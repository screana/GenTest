"""設計書から要件一覧とテスト仕様書を生成する（D-12：固定のワークフロー）。

    uv run python -m gentest.generate --run-name D-r1 --dry-run   # 呼び出し回数の見積もり
    uv run python -m gentest.generate --run-name D-r1              # 実行

各章について「生成 → 検証 → 不合格の項目だけ直させる」を繰り返す（D-05、D-14）。
結果は outputs/runs/<run-name>/ に保存する。
"""

import argparse
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from gentest import llm, prompts
from gentest.design_doc import DesignDoc
from gentest.schemas import Requirement, RequirementList, Spec, SpecCase
from gentest.validate import Issue, validate_requirements, validate_spec

RUNS_DIR = Path(__file__).resolve().parents[2] / "outputs" / "runs"
# 2章（用語の定義）と10章（出典一覧）は、テストの根拠になる要件を含まない
SKIP_CHAPTERS = {"2", "10"}
# 要件の抽出は実験条件に関係なく同じ手順で行う。比べたいのは仕様書の生成の違いだけ
EXTRACT_REPAIR_ROUNDS = 2


def _renumber[T: BaseModel](
    items: list[T], field: str, prefix: str, start: int
) -> list[T]:
    """ID はコードで振る（D-13）。"""
    return [
        it.model_copy(update={field: f"{prefix}-{n:03d}"})
        for n, it in enumerate(items, start)
    ]


def _dump(items: list[BaseModel]) -> str:
    return json.dumps(
        [it.model_dump(mode="json") for it in items], ensure_ascii=False, indent=2
    )


def _repair_loop[T: BaseModel](
    items: list[T],
    key: Callable[[T], str],
    check: Callable[[list[T]], list[Issue]],
    repair: Callable[[list[T], list[Issue]], list[T]],
    max_rounds: int,
) -> tuple[list[T], list[Issue]]:
    """検証を通らなかった項目だけを LLM に直させる。

    max_rounds 回直しても通らない項目は捨て、その指摘を返す。
    max_rounds が 0（検証と修正なしの条件）のときは、何も捨てずに指摘だけを返す。
    """
    issues = check(items)
    if max_rounds == 0:
        return items, issues
    for _ in range(max_rounds):
        if not issues:
            break
        bad = {i.item_id for i in issues}
        targets = [it for it in items if key(it) in bad]
        fixed = {key(f): f for f in repair(targets, issues) if key(f) in bad}
        items = [fixed.get(key(it), it) for it in items]
        issues = check(items)
    bad = {i.item_id for i in issues}
    return [it for it in items if key(it) not in bad], issues


def extract(
    doc: DesignDoc, chapter: str, *, start: int, cache_tag: str
) -> tuple[list[Requirement], list[Issue]]:
    def generate(request: str) -> list[Requirement]:
        return llm.generate_structured(
            [doc.text, request],
            RequirementList,
            system_instruction=prompts.EXTRACT_SYSTEM,
            cache_tag=cache_tag,
        ).requirements

    reqs = _renumber(generate(prompts.extract_request(chapter)), "req_id", "REQ", start)
    return _repair_loop(
        reqs,
        key=lambda r: r.req_id,
        check=lambda rs: validate_requirements(rs, doc),
        repair=lambda bad, issues: generate(
            prompts.repair_request(_dump(bad), _dump(issues))
        ),
        max_rounds=EXTRACT_REPAIR_ROUNDS,
    )


def make_spec(
    doc: DesignDoc,
    chapter: str,
    reqs: list[Requirement],
    *,
    system: str,
    viewpoints: set[str] | None,
    max_rounds: int,
    start: int,
    cache_tag: str,
) -> tuple[list[SpecCase], list[Issue]]:
    request = prompts.spec_request(chapter, _dump(reqs))

    def generate(*extra: str) -> list[SpecCase]:
        return llm.generate_structured(
            [doc.text, request, *extra],
            Spec,
            system_instruction=system,
            cache_tag=cache_tag,
        ).cases

    cases = _renumber(generate(), "tc_id", "TC", start)
    return _repair_loop(
        cases,
        key=lambda c: c.tc_id,
        check=lambda cs: validate_spec(cs, doc, reqs, viewpoints),
        repair=lambda bad, issues: generate(
            prompts.repair_request(_dump(bad), _dump(issues))
        ),
        max_rounds=max_rounds,
    )


