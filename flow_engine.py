"""flow_engine.py — 全球資金流向 / 跨資產流動性：純計算層（無 streamlit、無網路 IO）。

設計理念：真實基金資金流量（EPFR/ICI 美元流入流出）為付費資料、免費源不可得，
故以各「區域 / 資產類別代表性 ETF」的相對強弱當資金流向「代理指標」：
  - 世界區域股市：近 N 日報酬率排名（高=資金流入代理、低=流出代理）。
  - 跨資產風險情緒：採 252 日滾動 Z-score + clip(-3,3) 合成 risk-on/off 分數。

本模組只做純計算，方便單元測試；網路抓取在 daily_checklist.fetch_flow_snapshot。
"""
from __future__ import annotations

import math

# ── 世界區域股市（資金流向代理：相對報酬排名）────────────────────────────
REGIONAL_ETFS = {
    "美國 SPY": "SPY",
    "歐洲 VGK": "VGK",
    "日本 EWJ": "EWJ",
    "中國 FXI": "FXI",
    "新興市場 EEM": "EEM",
    "台灣 EWT": "EWT",
}

# ── 跨資產原始序列（風險情緒分數用；MOVE 可能抓不到→自動略過）──────────────
CROSS_ASSET_ETFS = {
    "股票 SPY": "SPY",
    "長天期美債 TLT": "TLT",
    "高收益債 HYG": "HYG",
    "投資級債 LQD": "LQD",
    "黃金 GLD": "GLD",
    "美元 UUP": "UUP",
    "美元日圓 USDJPY": "JPY=X",
    "VIX 波動率": "^VIX",
    "美債波動 MOVE": "^MOVE",
}


def all_symbols() -> dict:
    """區域 + 跨資產合併後的 {顯示名: yfinance 代號}（含重複代號如 SPY，抓取端會去重）。"""
    m = {}
    m.update(REGIONAL_ETFS)
    m.update(CROSS_ASSET_ETFS)
    return m


def to_close_list(df) -> list:
    """從 fetch_single 回傳的 DataFrame 取收盤序列 list[float]；無效回 []。"""
    if df is None:
        return []
    try:
        if not hasattr(df, "columns"):
            return []
        col = "close" if "close" in df.columns else ("Close" if "Close" in df.columns else None)
        if col is None:
            return []
        out = []
        for x in df[col].tolist():
            try:
                fx = float(x)
            except (TypeError, ValueError):
                continue
            if fx == fx:  # 過濾 NaN
                out.append(fx)
        return out
    except Exception:
        return []


def pct_return(closes, days):
    """近 days 個交易日報酬率(%)。資料不足或除以零回 None。"""
    if not closes or days <= 0 or len(closes) <= days:
        return None
    prev = closes[-days - 1]
    if prev == 0:
        return None
    return round((closes[-1] / prev - 1) * 100, 2)


def zscore_latest(closes, window=252, clip=3.0):
    """最新值相對過去 window 日分布的 Z-score，clip 到 [-clip, clip]。
    資料不足（<30 點）回 None；標準差為 0 回 0.0。"""
    if not closes or len(closes) < 30:
        return None
    window_vals = closes[-window:] if len(closes) > window else closes
    n = len(window_vals)
    mean = sum(window_vals) / n
    var = sum((x - mean) ** 2 for x in window_vals) / n
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    z = (closes[-1] - mean) / std
    return round(max(-clip, min(clip, z)), 2)


def rank_regional_flow(close_map, days=5):
    """各區域近 days 報酬率排名（高→低 = 資金流入→流出代理）。
    close_map: {名稱: closes_list}。回 list[(名稱, pct)]，已過濾 None、由高到低。"""
    rows = []
    for name, closes in close_map.items():
        r = pct_return(closes, days)
        if r is not None:
            rows.append((name, r))
    rows.sort(key=lambda kv: kv[1], reverse=True)
    return rows


def _ratio_series(close_map, a, b, min_len=30):
    """對齊尾段後計算 a/b 比率序列；長度不足或分母為零略過 → 回 []。"""
    ca = close_map.get(a) or []
    cb = close_map.get(b) or []
    n = min(len(ca), len(cb))
    if n < min_len:
        return []
    ca, cb = ca[-n:], cb[-n:]
    return [x / y for x, y in zip(ca, cb) if y]


def _risk_label(score):
    if score >= 50:
        return "🟢 強烈 Risk-on（資金追逐風險）"
    if score >= 15:
        return "🟢 偏 Risk-on"
    if score > -15:
        return "🟡 中性"
    if score > -50:
        return "🔴 偏 Risk-off（避險防禦）"
    return "🔴 強烈 Risk-off（資金撤退）"


def compute_risk_score(close_map, window=252):
    """用跨資產序列合成 risk-on/off 分數。
    close_map 需含 CROSS_ASSET_ETFS 的 key（缺的自動略過）。
    各代理指標「上升」代表 risk-on(+1) 或 risk-off(-1)，取 Z-score×方向 平均後映射 -100..100。
    回 {score: int 或 None, label, components: [(名稱, z, 方向)]}。"""
    signals = []  # (顯示名, closes, 方向)

    spy_tlt = _ratio_series(close_map, "股票 SPY", "長天期美債 TLT")
    if spy_tlt:
        signals.append(("股債比 SPY/TLT", spy_tlt, +1))
    hyg_lqd = _ratio_series(close_map, "高收益債 HYG", "投資級債 LQD")
    if hyg_lqd:
        signals.append(("信用利差 HYG/LQD", hyg_lqd, +1))
    move_vix = _ratio_series(close_map, "美債波動 MOVE", "VIX 波動率")
    if move_vix:
        signals.append(("MOVE/VIX 債市壓力", move_vix, -1))
    for name, direction in (
        ("VIX 波動率", -1),
        ("美元 UUP", -1),
        ("黃金 GLD", -1),
        ("美元日圓 USDJPY", +1),  # USD/JPY 升 = 日圓貶 = carry-on = risk-on
    ):
        if close_map.get(name):
            signals.append((name, close_map[name], direction))

    components = []
    weighted = []
    for label, closes, direction in signals:
        z = zscore_latest(closes, window=window)
        if z is None:
            continue
        components.append((label, z, direction))
        weighted.append(z * direction)

    if not weighted:
        return {"score": None, "label": "資料不足", "components": []}
    avg = sum(weighted) / len(weighted)              # 約落在 [-3, 3]
    score = int(round(max(-100, min(100, avg / 3 * 100))))
    return {"score": score, "label": _risk_label(score), "components": components}
