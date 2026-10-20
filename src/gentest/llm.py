"""Gemini（Vertex AI）呼び出しの共通処理。

接続方法は mock/.ipynb と同じ（.env の GOOGLE_GENAI_USE_VERTEXAI 等を読む）。
モデル名はここで一元管理し、実験条件ごとに切り替えられるようにする。
"""

from functools import cache
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()

DEFAULT_MODEL = "gemini-3.8-flash"


@cache
def get_client() -> genai.Client:
    return genai.Client()


def pdf_part(path: Path) -> types.Part:
    """PDF をそのまま Gemini に渡すための Part を作る。"""
    return types.Part.from_bytes(data=path.read_bytes(), mime_type="application/pdf")


def generate_text(
    contents: list[types.Part | str] | str,
    *,
    system_instruction: str | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float | None = None,
) -> str:
    res = get_client().models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
        ),
    )
    return res.text or ""


def generate_structured[T: BaseModel](
    contents: list[types.Part | str] | str,
    schema: type[T],
    *,
    system_instruction: str | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float | None = None,
) -> T:
    """JSON スキーマを指定して生成し、Pydantic モデルとして検証して返す。"""
    res = get_client().models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    return schema.model_validate_json(res.text or "")
