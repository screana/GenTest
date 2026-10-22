"""Gemini（Vertex AI）呼び出しの共通処理。

接続方法は mock/.ipynb と同じ（.env の GOOGLE_GENAI_USE_VERTEXAI 等を読む）。
モデル名はここで一元管理し、実験条件ごとに切り替えられるようにする。

API の利用料を抑えるため、応答は outputs/cache/ にキャッシュする。
同じ入力でも別の生成結果がほしいとき（実験の繰り返しなど）は cache_tag を変える。
"""

import hashlib
import json
from collections.abc import Callable
from functools import cache
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()

DEFAULT_MODEL = "gemini-3.8-flash"
CACHE_DIR = Path(__file__).resolve().parents[2] / "outputs" / "cache"

Contents = list[types.Part | str] | str


@cache
def get_client() -> genai.Client:
    return genai.Client()


def pdf_part(path: Path) -> types.Part:
    """PDF をそのまま Gemini に渡すための Part を作る。"""
    return types.Part.from_bytes(data=path.read_bytes(), mime_type="application/pdf")


def _cache_key(contents: Contents, **params: object) -> str:
    items = [contents] if isinstance(contents, str) else contents
    h = hashlib.sha256()
    for item in items:
        h.update(
            item.encode() if isinstance(item, str) else item.model_dump_json().encode()
        )
    h.update(json.dumps(params, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


def _generate[R](
    contents: Contents,
    config: types.GenerateContentConfig,
    *,
    model: str,
    cache_tag: str,
    schema_name: str | None,
    parse: Callable[[str], R],
) -> R:
    key = _cache_key(
        contents,
        model=model,
        cache_tag=cache_tag,
        schema=schema_name,
        system_instruction=config.system_instruction,
        temperature=config.temperature,
    )
    path = CACHE_DIR / f"{key}.txt"
    if path.exists():
        return parse(path.read_text(encoding="utf-8"))

    res = get_client().models.generate_content(
        model=model, contents=contents, config=config
    )
    text = res.text or ""
    # 読めない応答（途中で切れた JSON など）をキャッシュすると、同じ入力で毎回失敗するため先に検証する
    result = parse(text)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return result


def generate_text(
    contents: Contents,
    *,
    system_instruction: str | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float | None = None,
    cache_tag: str = "",
) -> str:
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature,
    )
    return _generate(
        contents, config, model=model, cache_tag=cache_tag, schema_name=None, parse=str
    )


def generate_structured[T: BaseModel](
    contents: Contents,
    schema: type[T],
    *,
    system_instruction: str | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float | None = None,
    cache_tag: str = "",
) -> T:
    """JSON スキーマを指定して生成し、Pydantic モデルとして検証して返す。"""
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=schema,
    )
    return _generate(
        contents,
        config,
        model=model,
        cache_tag=cache_tag,
        # スキーマを変更したら古いキャッシュを使わないよう、定義全体をキーに含める
        schema_name=json.dumps(schema.model_json_schema(), sort_keys=True),
        parse=schema.model_validate_json,
    )
