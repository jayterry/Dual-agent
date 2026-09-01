"""內部輔助：關鍵字命中強度。"""

from __future__ import annotations

import math
import re


def count_keyword_hits(text: str, keywords: list[str]) -> int:
    t = text.casefold()
    hits = 0
    for kw in keywords:
        if kw.casefold() in t:
            hits += 1
    return hits


def score_from_hits(hits: int, saturate_at: int = 3) -> float:
    """命中數轉 0~1；saturate_at 次滿分為 1。"""
    if hits <= 0:
        return 0.0
    return min(1.0, hits / float(saturate_at))


def find_money_amounts(text: str) -> list[float]:
    """抓取常見金額表示（元／萬／$／% 以外的數字金額）。"""
    amounts: list[float] = []
    # 12萬 / 12.5万
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*萬", text):
        amounts.append(float(m.group(1)) * 10000)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*万", text):
        amounts.append(float(m.group(1)) * 10000)
    # $1,234.56 or 1234元
    for m in re.finditer(r"[$＄]\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)", text):
        amounts.append(float(m.group(1).replace(",", "")))
    for m in re.finditer(r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*元", text):
        amounts.append(float(m.group(1).replace(",", "")))
    return amounts


def log_money_amount(text: str) -> float:
    amounts = find_money_amounts(text)
    if not amounts:
        # 月獲利 20% 這類非金額本體 → 0
        return 0.0
    return float(math.log1p(max(amounts)))
