"""葡萄串領息法（Grape Ladder）— 高股息 ETF 月配組合最佳化

挑選不同除息月份的高股息 ETF 組成投組，讓每個月都有息可領。

兩個入口：
- recommend_income_ladder(): 從 etf_categories['高股息'] 10 檔自動挑最少 ETF cover 最多月
- evaluate_income_ladder(): 評估使用者輸入組合的月份覆蓋率與現金流

資料源：yfinance via etf_dashboard.fetch_etf_dividends（既有 cache）
"""
from __future__ import annotations
import datetime as _dt
from itertools import combinations
import pandas as pd
import streamlit as st

from etf_categories import ETF_PEER_GROUPS
from etf_dashboard import fetch_etf_dividends

# ── Constants ─────────────────────────────────────────────────
LOOKBACK_DAYS = 400         # 取近 ~13 月配息，給月配 ETF 偶缺一月緩衝
MAX_COMBO_SIZE = 5          # 暴力搜尋上限
MIN_PAYMENTS_FOR_VALID = 2  # 至少 2 次配息才算「有資料」
TARGET_MONTHS_FULL = 12

# 月配 ETF 清單（slider 排除選項用）
_MONTHLY_ETFS = {'00929.TW', '00940.TW', '00939.TW'}


# ══════════════════════════════════════════════════════════════
# Pure Logic（無 Streamlit 副作用，可單測）
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=86400, show_spinner=False)
def get_pay_months(ticker: str, lookback_days: int = LOOKBACK_DAYS) -> set[int]:
    """取得 ticker 近 lookback_days 內實際除息月份集合（1-12）。

    Returns
    -------
    set[int]  例：{1, 4, 7, 10}；資料不足或抓取失敗回 set()。
    """
    _divs = fetch_etf_dividends(ticker)
    if _divs is None or _divs.empty:
        return set()
    _cutoff = pd.Timestamp(_dt.date.today() - _dt.timedelta(days=lookback_days))
    _recent = _divs[_divs.index >= _cutoff]
    if len(_recent) < MIN_PAYMENTS_FOR_VALID:
        return set()
    return set(_recent.index.month.tolist())


@st.cache_data(ttl=86400, show_spinner=False)
def get_avg_monthly_cash(ticker: str, shares: int = 1000) -> dict[int, float]:
    """{月份: 該月平均每股配息 × shares}。

    Returns
    -------
    dict[int, float]  缺月份不出現在 key 中。
    """
    _divs = fetch_etf_dividends(ticker)
    if _divs is None or _divs.empty:
        return {}
    _cutoff = pd.Timestamp(_dt.date.today() - _dt.timedelta(days=LOOKBACK_DAYS))
    _recent = _divs[_divs.index >= _cutoff]
    if _recent.empty:
        return {}
    _by_month = _recent.groupby(_recent.index.month).mean()
    return {int(_m): round(float(_v) * shares, 2) for _m, _v in _by_month.items()}


def _score_combo(combo: tuple, month_map: dict[str, set[int]]) -> tuple[int, int]:
    """(覆蓋月數, -成員數) — tuple comparison 先比覆蓋、再比成員少。"""
    _covered = set().union(*(month_map[t] for t in combo))
    return (len(_covered), -len(combo))