def _chapter_of(section: str) -> str:
    return section.split(".")[0]


def run(
    run_name: str,
    *,
    use_checklist: bool,
    max_rounds: int,
    cache_tag: str,
    dry_run: bool,
    only: list[str] | None = None,
) -> None:
    doc = DesignDoc.load()
    chapters = [s.number for s in doc.chapters() if s.number not in SKIP_CHAPTERS]
    if only:
        chapters = [ch for ch in chapters if ch in only]
    checklist, viewpoint_names = prompts.load_checklist()
    system = prompts.spec_system(checklist if use_checklist else None)
    viewpoints = viewpoint_names if use_checklist else None

    if dry_run:
        n = len(chapters)
        print(f"対象の章: {', '.join(chapters)}")
        print(
            f"LLM 呼び出し: 最少 {2 * n} 回、最多 "
            f"{n * (1 + EXTRACT_REPAIR_ROUNDS) + n * (1 + max_rounds)} 回"
            "（キャッシュ済みの分は呼ばない）"
        )
        print(
            f"1回あたりの入力: 設計書 {len(doc.text):,} 文字"
            f" + 指示 {len(system):,} 文字（仕様書の生成時）+ 要件一覧"
        )
        return

    reqs: list[Requirement] = []
    cases: list[SpecCase] = []
    req_issues: dict[str, list[Issue]] = {}
    spec_issues: dict[str, list[Issue]] = {}

    for ch in chapters:
        got, req_issues[ch] = extract(doc, ch, start=len(reqs) + 1, cache_tag=cache_tag)
        reqs += got
        print(f"{ch}章: 要件 {len(got)} 件（未解決の指摘 {len(req_issues[ch])} 件）")

    for ch in chapters:
        ch_reqs = [r for r in reqs if _chapter_of(r.section) == ch]
        if not ch_reqs:
            continue
        got, spec_issues[ch] = make_spec(
            doc,
            ch,
            ch_reqs,
            system=system,
            viewpoints=viewpoints,
            max_rounds=max_rounds,
            # 捨てたケースがあると欠番になるが、指摘の ID と突き合わせられるよう振り直さない
            start=len(cases) + 1,
            cache_tag=cache_tag,
        )
        cases += got
        print(
            f"{ch}章: テストケース {len(got)} 件（未解決の指摘 {len(spec_issues[ch])} 件）"
        )

    all_spec_issues = [i for v in spec_issues.values() for i in v]
    used = {c.viewpoint for c in cases}
    summary = {
        "run_name": run_name,
        "use_checklist": use_checklist,
        "repair_rounds": max_rounds,
        "cache_tag": cache_tag,
        "requirements": len(reqs),
        "cases": len(cases),
        "status": Counter(c.status.value for c in cases),
        "viewpoints": Counter(c.viewpoint for c in cases),
        "unused_viewpoints": sorted(viewpoint_names - used),
        "unresolved_issues": Counter(i.code for i in all_spec_issues),
    }

    out = RUNS_DIR / run_name
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "requirements.json": RequirementList(requirements=reqs).model_dump_json(
            indent=2
        ),
        "spec.json": Spec(cases=cases).model_dump_json(indent=2),
        "issues.json": json.dumps(
            {
                "requirements": {
                    k: [i.model_dump() for i in v] for k, v in req_issues.items()
                },
                "spec": {
                    k: [i.model_dump() for i in v] for k, v in spec_issues.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        "summary.json": json.dumps(summary, ensure_ascii=False, indent=2),
    }
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    print(f"保存先: {out}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-name", required=True)
    p.add_argument(
        "--no-checklist", action="store_true", help="観点チェックリストを渡さない"
    )
    p.add_argument(
        "--repair-rounds",
        type=int,
        default=2,
        help="仕様書の検証と修正の最大回数。0 で検証と修正なし",
    )
    p.add_argument(
        "--cache-tag", default="", help="同じ条件を繰り返すときに変える（D-08）"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="LLM を呼ばずに見積もりだけ出す"
    )
    p.add_argument(
        "--chapters", nargs="+", help="対象の章を絞る（例: --chapters 3）。試行用"
    )
    a = p.parse_args()
    run(
        a.run_name,
        use_checklist=not a.no_checklist,
        max_rounds=a.repair_rounds,
        cache_tag=a.cache_tag,
        dry_run=a.dry_run,
        only=a.chapters,
    )


if __name__ == "__main__":
    main()
