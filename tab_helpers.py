"""跨 tab_*.py 共用的純函式 — Phase 7A 抽純函式（2026-05-16）

零 Streamlit / Plotly 依賴，無 side effect。
從 tab_stock.py / tab_stock_grp.py / tab_macro.py 內部抽出的重複工具。

設計原則：
- pure function：相同輸入恆等輸出
- 防呆優先：所有 helper 對 None / NaN / 缺欄位皆有 fallback
- 易測：對應 tests/test_tab_helpers.py 完整 coverage
"""
from __future__ import annotations

import re
from typing import Any, Optional

import pandas as pd

_PCT_RE = re.compile(r'(-?\d+(?:\.\d+)?)\s*%')


def parse_cash_flow_ratio(value: Any, threshold: float, strict: bool = False) -> Optional[bool]:
    """解析含百分比字串並對照門檻 — 取代 tab_stock._r110_ok_a / tab_stock_grp._r110_ok_b。

    對應 financial_health_engine 的 Rule 100/100/10 三項檢核
    （A: Cash_Flow_Ratio > 100% 嚴格 / B: Cash_Flow_Adequacy ≥ 100% / C: Cash_Reinvestment > 10% 嚴格）。

    Args:
        value: 含 "%" 的字串、None、或 "N/A"
        threshold: 比較門檻（數值，單位 %）
        strict: True → 嚴格 `>`；False → `>=`

    Returns:
        True / False / None（值缺失或無法解析）
    """
    s = str(value or '')
    if not s or 'N/A' in s:
        return None
    m = _PCT_RE.search(s)
    if not m:
        return None
    v = float(m.group(1))
    return (v > threshold) if strict else (v >= threshold)


def format_condition_emoji(value: Optional[bool]) -> str:
    """三態 bool → emoji — 取代 tab_stock._tk2 / tab_stock_grp._tk。

    True → ✅、False → ❌、None / 其他 → ⚪。
    """
    if value is True:
        return '✅'
    if value is False:
        return '❌'
    return '⚪'


def safe_get(value: Any) -> Any:
    """過濾 None / NaN，其餘原樣返回 — 取代 tab_macro._v。

    用於從 pandas Series / dict 取欄位後的防呆，
    避免 NaN 進入下游條件判斷造成 silent bug。
    """
    try:
        if value is None or pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    return value


def safe_ma(df: pd.DataFrame, n: int) -> float:
    """取最新 MA{n} — 取代 tab_stock._safe_ma。

    優先讀 df['MA{n}'] 既有欄位；缺欄位但資料足 → 即時 rolling；
    資料不足 → 退回 close 平均（最保守 fallback）。

    Args:
        df: 至少有 'close' 欄位
        n: 均線天數（5/20/60/120/240）

    Returns:
        float — 最後一根的 MA 值
    """
    col = f'MA{n}'
    if col in df.columns:
        return float(df[col].iloc[-1])
    if len(df) >= n:
        return float(df['close'].tail(n).mean())
    return float(df['close'].mean())
