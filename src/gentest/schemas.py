"""パイプライン各段階の入出力スキーマ。

クラス名を Test で始めないのは、pytest がテストクラスとして収集しないようにするため。

根拠の追跡（設計書 → 要件 → テストケース → テスト関数）は、
REQ-ID・章番号・引用文の3点で行う。引用文は validate.py で設計書原本と照合する。
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class RequirementKind(StrEnum):
    NORMAL = "正常系"
    BOUNDARY = "境界"
    PERIOD = "適用期間"
    SPECIAL = "特例"
    DEPENDENCY = "依存関係"
    ERROR = "異常系"


class Requirement(BaseModel):
    req_id: str = Field(description="要件ID。REQ-001 形式の連番")
    section: str = Field(description="設計書の章番号（例: 3.2.1）")
    quote: str = Field(description="根拠となる設計書の記述をそのまま引用したもの")
    kind: RequirementKind
    summary: str = Field(description="要件の要約（1文）")


class RequirementList(BaseModel):
    requirements: list[Requirement]


class Evidence(BaseModel):
    req_id: str
    section: str
    quote: str = Field(
        description="期待結果の根拠となる設計書の記述をそのまま引用したもの"
    )


class SpecCase(BaseModel):
    tc_id: str = Field(description="テストケースID。TC-001 形式の連番")
    target: str = Field(description="テスト対象の関数・クラス名")
    viewpoint: str = Field(description="観点（観点チェックリストの項目名）")
    precondition: str = Field(description="前提条件。なければ空文字")
    input: str = Field(
        description="入力値。Python のリテラル表記（例: datetime.date(2024, 1, 8)）"
    )
    expected: str = Field(
        description="期待結果。Python のリテラル表記（例: '成人の日'、True、None）"
    )
    evidence: list[Evidence] = Field(min_length=1)


class Spec(BaseModel):
    cases: list[SpecCase]