def recommend_income_ladder(
    candidates: list[str] | None = None,
    target_months: int = TARGET_MONTHS_FULL,
    max_etfs: int = 4,
    min_etfs: int = 1,
    exclude_monthly: bool = False,
    min_stars: int = 1,
) -> dict:
    """暴力 itertools.combinations 搜尋最佳組合。

    Parameters
    ----------
    min_stars : int
        最低品質星等過濾門檻（1-5）。1 = 不過濾，3+ 用 etf_quality 預先剔除。

    Returns
    -------
    dict
      best_combo, covered_months, missing_months, coverage_pct,
      month_map, all_candidates_evaluated, skipped_tickers, low_quality, alternatives
    """
    _cands = list(candidates) if candidates else list(ETF_PEER_GROUPS.get('高股息', []))
    if exclude_monthly:
        _cands = [t for t in _cands if t not in _MONTHLY_ETFS]
    # 品質星等過濾（min_stars >= 2 才啟動，避免 1=不過濾時白抓）
    _low_quality: list[str] = []
    if min_stars >= 2:
        try:
            from etf_quality import compute_etf_quality
            _filtered: list[str] = []
            for _t in _cands:
                _q = compute_etf_quality(_t)
                _s = _q.get('stars') if _q else None
                if _s is None or _s >= min_stars:
                    # 未評等者保留（避免資料缺漏誤殺）
                    _filtered.append(_t)
                else:
                    _low_quality.append(_t)
            _cands = _filtered
        except Exception as _e_q:
            print(f'[grape_ladder/min_stars] ❌ {type(_e_q).__name__}: {_e_q}')
    # 抓每檔配息月份；空 set 視為無資料
    _month_map: dict[str, set[int]] = {}
    _skipped: list[str] = []
    for _t in _cands:
        _m = get_pay_months(_t)
        if _m:
            _month_map[_t] = _m
        else:
            _skipped.append(_t)
    _valid = list(_month_map.keys())
    if len(_valid) < min_etfs:
        return {
            'best_combo': [], 'covered_months': set(), 'missing_months': set(range(1, 13)),
            'coverage_pct': 0.0, 'month_map': {},
            'all_candidates_evaluated': 0, 'skipped_tickers': _skipped,
            'low_quality': _low_quality, 'alternatives': [],
            '_err': f'有效 ETF 僅 {len(_valid)} 檔，少於 min_etfs={min_etfs}',
        }
    _max_k = min(max_etfs, len(_valid), MAX_COMBO_SIZE)
    _best_score: tuple[int, int] | None = None
    _best_combo: tuple = ()
    _evaluated = 0
    _all_top: list[tuple] = []  # 同分組合
    for _k in range(min_etfs, _max_k + 1):
        for _combo in combinations(_valid, _k):
            _evaluated += 1
            _sc = _score_combo(_combo, _month_map)
            if _best_score is None or _sc > _best_score:
                _best_score = _sc
                _best_combo = _combo
                _all_top = [_combo]
            elif _sc == _best_score:
                _all_top.append(_combo)
    _best_covered = set().union(*(_month_map[t] for t in _best_combo))
    _missing = set(range(1, target_months + 1)) - _best_covered
    # 每月 → 哪幾檔配
    _by_month: dict[int, list[str]] = {}
    for _t in _best_combo:
        for _m in _month_map[_t]:
            _by_month.setdefault(_m, []).append(_t)
    # alternatives：除 best 外取前 3 個
    _alts = [list(_c) for _c in _all_top if _c != _best_combo][:3]
    return {
        'best_combo': list(_best_combo),
        'covered_months': _best_covered,
        'missing_months': _missing,
        'coverage_pct': round(len(_best_covered) / target_months * 100, 1),
        'month_map': _by_month,
        'all_candidates_evaluated': _evaluated,
        'skipped_tickers': _skipped,
        'low_quality': _low_quality,
        'alternatives': _alts,
    }


def evaluate_income_ladder(
    tickers: list[str],
    shares_map: dict[str, int] | None = None,
) -> dict:
    """評估使用者輸入組合的月份覆蓋率 + 每月現金流。

    Returns
    -------
    dict
      tickers, covered_months, missing_months, month_etfs,
      monthly_cashflow (1..12 完整 key), annual_cashflow, invalid_tickers
    """
    if not tickers:
        return {'_err': '請至少輸入 1 檔 ETF', 'tickers': [], 'invalid_tickers': []}
    # 去重保序
    _seen: set[str] = set()
    _clean: list[str] = []
    for _t in tickers:
        _t = (_t or '').strip().upper()
        if _t and _t not in _seen:
            _seen.add(_t)
            _clean.append(_t)
    # 台股代碼驗證
    _valid: list[str] = []
    _invalid: list[str] = []
    for _t in _clean:
        if _t.endswith('.TW') or _t.endswith('.TWO'):
            _valid.append(_t)
        else:
            _invalid.append(_t)
    _shares = shares_map or {}
    _month_etfs: dict[int, list[str]] = {}
    _monthly_cf: dict[int, float] = {m: 0.0 for m in range(1, 13)}
    for _t in _valid:
        _m_set = get_pay_months(_t)
        for _m in _m_set:
            _month_etfs.setdefault(_m, []).append(_t)
        _cash = get_avg_monthly_cash(_t, shares=_shares.get(_t, 1000))
        for _m, _v in _cash.items():
            _monthly_cf[_m] = round(_monthly_cf.get(_m, 0.0) + _v, 2)
    _covered = {m for m, lst in _month_etfs.items() if lst}
    _missing = set(range(1, 13)) - _covered
    return {
        'tickers': _valid,
        'covered_months': _covered,
        'missing_months': _missing,
        'month_etfs': _month_etfs,
        'monthly_cashflow': _monthly_cf,
        'annual_cashflow': round(sum(_monthly_cf.values()), 2),
        'invalid_tickers': _invalid,
    }


# ══════════════════════════════════════════════════════════════
# UI Helpers
# ══════════════════════════════════════════════════════════════

