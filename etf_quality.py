"""ETF 自製品質評等 — 4 因子加權合成 1-5 顆星

不依賴外部評等機構（晨星無公開 API），用 codebase 已有資料：
  - AUM 規模 30%：log10 scale，100 億+ 滿分
  - 費用率 25%：≤0.3% 滿分、≥1.5% 零分
  - 殖利率穩定度 25%：近 3Y 年度配息 CV，≤0.15 滿分、≥0.6 零分
  - Beta 合理性 20%：|β-1|≤0.1 滿分、|β-1|≥0.8 零分

評等動態 rescale：缺一因子時剩餘權重歸一化。
"""
from __future__ import annotations
import datetime as _dt
import math

import pandas as pd
import streamlit as st

from etf_dashboard import (
    fetch_etf_info, fetch_etf_dividends, get_etf_expense_ratio_safe,
)

# ── 權重（4 因子加總 = 1.0）─────────────────────────────────
_WEIGHTS: dict[str, float] = {
    'aum':      0.30,
    'expense':  0.25,
    'yield_cv': 0.25,
    'beta':     0.20,
}

# ── 因子閾值（滿分 / 零分）────────────────────────────────
# AUM in TWD：1e9 (10億) → 0；1e10 (100億) → 1
_AUM_LO_LOG = 9.0
_AUM_HI_LOG = 10.0
# Expense ratio：0.003 (0.3%) → 1；0.015 (1.5%) → 0
_EXP_HI = 0.003
_EXP_LO = 0.015
# Yield CV：0.15 → 1；0.6 → 0
_YCV_HI = 0.15
_YCV_LO = 0.6
# Beta deviation from 1：0.1 → 1；0.8 → 0
_BETA_HI = 0.1
_BETA_LO = 0.8


# ══════════════════════════════════════════════════════════════
# 4 個 pure 評分函式（0-1 浮點，缺資料回 None）
# ══════════════════════════════════════════════════════════════

def score_aum(aum: float | None) -> float | None:
    """AUM (元) → 0-1 分。log10 線性，10 億 → 0、100 億 → 1。"""
    if aum is None or aum <= 0:
        return None
    _log = math.log10(float(aum))
    return max(0.0, min(1.0, (_log - _AUM_LO_LOG) / (_AUM_HI_LOG - _AUM_LO_LOG)))


def score_expense(expense_ratio: float | None) -> float | None:
    """費用率（比例形式 0.003=0.3%）→ 0-1 分。越低越好。"""
    if expense_ratio is None or expense_ratio < 0:
        return None
    return max(0.0, min(1.0, (_EXP_LO - float(expense_ratio)) / (_EXP_LO - _EXP_HI)))


def _yield_cv(divs: pd.Series | None) -> float | None:
    """近 3Y 年度配息變異係數（std/mean）；樣本不足回 None。內部 helper。"""
    if divs is None or divs.empty:
        return None
    _cutoff = pd.Timestamp(_dt.date.today() - _dt.timedelta(days=3 * 365))
    _recent = divs[divs.index >= _cutoff]
    if len(_recent) < 4:
        return None
    _by_year = _recent.groupby(_recent.index.year).sum()
    if len(_by_year) < 2:
        return None
    _mean = float(_by_year.mean())
    if _mean <= 0:
        return None
    return float(_by_year.std() / _mean)


def score_yield_cv(divs: pd.Series | None) -> float | None:
    """殖利率穩定度：CV ≤ 0.15→1 / ≥ 0.6→0；資料不足回 None。"""
    _cv = _yield_cv(divs)
    if _cv is None:
        return None
    return max(0.0, min(1.0, (_YCV_LO - _cv) / (_YCV_LO - _YCV_HI)))


def score_beta(beta: float | None) -> float | None:
    """Beta 合理性：|β-1| 越小越好。"""
    if beta is None:
        return None
    _dev = abs(float(beta) - 1.0)
    return max(0.0, min(1.0, (_BETA_LO - _dev) / (_BETA_LO - _BETA_HI)))


