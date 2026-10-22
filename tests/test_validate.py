"""パイプラインのうち、LLM を呼ばない部分のテスト。"""

import datetime

import pytest

from gentest.design_doc import DesignDoc
from gentest.generate import _repair_loop
from gentest.prompts import _FEW_SHOT_CASES, load_checklist
from gentest.schemas import Evidence, Requirement, RequirementKind, SpecCase
from gentest.validate import (
    Issue,
    ParseError,
    parse_args,
    parse_value,
    validate_spec,
)


@pytest.fixture(scope="module")
def doc() -> DesignDoc:
    return DesignDoc.load()


REQS = [
    Requirement(
        req_id="REQ-001",
        section="3.3.1",
        quote="2000年以降、成人の日は1月の第2月曜日である。",
        kind=RequirementKind.PERIOD,
        summary="2000年以降の成人の日",
    ),
    Requirement(
        req_id="REQ-002",
        section="9.3.6",
        quote="`between` で `start_date` が `end_date` より後の日付のときの挙動",
        kind=RequirementKind.UNDEFINED,
        summary="between の引数が逆順のとき",
    ),
]


def case(**kw: object) -> SpecCase:
    base: dict[str, object] = {
        "tc_id": "TC-001",
        "target": "is_holiday_name",
        "viewpoint": "代表日",
        "precondition": "",
        "input": "datetime.date(2024, 1, 8)",
        "status": "確定",
        "expected": "'成人の日'",
        "question": None,
        "evidence": [Evidence(req_id="REQ-001", section="3.3.1", quote=REQS[0].quote)],
    }
    return SpecCase.model_validate(base | kw)


def codes(issues: list[Issue]) -> set[str]:
    return {i.code for i in issues}


class TestDesignDoc:
    def test_sections(self, doc: DesignDoc) -> None:
        chapters = [s.number for s in doc.chapters()]
        assert chapters == [str(n) for n in range(1, 11)]
        assert doc.sections["3.3"].title == "成人の日"
        # 上位の章は下位の節を含む
        assert "第2月曜日" in doc.sections["3"].text
        assert "第2月曜日" not in doc.sections["3.4"].text

    def test_undefined_items_are_sections(self, doc: DesignDoc) -> None:
        assert "start_date" in doc.sections["9.3.6"].text

    def test_contains_ignores_markup(self, doc: DesignDoc) -> None:
        # 箇条書きの記号、バッククォート、表の区切り、全角括弧の違いは無視する
        assert doc.contains("9.3.6", "- between で start_date が end_date より後")
        assert doc.contains("4.2", "1949 | 1949-03-21(月)")
        assert not doc.contains("3.3.1", "2000年以降、成人の日は1月の第3月曜日である。")

    def test_locate_returns_deepest(self, doc: DesignDoc) -> None:
        assert doc.locate("1949年から1999年まで、成人の日は1月15日である。") == [
            "3.3.1"
        ]


class TestParse:
    def test_values(self) -> None:
        assert parse_value("[(datetime.date(2017, 5, 3), '憲法記念日')]") == [
            (datetime.date(2017, 5, 3), "憲法記念日")
        ]
        assert parse_args("2017, 5") == (2017, 5)
        assert parse_args("datetime.date(2017, 1, 1)") == (datetime.date(2017, 1, 1),)

    @pytest.mark.parametrize(
        "src",
        [
            "__import__('os')",
            "datetime.date.__class__",
            "open('x')",
            "datetime.date(2024, 2, 30)",  # 存在しない日付
            "datetime.date(year=2024, month=1, day=1)",
        ],
    )
    def test_rejects(self, src: str) -> None:
        with pytest.raises(ParseError):
            parse_value(src)


