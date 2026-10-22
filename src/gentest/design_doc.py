"""設計書（Markdown）を章番号ごとに分け、引用文を照合する。

章は「## 1. 概要」「### 3.3 成人の日」「#### 3.3.1 日付」の見出しで区切る。
9章の未定義事項は見出しではなく「- 9.3.6 ...」の箇条書きなので、項目番号でも引けるようにする。
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

DESIGN_DOC = (
    Path(__file__).resolve().parents[2] / "docs" / "design" / "detailed_design.md"
)

_HEADING = re.compile(r"^(#{2,4}) (\d+(?:\.\d+)*)\.? (.+)$")
_ITEM = re.compile(r"^- (\d+\.\d+\.\d+) ")
# 照合では、LLM が書き写すときに崩しやすい記号を無視する
_IGNORED = re.compile(r"[\s|`*]")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text.strip().removeprefix("- "))
    return _IGNORED.sub("", text)


@dataclass(frozen=True)
class Section:
    number: str
    title: str
    text: str


class DesignDoc:
    def __init__(self, text: str) -> None:
        self.text = text
        self.sections: dict[str, Section] = {}
        lines = text.splitlines()
        headings = [
            (i, len(m[1]), m[2], m[3])
            for i, line in enumerate(lines)
            if (m := _HEADING.match(line))
        ]
        for n, (start, level, number, title) in enumerate(headings):
            # 次の同じ階層以上の見出しまでを、その章の本文とする（下位の節を含む）
            end = next(
                (i for i, lv, _, _ in headings[n + 1 :] if lv <= level), len(lines)
            )
            self.sections[number] = Section(number, title, "\n".join(lines[start:end]))
        for line in lines:
            if m := _ITEM.match(line):
                self.sections.setdefault(m[1], Section(m[1], "", line))
        self._normalized = {k: normalize(s.text) for k, s in self.sections.items()}

    @classmethod
    def load(cls, path: Path = DESIGN_DOC) -> "DesignDoc":
        return cls(path.read_text(encoding="utf-8"))

    def chapters(self) -> list[Section]:
        return [s for k, s in self.sections.items() if "." not in k]

    def contains(self, section: str, quote: str) -> bool:
        body = self._normalized.get(section)
        return body is not None and normalize(quote) in body

    def locate(self, quote: str) -> list[str]:
        """引用文を含む最も深い章番号を返す。修正の指摘に使う。"""
        hits = [k for k in self._normalized if self.contains(k, quote)]
        return [k for k in hits if not any(h.startswith(k + ".") for h in hits)]
