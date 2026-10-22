"""LLM の出力を機械的に検証する（D-05 の Hooks 相当）。

指摘は Issue として返し、generate.py がそのまま JSON で LLM に渡して直させる。
そのため message には「何が違うか」だけでなく「どう直すか」を書く。
"""

import ast
import datetime

from pydantic import BaseModel

from gentest.design_doc import DesignDoc
from gentest.schemas import CaseStatus, Requirement, SpecCase

# 設計書 8章の公開インタフェースと、その引数の数
PUBLIC_FUNCTIONS = {
    "is_holiday": 1,
    "is_holiday_name": 1,
    "year_holidays": 1,
    "month_holidays": 2,
    "between": 2,
}
MIN_QUOTE_LENGTH = 6
UNDEFINED_CHAPTER = "9"


class Issue(BaseModel):
    item_id: str
    code: str
    message: str


def _check_quote(
    doc: DesignDoc, item_id: str, section: str, quote: str, where: str = ""
) -> list[Issue]:
    if section not in doc.sections:
        return [
            Issue(
                item_id=item_id,
                code="section_not_found",
                message=f"{where}章番号 {section} は設計書にありません。",
            )
        ]
    if len(quote.strip()) < MIN_QUOTE_LENGTH:
        return [
            Issue(
                item_id=item_id,
                code="quote_too_short",
                message=f"{where}引用文が短すぎます。根拠となる文を1文まるごと書き写してください。",
            )
        ]
    if doc.contains(section, quote):
        return []
    found = doc.locate(quote)
    hint = (
        f"この文は {', '.join(found)} にあります。章番号を直してください。"
        if found
        else "設計書の原文と一致しません。要約・言い換え・省略をせず、連続した1か所をそのまま書き写してください。"
    )
    return [
        Issue(
            item_id=item_id,
            code="quote_not_found",
            message=f"{where}引用文が {section} にありません。{hint}",
        )
    ]


def validate_requirements(reqs: list[Requirement], doc: DesignDoc) -> list[Issue]:
    issues: list[Issue] = []
    for r in reqs:
        issues += _check_quote(doc, r.req_id, r.section, r.quote)
    return issues


_ALLOWED_NODES = (
    ast.Expression,
    ast.Constant,
    ast.Tuple,
    ast.List,
    ast.UnaryOp,
    ast.USub,
    ast.Load,
    ast.Call,
    ast.Attribute,
    ast.Name,
)


# parse_value が投げうる例外。存在しない日付や引数の数の誤りは eval の時点で出る
ParseError = (SyntaxError, ValueError, TypeError)


def _allowed(node: ast.AST) -> bool:
    if not isinstance(node, _ALLOWED_NODES):
        return False
    if isinstance(node, ast.Name):
        return node.id == "datetime"
    if isinstance(node, ast.Attribute):
        return node.attr in ("date", "datetime")
    if isinstance(node, ast.Call):
        return not node.keywords
    return True


def parse_value(src: str) -> object:
    """仕様書の input / expected を Python の値にする。

    使えるのはリテラルと datetime.date / datetime.datetime の位置引数での呼び出しだけ。
    任意の式を eval しないよう、構文木を先に確かめる。
    """
    tree = ast.parse(src, mode="eval")
    if bad := next((n for n in ast.walk(tree) if not _allowed(n)), None):
        raise ValueError(f"使えない式です: {ast.unparse(bad)}")
    return eval(
        compile(tree, "<spec>", "eval"), {"__builtins__": {}, "datetime": datetime}
    )


def parse_args(src: str) -> tuple[object, ...]:
    return parse_value(f"({src},)")  # type: ignore[return-value]


def _check_case(
    case: SpecCase,
    doc: DesignDoc,
    req_ids: set[str],
    viewpoints: set[str] | None,
) -> list[Issue]:
    def issue(code: str, message: str) -> Issue:
        return Issue(item_id=case.tc_id, code=code, message=message)

    issues: list[Issue] = []

    if case.target not in PUBLIC_FUNCTIONS:
        issues.append(
            issue(
                "unknown_target",
                f"target は {', '.join(PUBLIC_FUNCTIONS)} のいずれかにしてください。",
            )
        )
    else:
        try:
            args = parse_args(case.input)
            if len(args) != PUBLIC_FUNCTIONS[case.target]:
                issues.append(
                    issue(
                        "wrong_arity",
                        f"{case.target} の引数は {PUBLIC_FUNCTIONS[case.target]} 個ですが、"
                        f"input は {len(args)} 個です。引数をカンマで区切り、全体を括弧で囲まないでください。",
                    )
                )
        except ParseError as e:
            issues.append(
                issue("bad_input", f"input を Python の式として読めません（{e}）。")
            )

    if viewpoints is not None and case.viewpoint not in viewpoints:
        issues.append(
            issue(
                "unknown_viewpoint",
                "viewpoint は観点チェックリストの観点名をそのまま書いてください。",
            )
        )

    for i, ev in enumerate(case.evidence, 1):
        where = f"evidence[{i}] の"
        if ev.req_id not in req_ids:
            issues.append(
                issue(
                    "unknown_req_id",
                    f"{where}req_id {ev.req_id} は要件一覧にありません。",
                )
            )
        issues += [
            issue(x.code, x.message)
            for x in _check_quote(doc, case.tc_id, ev.section, ev.quote, where)
        ]

    # D-09：確認待ちかどうかは、根拠が 9章（未定義事項）かどうかと一致しなければならない
    cites_undefined = any(
        ev.section.split(".")[0] == UNDEFINED_CHAPTER for ev in case.evidence
    )
    if case.status == CaseStatus.PENDING:
        if case.expected is not None:
            issues.append(
                issue(
                    "pending_with_expected",
                    "確認待ちのケースは期待値の根拠がないので、expected を null にしてください。",
                )
            )
        if not case.question:
            issues.append(
                issue(
                    "pending_without_question",
                    "顧客に確認する内容を question に書いてください。",
                )
            )
        if not cites_undefined:
            issues.append(
                issue(
                    "pending_without_undefined",
                    "確認待ちのケースは 9章の未定義事項を根拠にしてください。"
                    "設計書に定めがある挙動なら、確定にして期待値を書いてください。",
                )
            )
    else:
        if case.expected is None:
            issues.append(
                issue(
                    "confirmed_without_expected",
                    "確定のケースは expected を書いてください。",
                )
            )
        else:
            try:
                parse_value(case.expected)
            except ParseError as e:
                issues.append(
                    issue(
                        "bad_expected",
                        f"expected を Python の式として読めません（{e}）。",
                    )
                )
        if cites_undefined:
            issues.append(
                issue(
                    "confirmed_with_undefined",
                    "9章の未定義事項を根拠にするケースは、確認待ちにしてください。",
                )
            )
    return issues


def validate_spec(
    cases: list[SpecCase],
    doc: DesignDoc,
    reqs: list[Requirement],
    viewpoints: set[str] | None = None,
) -> list[Issue]:
    """viewpoints を渡したときだけ、観点名がチェックリストにあるかを確かめる。"""
    req_ids = {r.req_id for r in reqs}
    return [i for c in cases for i in _check_case(c, doc, req_ids, viewpoints)]
