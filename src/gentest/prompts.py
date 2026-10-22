"""各段階のプロンプト。

Few-shot は架空の設計書から作る。本物の設計書のケースを例に使うと、そのケースの答えを
教えたことになり評価できなくなるため。例は確定2件・確認待ち1件とし、
何でも確認待ちにする偏りを防ぐ（D-09）。Few-shot はどの実験条件でも同じものを使う。
"""

import json
import re
from pathlib import Path

CHECKLIST = Path(__file__).resolve().parents[2] / "checklists" / "viewpoints.md"

EXTRACT_SYSTEM = """\
あなたはテスト設計者です。顧客から受け取った詳細設計書から、単体テストの根拠となる要件を抽出します。

規則
- 指定された章だけを対象にする。
- 1つの要件には、検証できる事柄を1つだけ書く。
- quote には設計書の文をそのまま書き写す。要約・言い換え・省略をせず、「…」でつながない。末尾の出典の括弧書きは省いてよい。
- section には、quote がある最も深い章番号（例: 3.3.1）を書く。9章の未定義事項は項目番号（例: 9.3.6）を書く。
- 一覧表は行ごとに要件にしない。表の前にある、表の意味を説明する文を要件にする。
- 9章の項目は kind を「未定義事項」にする。
- req_id は仮の連番でよい（後で振り直す）。
"""

_SPEC_RULES = """\
あなたはテスト設計者です。詳細設計書と要件一覧から、単体テスト仕様書のテストケースを作ります。

規則
- 期待結果は設計書の記述から導く。設計書に書かれていない挙動を推測して期待結果にしない。
- 期待結果の根拠が設計書にあれば status を「確定」にする。
- 期待結果の根拠がなく、9章の未定義事項に当たるときだけ status を「確認待ち」にする。このとき expected は null、question に顧客に確認する内容を書き、evidence には 9章の項目を含める。
- 設計書に定めがある挙動を「確認待ち」にしない。確定のケースは 9章を根拠にしない。
- target は is_holiday, is_holiday_name, year_holidays, month_holidays, between のいずれか。
- input は関数に渡す引数を Python の式で書く。複数あるときはカンマで区切り、全体を括弧で囲まない。
- input と expected に使ってよいのは、数値・文字列・None・True・False・リスト・タプル・datetime.date(...)・datetime.datetime(...) だけ。
- 一覧を返す関数の expected は [(datetime.date(2017, 5, 3), '憲法記念日'), ...] の形で書く。
- evidence の req_id は要件一覧のものを使う。quote は設計書の原文をそのまま書き写す。
- tc_id は仮の連番でよい（後で振り直す）。
"""

_FEW_SHOT_DOC = """\
### 5.1 森の日
- 2010年以降、6月の第1月曜日は「森の日」である。

### 9.2 引数に関する事項
- 9.2.1 `year` に負の数を渡したときの挙動。
"""

_FEW_SHOT_CASES = [
    {
        "tc_id": "TC-001",
        "target": "is_holiday_name",
        "viewpoint": "代表日",
        "precondition": "",
        "input": "datetime.date(2010, 6, 7)",
        "status": "確定",
        "expected": "'森の日'",
        "question": None,
        "evidence": [
            {
                "req_id": "REQ-001",
                "section": "5.1",
                "quote": "2010年以降、6月の第1月曜日は「森の日」である。",
            }
        ],
    },
    {
        "tc_id": "TC-002",
        "target": "is_holiday",
        "viewpoint": "代表日",
        "precondition": "",
        "input": "datetime.date(2010, 6, 7)",
        "status": "確定",
        "expected": "True",
        "question": None,
        "evidence": [
            {
                "req_id": "REQ-001",
                "section": "5.1",
                "quote": "2010年以降、6月の第1月曜日は「森の日」である。",
            }
        ],
    },
    {
        "tc_id": "TC-003",
        "target": "year_holidays",
        "viewpoint": "未定義事項",
        "precondition": "",
        "input": "-1",
        "status": "確認待ち",
        "expected": None,
        "question": "year に負の数を渡したとき、例外を送出するか、空のリストを返すか。",
        "evidence": [
            {
                "req_id": "REQ-002",
                "section": "9.2.1",
                "quote": "9.2.1 `year` に負の数を渡したときの挙動。",
            }
        ],
    },
]

_FEW_SHOT = f"""\
例（架空の設計書）

設計書:
{_FEW_SHOT_DOC}
テストケース:
{json.dumps(_FEW_SHOT_CASES, ensure_ascii=False, indent=2)}
"""


def load_checklist(path: Path = CHECKLIST) -> tuple[str, set[str]]:
    """チェックリストの本文と、観点名（「## 」の見出し）の集合を返す。"""
    text = path.read_text(encoding="utf-8")
    return text, set(re.findall(r"^## (.+)$", text, flags=re.MULTILINE))


def spec_system(checklist: str | None) -> str:
    """checklist を渡すと、観点チェックリストを使う条件のプロンプトになる（D-05 の Skills 相当）。"""
    if checklist is None:
        viewpoint_rule = "- viewpoint には、そのケースで確かめる観点を短く書く。\n"
        return _SPEC_RULES + viewpoint_rule + "\n" + _FEW_SHOT
    viewpoint_rule = (
        "- 次の観点チェックリストの各観点について、当てはまるものはすべてテストケースにする。\n"
        "- viewpoint には、チェックリストの観点名をそのまま書く。\n"
    )
    return _SPEC_RULES + viewpoint_rule + "\n" + checklist + "\n" + _FEW_SHOT


def extract_request(chapter: str) -> str:
    return f"設計書の {chapter}章から要件を抽出してください。"


def spec_request(chapter: str, requirements_json: str) -> str:
    return (
        f"設計書の {chapter}章の要件について、テストケースを作ってください。\n\n"
        f"要件一覧:\n{requirements_json}"
    )


def repair_request(items_json: str, issues_json: str) -> str:
    return (
        "次の項目は機械的な検証で不合格になりました。指摘に従って直し、同じ ID のまま返してください。"
        "直せない項目は返さなくてかまいません。\n\n"
        f"項目:\n{items_json}\n\n指摘:\n{issues_json}"
    )