# ══════════════════════════════════════════════════════════════
# 主入口：compute_etf_quality()
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=86400, show_spinner=False)
def compute_etf_quality(ticker: str) -> dict:
    """4 因子加權合成 ETF 品質評等。

    Returns
    -------
    dict
      成功：{stars: 1-5, score: float, factors: {...}, weakest: str, coverage: float}
      失敗：{stars: None, _err: str}
    """
    try:
        _info = fetch_etf_info(ticker) or {}
        _aum = _info.get('totalAssets')
        _beta = _info.get('beta') or _info.get('beta3Year')
        _exp = get_etf_expense_ratio_safe(ticker)
        _divs = fetch_etf_dividends(ticker)
    except Exception as _e:
        return {'stars': None, '_err': f'抓取失敗 {type(_e).__name__}'}
    # _yield_cv 只算 1 次；score_yield_cv 是純轉換不再做 groupby
    _ycv_raw = _yield_cv(_divs)
    _factors = {
        'aum':      {'val': _aum,  'score': score_aum(_aum)},
        'expense':  {'val': _exp,  'score': score_expense(_exp)},
        'yield_cv': {'val': round(_ycv_raw, 3) if _ycv_raw is not None else None,
                     'score': score_yield_cv(_divs)},
        'beta':     {'val': _beta, 'score': score_beta(_beta)},
    }
    # ── 單迴圈合一：valid_w / weighted_score / weakest 一次跑完 ──
    _valid_w = 0.0
    _weighted = 0.0
    _valid_pairs: list[tuple[str, float]] = []
    for _k, _v in _factors.items():
        _s = _v['score']
        if _s is None:
            continue
        _w = _WEIGHTS[_k]
        _valid_w += _w
        _weighted += _w * _s
        _valid_pairs.append((_k, _s))
    if _valid_w <= 0:
        return {'stars': None, '_err': '4 因子全缺資料', 'factors': _factors}
    _score = _weighted / _valid_w
    _weakest = min(_valid_pairs, key=lambda x: x[1])[0]
    # 5 顆星映射
    if _score >= 0.80:
        _stars = 5
    elif _score >= 0.65:
        _stars = 4
    elif _score >= 0.50:
        _stars = 3
    elif _score >= 0.35:
        _stars = 2
    else:
        _stars = 1
    return {
        'stars': _stars,
        'score': round(_score, 3),
        'factors': _factors,
        'weakest': _weakest,
        'coverage': round(_valid_w, 2),
    }


# ══════════════════════════════════════════════════════════════
# UI Helper
# ══════════════════════════════════════════════════════════════

_FACTOR_NAMES = {
    'aum':      'AUM 規模',
    'expense':  '費用率',
    'yield_cv': '殖利率穩定度',
    'beta':     'Beta 合理性',
}


def _fmt_factor_val(key: str, val) -> str:
    if val is None:
        return 'N/A'
    if key == 'aum':
        return f'{val / 1e8:.1f} 億'
    if key == 'expense':
        return f'{val * 100:.2f}%'
    if key == 'yield_cv':
        return f'CV {val:.2f}'
    if key == 'beta':
        return f'β {val:.2f}'
    return str(val)


def render_quality_badge(quality: dict | None) -> None:
    """渲染 ETF 品質徽章（完整版：星等 + 4 因子分條 + 最弱項提示）。"""
    if quality is None or quality.get('stars') is None:
        _msg = quality.get('_err', '未評等') if quality else '未評等'
        st.caption(f'⚪ 品質評等：{_msg}')
        return
    _stars = quality['stars']
    _score = quality['score']
    _cov = quality['coverage']
    _color = ('#3fb950' if _stars >= 4 else
              '#d29922' if _stars == 3 else '#f85149')
    _star_str = '★' * _stars + '☆' * (5 - _stars)
    st.markdown(
        f"#### ⭐ 品質評等　"
        f"<span style='color:{_color};font-weight:700;font-size:22px'>{_star_str}</span>　"
        f"<span style='color:#8b949e;font-size:13px'>"
        f"{_stars}/5 星｜綜合分 {_score:.2f}｜資料覆蓋 {_cov * 100:.0f}%</span>",
        unsafe_allow_html=True)
    _cols = st.columns(4)
    for _i, (_k, _name) in enumerate(_FACTOR_NAMES.items()):
        _f = quality['factors'][_k]
        with _cols[_i]:
            _s = _f['score']
            if _s is None:
                _icon = '⚪'
                _scol = '#8b949e'
                _bar = 0
            else:
                _icon = ('🟢' if _s >= 0.7 else
                         '🟡' if _s >= 0.4 else '🔴')
                _scol = ('#3fb950' if _s >= 0.7 else
                         '#d29922' if _s >= 0.4 else '#f85149')
                _bar = int(_s * 100)
            _val_str = _fmt_factor_val(_k, _f['val'])
            st.markdown(
                f"<div style='border:1px solid #30363d;border-radius:6px;"
                f"padding:8px;background:#0d1117'>"
                f"<div style='color:#8b949e;font-size:11px'>{_icon} {_name}</div>"
                f"<div style='color:{_scol};font-weight:700;font-size:14px;margin-top:2px'>"
                f"{_val_str}</div>"
                f"<div style='background:#30363d;height:4px;border-radius:2px;"
                f"margin-top:6px'>"
                f"<div style='background:{_scol};height:100%;width:{_bar}%;"
                f"border-radius:2px'></div>"
                f"</div></div>", unsafe_allow_html=True)
    if quality.get('weakest'):
        st.caption(
            f"💡 最弱項：**{_FACTOR_NAMES[quality['weakest']]}**"
            f"（拉升此因子可提升星等）")
