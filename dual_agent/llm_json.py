from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable
from typing import Any


def coerce_llm_text(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x.strip()
    return str(x).strip()


def coerce_llm_bool(x: Any) -> bool:
    """避免 bool('false')==True 等字串誤判。"""
    if isinstance(x, bool):
        return x
    if x is None:
        return False
    if isinstance(x, (int, float)):
        return x != 0
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("true", "1", "yes", "y", "t", "是", "對", "完成", "ok"):
            return True
        if s in ("false", "0", "no", "n", "f", "否", "錯", ""):
            return False
    return False


_FULLWIDTH_QUOTE_MAP = str.maketrans(
    {
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
    }
)


def _normalize_json_candidate(s: str) -> str:
    s = s.strip().lstrip("\ufeff")
    s = s.translate(_FULLWIDTH_QUOTE_MAP)
    # 移除 trailing comma（物件／陣列結尾）
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


def _try_parse_json_object(s: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(s)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    if s.startswith("{"):
        try:
            obj = ast.literal_eval(s)
            if isinstance(obj, dict):
                return obj
        except (SyntaxError, ValueError):
            pass
    return None


def extract_json_object(raw: str) -> dict[str, Any]:
    """
    從模型輸出中擷取第一個 JSON 物件。
    - 允許 ```json ... ``` code fence
    - 忽略 JSON 後的多餘文字（避免 Extra data）
    - 嘗試修復 trailing comma、全形引號、Python 單引號 dict
    """
    s = coerce_llm_text(raw)
    if not s:
        raise ValueError("模型回傳空白")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()
    s = s.strip()
    start = s.find("{")
    if start < 0:
        raise ValueError("模型回傳中找不到 JSON 物件（應為物件型態的左大括號開頭）")
    candidate = _normalize_json_candidate(s[start:])
    obj = _try_parse_json_object(candidate)
    if obj is not None:
        return obj
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(candidate)
    except json.JSONDecodeError as e:
        raise ValueError(f"無法解析計畫 JSON：{e}") from e
    if not isinstance(obj, dict):
        raise ValueError("JSON 根節點必須是物件")
    return obj


def invoke_and_parse_json(
    invoke: Callable[[], str],
    *,
    retry_invoke: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """呼叫 LLM 取得字串並解析 JSON；失敗時可選重試一次。"""
    try:
        return extract_json_object(invoke())
    except ValueError:
        if retry_invoke is None:
            raise
        return extract_json_object(retry_invoke())