class TestValidateSpec:
    def test_valid(self, doc: DesignDoc) -> None:
        assert validate_spec([case()], doc, REQS) == []

    def test_quote_in_other_section_gets_hint(self, doc: DesignDoc) -> None:
        ev = Evidence(req_id="REQ-001", section="3.3.2", quote=REQS[0].quote)
        [issue] = validate_spec([case(evidence=[ev])], doc, REQS)
        assert issue.code == "quote_not_found"
        assert "3.3.1" in issue.message

    def test_paraphrased_quote(self, doc: DesignDoc) -> None:
        ev = Evidence(
            req_id="REQ-001", section="3.3.1", quote="成人の日は2000年から第2月曜日"
        )
        assert codes(validate_spec([case(evidence=[ev])], doc, REQS)) == {
            "quote_not_found"
        }

    def test_input(self, doc: DesignDoc) -> None:
        assert codes(
            validate_spec([case(input="(2017, 5)", target="month_holidays")], doc, REQS)
        ) == {"wrong_arity"}
        assert codes(validate_spec([case(target="is_weekend")], doc, REQS)) == {
            "unknown_target"
        }

    def test_viewpoint_checked_only_with_checklist(self, doc: DesignDoc) -> None:
        _, names = load_checklist()
        c = case(viewpoint="なんとなく")
        assert validate_spec([c], doc, REQS) == []
        assert codes(validate_spec([c], doc, REQS, names)) == {"unknown_viewpoint"}

    def test_pending_must_cite_undefined(self, doc: DesignDoc) -> None:
        # 設計書に定めがあるのに確認待ちにした
        c = case(status="確認待ち", expected=None, question="成人の日はいつか")
        assert codes(validate_spec([c], doc, REQS)) == {"pending_without_undefined"}

    def test_pending_valid(self, doc: DesignDoc) -> None:
        ev = Evidence(req_id="REQ-002", section="9.3.6", quote=REQS[1].quote)
        c = case(
            target="between",
            input="datetime.date(2017, 5, 3), datetime.date(2017, 1, 1)",
            status="確認待ち",
            expected=None,
            question="空のリストを返すか、例外を送出するか",
            evidence=[ev],
        )
        assert validate_spec([c], doc, REQS) == []
        # 確認待ちなのに期待値を推測で書いた
        assert codes(
            validate_spec([c.model_copy(update={"expected": "[]"})], doc, REQS)
        ) == {"pending_with_expected"}
        # 未定義事項を根拠にしているのに確定にした
        confirmed = c.model_copy(
            update={"status": "確定", "expected": "[]", "question": None}
        )
        assert codes(validate_spec([confirmed], doc, REQS)) == {
            "confirmed_with_undefined"
        }


def test_few_shot_matches_schema() -> None:
    for c in _FEW_SHOT_CASES:
        SpecCase.model_validate(c)


class TestRepairLoop:
    @staticmethod
    def check(items: list[SpecCase]) -> list[Issue]:
        return [
            Issue(item_id=c.tc_id, code="bad", message="")
            for c in items
            if c.expected == "'誤り'"
        ]

    def test_repairs_only_bad_items(self) -> None:
        items = [case(tc_id="TC-001"), case(tc_id="TC-002", expected="'誤り'")]
        sent: list[list[str]] = []

        def repair(bad: list[SpecCase], _: list[Issue]) -> list[SpecCase]:
            sent.append([c.tc_id for c in bad])
            return [c.model_copy(update={"expected": "'成人の日'"}) for c in bad]

        kept, issues = _repair_loop(items, lambda c: c.tc_id, self.check, repair, 2)
        assert sent == [["TC-002"]]
        assert [c.tc_id for c in kept] == ["TC-001", "TC-002"]
        assert issues == []

    def test_drops_unfixable_items(self) -> None:
        items = [case(tc_id="TC-001"), case(tc_id="TC-002", expected="'誤り'")]
        kept, issues = _repair_loop(
            items, lambda c: c.tc_id, self.check, lambda bad, _: bad, 2
        )
        assert [c.tc_id for c in kept] == ["TC-001"]
        assert [i.item_id for i in issues] == ["TC-002"]

    def test_no_repair_keeps_everything(self) -> None:
        items = [case(tc_id="TC-001"), case(tc_id="TC-002", expected="'誤り'")]
        kept, issues = _repair_loop(
            items, lambda c: c.tc_id, self.check, lambda bad, _: [], 0
        )
        assert len(kept) == 2
        assert len(issues) == 1
