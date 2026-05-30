"""
tw_backtest.py — 台股版倒掛翻正後 ^TWII 表現歷史回測（v1.0）

設計目標
========
複製 fund-dashboard `services.macro_service.backtest_turning_points` 的概念，
但對「台股加權指數 ^TWII」做後續 6/12/18M 表現回測——
讓使用者看到「美國 10Y-2Y 倒掛→翻正」這個全球領先訊號對台股的歷史含義。

資料源
======
- T10Y2Y：FRED API（全球無得替代，沿用美債曲線）
- ^TWII：透過 macro_core.fetch_yf_close 抓 Yahoo Chart REST API（NAS proxy）

對外 API
========
- `backtest_twii_turning_points(fred_api_key, ...) -> dict`
- `find_uninversion_events(s, ...) -> list`（重用）
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


# ════════════════════════════════════════════════════════════════
# 事件識別 — 與 fund-dashboard 同邏輯
# ════════════════════════════════════════════════════════════════
def find_uninversion_events(s: pd.Series,
                            min_inversion_depth: float = -0.10,
                            stable_days: int = 5,
                            cooldown_days: int = 365) -> list:
    """掃描 T10Y2Y 序列，識別所有「真倒掛 → 穩定翻正」事件。

    事件定義（同時滿足）：
      1. 區段內 min(T10Y2Y) ≤ min_inversion_depth（去除貼地噪音）
      2. 翻正日 T10Y2Y ≥ 0 且後續 stable_days 日皆 ≥ 0（去抖）
      3. 距上一事件 ≥ cooldown_days（避免同週期重複觸發）

    Returns
    -------
    [{"date": Timestamp, "t10y2y_min_pre": float}, ...]
    """
    if s is None or s.empty or len(s) < stable_days + 2:
        return []
    s = s.sort_index().dropna()
    vals  = s.values
    dates = s.index

    events: list = []
    in_inversion = False
    seg_min      = 0.0
    last_event_t = None

    for i in range(len(vals)):
        v = vals[i]
        if v < 0:
            if not in_inversion:
                in_inversion = True
                seg_min = v
            else:
                seg_min = min(seg_min, v)
        else:
            if in_inversion and seg_min <= min_inversion_depth:
                end = i + stable_days
                if end <= len(vals) and (vals[i:end] >= 0).all():
                    t = dates[i]
                    if last_event_t is None \
                       or (t - last_event_t).days >= cooldown_days:
                        events.append({
                            "date": t,
                            "t10y2y_min_pre": float(round(seg_min, 3)),
                        })
                        last_event_t = t
            in_inversion = False
            seg_min      = 0.0
    return events


def _forward_return(idx: pd.Series, t0: pd.Timestamp,
                    days: int) -> Optional[float]:
    """指數從 t0 起 days 天後的累計報酬（%）。窗口未到期回 None。"""
    if idx is None or idx.empty:
        return None
    try:
        idx0 = idx.index.searchsorted(t0)
        if idx0 >= len(idx):
            return None
        p0 = float(idx.iloc[idx0])
        t1 = t0 + pd.Timedelta(days=days)
        idx1 = idx.index.searchsorted(t1)
        if idx1 >= len(idx):
            return None
        p1 = float(idx.iloc[idx1])
        if p0 <= 0:
            return None
        return round((p1 / p0 - 1.0) * 100.0, 2)
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════
# 主 API — 倒掛翻正後 ^TWII 表現
# ════════════════════════════════════════════════════════════════
def backtest_twii_turning_points(
    fred_api_key: str = "",
    min_inversion_depth: float = -0.10,
    stable_days: int = 5,
    cooldown_days: int = 365,
) -> dict:
    """倒掛翻正歷史回測 — 台股版（v1.0）

    抓 25Y T10Y2Y 日頻 + ^TWII 全歷史，識別所有「倒掛→翻正」事件，
    對每事件計算 TWII 後續 6M / 12M / 18M 累計報酬，及中位數與勝率。

    Returns
    -------
    {
      "events": [
        {"date": Timestamp, "t10y2y_min_pre": float,
         "ret_6m": float|None, "ret_12m": float|None, "ret_18m": float|None,
         "complete": bool},
        ...
      ],
      "summary": {"n_events": int, "n_complete_18m": int,
                  "median_6m/12m/18m": float, "mean_6m/12m/18m": float,
                  "win_rate_6m/12m/18m": float},
      "twii_series":   pd.Series,
      "t10y2y_series": pd.Series,
      "source_ok": bool,
      "note": str,
    }
    """
    out: dict = {
        "events": [],
        "summary": {"n_events": 0, "n_complete_18m": 0,
                    "median_6m": None,  "median_12m": None, "median_18m": None,
                    "mean_6m":   None,  "mean_12m":   None, "mean_18m":   None,
                    "win_rate_6m": None, "win_rate_12m": None,
                    "win_rate_18m": None},
        "twii_series":   pd.Series(dtype=float),
        "t10y2y_series": pd.Series(dtype=float),
        "source_ok": False,
        "note": "",
    }

    if not fred_api_key:
        out["note"] = "FRED API key 未設置"
        return out

    # ── 抓 T10Y2Y 25Y ─────────────────────────────────────────────
    try:
        from macro_core import fetch_fred as _ff_tw
        df_t = _ff_tw("T10Y2Y", fred_api_key, n=8000)
    except Exception as e:
        out["note"] = f"T10Y2Y 抓取異常：{str(e)[:80]}"
        return out
    if df_t is None or df_t.empty or len(df_t) < 1000:
        out["note"] = "T10Y2Y 資料不足（< 1000 obs）"
        return out

    s_t = (df_t.sort_values("date").set_index("date")["value"]
                 .astype(float).dropna())
    try:
        s_t.index = s_t.index.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    out["t10y2y_series"] = s_t

    # ── 抓 ^TWII 全歷史（多 range 備援）───────────────────────────
    try:
        from macro_core import fetch_yf_close as _fyf_tw
    except ImportError as e:
        out["note"] = f"macro_core.fetch_yf_close import 失敗：{e}"
        return out

    twii = None
    _twii_tried: list[str] = []
    for _rng in ("max", "30y", "20y", "10y", "5y"):
        try:
            _cand = _fyf_tw("^TWII", range_=_rng, interval="1d")
            _twii_tried.append(f"{_rng}={len(_cand) if _cand is not None else 0}")
            if _cand is not None and not _cand.empty:
                if twii is None or len(_cand) > len(twii):
                    twii = _cand
                if twii is not None and len(twii) >= 1000:
                    break
        except Exception as e:
            _twii_tried.append(f"{_rng}=ERR:{type(e).__name__}")
            continue
    if twii is None or twii.empty or len(twii) < 500:
        out["note"] = (
            f"^TWII history insufficient (< 500 trading days)"
            f" — 嘗試結果：{', '.join(_twii_tried)}"
        )
        return out
    try:
        twii.index = twii.index.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    out["twii_series"] = twii.sort_index()

    # ── 事件識別 ────────────────────────────────────────────────
    events = find_uninversion_events(
        s_t, min_inversion_depth=min_inversion_depth,
        stable_days=stable_days, cooldown_days=cooldown_days,
    )

    # ── 對每事件計算 TWII +6M/+12M/+18M 報酬 ──────────────────────
    today = pd.Timestamp.today().normalize()
    enriched: list = []
    for ev in events:
        t0 = ev["date"]
        r6  = _forward_return(out["twii_series"], t0, 182)
        r12 = _forward_return(out["twii_series"], t0, 365)
        r18 = _forward_return(out["twii_series"], t0, 547)
        complete = (today - t0).days >= 547 and r18 is not None
        enriched.append({
            "date": t0,
            "t10y2y_min_pre": ev["t10y2y_min_pre"],
            "ret_6m":  r6,
            "ret_12m": r12,
            "ret_18m": r18,
            "complete": complete,
        })
    out["events"] = enriched

    # ── Summary 統計 ──────────────────────────────────────────────
    def _stat(key: str, require_complete: bool = False):
        vals = [e[key] for e in enriched
                if e[key] is not None
                and (e["complete"] if require_complete else True)]
        if not vals:
            return None, None, None
        med = float(np.median(vals))
        avg = float(np.mean(vals))
        wr  = float(sum(1 for v in vals if v > 0) / len(vals) * 100.0)
        return round(med, 2), round(avg, 2), round(wr, 1)

    m6,  a6,  w6  = _stat("ret_6m")
    m12, a12, w12 = _stat("ret_12m")
    m18, a18, w18 = _stat("ret_18m", require_complete=True)

    out["summary"].update({
        "n_events":        len(enriched),
        "n_complete_18m":  sum(1 for e in enriched if e["complete"]),
        "median_6m":   m6,  "median_12m": m12, "median_18m": m18,
        "mean_6m":     a6,  "mean_12m":   a12, "mean_18m":   a18,
        "win_rate_6m": w6,  "win_rate_12m": w12, "win_rate_18m": w18,
    })
    out["source_ok"] = True
    out["note"] = (
        f"識別 {len(enriched)} 個事件"
        f"（去抖 stable={stable_days}d, depth≤{min_inversion_depth}）"
    )
    return out