def _render_month_grid(month_etfs: dict[int, list[str]], missing: set[int]) -> None:
    """12 月份 3×4 grid；該月有配 → 綠底 + ETF chips；缺月 → 紅底 ❌。"""
    _MONTH_NAMES = ['一月', '二月', '三月', '四月', '五月', '六月',
                    '七月', '八月', '九月', '十月', '十一月', '十二月']
    for _row in range(3):
        _cols = st.columns(4)
        for _i in range(4):
            _m = _row * 4 + _i + 1
            with _cols[_i]:
                _etfs = month_etfs.get(_m, [])
                _has = bool(_etfs)
                _bg = '#0d2818' if _has else '#2d0e0e'
                _border = '#3fb950' if _has else '#f85149'
                _icon = '✅' if _has else '❌'
                _content = ('<br>'.join(
                    f"<span style='background:#1f6feb22;color:#79c0ff;"
                    f"padding:2px 6px;border-radius:8px;font-size:10px;"
                    f"margin:2px 0;display:inline-block'>{_e}</span>"
                    for _e in _etfs)
                    if _has else '<span style="color:#8b949e">無 ETF</span>')
                st.markdown(
                    f"<div style='background:{_bg};border:1px solid {_border};"
                    f"border-radius:6px;padding:8px;min-height:80px'>"
                    f"<div style='color:#e6edf3;font-weight:700;font-size:12px'>"
                    f"{_icon} {_MONTH_NAMES[_m - 1]}</div>"
                    f"<div style='margin-top:4px;line-height:1.6'>{_content}</div>"
                    f"</div>", unsafe_allow_html=True)


def _render_propose_subtab() -> None:
    """💡 系統提議 sub-tab"""
    st.markdown('##### 💡 從高股息 10 檔自動挑選最佳組合')
    _c1, _c2, _c3 = st.columns([1, 1, 1])
    with _c1:
        _max_etfs = st.slider('最多 ETF 數', 1, 5, value=4, key='_grape_max_etfs')
    with _c2:
        _min_stars = st.slider('最低品質星等 ⭐', 1, 5, value=3,
                               key='_grape_min_stars',
                               help='1 = 不過濾；3+ 用 etf_quality 4 因子預先剔除低品質 ETF')
    with _c3:
        _excl = st.checkbox('排除月配高息（00929/00940/00939）',
                            value=False, key='_grape_excl_monthly')
    if not st.button('🍇 生成提議', key='_grape_btn_propose', type='primary'):
        st.caption('點上方按鈕產生建議組合。提議引擎會嘗試所有 1~N 檔組合（最多 C(10,5)=252 種）。')
        return
    with st.spinner('搜尋最佳組合中…（< 10 秒）'):
        _res = recommend_income_ladder(
            max_etfs=_max_etfs, min_etfs=1,
            exclude_monthly=_excl, min_stars=_min_stars)
    if _res.get('_err'):
        st.error(f'❌ {_res["_err"]}')
        return
    _combo = _res['best_combo']
    _cover_pct = _res['coverage_pct']
    _missing = sorted(_res['missing_months'])
    if _cover_pct >= 100:
        st.success(f'✅ 用 {len(_combo)} 檔 cover 全部 12 個月！組合：{", ".join(_combo)}')
    else:
        st.warning(f'⚠️ 用 {len(_combo)} 檔 cover {len(_res["covered_months"])}/12 月 '
                   f'({_cover_pct}%)，缺月份：{_missing}')
    _m1, _m2, _m3, _m4 = st.columns(4)
    _m1.metric('覆蓋月數', f'{len(_res["covered_months"])}/12')
    _m2.metric('缺口', len(_missing))
    _m3.metric('ETF 數', len(_combo))
    _m4.metric('嘗試組合', _res['all_candidates_evaluated'])
    st.markdown('##### 📅 12 月份覆蓋圖')
    _render_month_grid(_res['month_map'], _res['missing_months'])
    if _res.get('skipped_tickers'):
        st.caption(f'⚪ 略過（配息資料不足）：{", ".join(_res["skipped_tickers"])}')
    if _res.get('low_quality'):
        st.caption(f'⭐ 品質星等過濾（< {_min_stars}★）剔除：{", ".join(_res["low_quality"])}')
    if _res.get('alternatives'):
        st.markdown('##### 🔄 同分次優組合')
        _alt_rows = [{'組合': ', '.join(_a), 'ETF 數': len(_a)}
                     for _a in _res['alternatives']]
        st.dataframe(pd.DataFrame(_alt_rows),
                     use_container_width=True, hide_index=True)


def render_grape_ladder(gemini_fn=None) -> None:
    """Streamlit UI 對外入口 — 主視圖：💡 系統提議（從高股息 10 檔自動挑選最佳組合）。

    註：評估你現有持股的月配息分布功能已下放到 etf_tab_portfolio 的「💰 配息日曆 × 年度現金流預估」（PR #6 去重）。
    """
    st.markdown('### 📅 葡萄串領息法')
    st.caption('「不同月配 ETF」組合形成「葡萄串」：讓每個月都有息可領。'
               '本區從高股息 10 檔自動挑選最佳組合；'
               '若想看你既有持股的月配息分布，請見上方「💰 配息日曆 × 年度現金流預估」。')
    _render_propose_subtab()
