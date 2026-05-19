"""
ETF AI 儀表板 — Public API Shim
Tab ⑥ 單一 ETF 深度診斷 | Tab ⑦ 組合配置 | Tab ⑧ 回測 | Tab ⑨ AI 綜合評斷

P2-B Phase 7C：fetch / calc / render 三層分檔重構（2026-05-16）
  - etf_fetch.py    純 I/O：價格 / 配息 / 基本資訊 / 費用率 / NAV / 類股漲跌 / 新聞
  - etf_calc.py     純計算：殖利率 / 總報酬 / 折溢價 / 風險指標 / 同儕排名 / 戰情室列
  - etf_render.py   Streamlit/Plotly UI：橫幅 / 走勢圖 / BIAS / 蒙地卡羅 / 類股熱力圖
  - etf_tab_*.py    Phase 6 已抽出的四大 tab 渲染入口

此檔僅作 re-export，保持下游 6 個 importer（app / etf_quality / etf_tab_* / grape_ladder）
既有 `from etf_dashboard import ...` 不變。新程式碼建議直接 import 對應子模組。
"""

# ── fetch 層 ─────────────────────────────────────────────────
from etf_fetch import (  # noqa: F401
    _fetch_news_for, _TW_ETF_LAUNCH_PRICE, _get_etf_launch_price,
    fetch_etf_price, fetch_etf_dividends, fetch_etf_info,
    fetch_sitca_expense_ratio, fetch_moneydj_expense_ratio,
    get_etf_expense_ratio_safe,
    fetch_etf_holdings,
    _NAV_MIN, _NAV_MAX, _safe_float,
    fetch_etf_nav_history, _fetch_sector_returns,
)

# ── calc 層 ──────────────────────────────────────────────────
from etf_calc import (  # noqa: F401
    _compute_etf_warroom_row,
    calc_current_yield, calc_total_return_1y, calc_avg_yield,
    check_vcp_signal, calc_premium_discount,
    calc_tracking_error, calc_mdd, calc_cagr, calc_sharpe,
    auto_detect_benchmark, compute_etf_peer_ranking,
    calc_holdings_overlap_pct, calc_jaccard_overlap, build_holdings_overlap_matrix,
)

# ── render 層 ────────────────────────────────────────────────
from etf_render import (  # noqa: F401
    MACRO_ALLOC, MACRO_DESC,
    macro_allocation_banner, _colored_box, _teacher_conclusion,
    _plot_etf_chart, _plot_correlation, _plot_holdings_overlap, _render_bias,
    _ETF_SECTOR_MAP, _check_sector_exposure,
    _render_monte_carlo, _etf_ai_backtest,
    _US_SECTORS, _TW_SECTORS, _PERIOD_MAP,
    _build_treemap_data, render_sector_heatmap,
)

# ── 四大 tab 入口（Phase 6 已抽出）──────────────────────────
from etf_tab_single import render_etf_single  # noqa: F401
from etf_tab_portfolio import render_etf_portfolio  # noqa: F401
from etf_tab_backtest import render_etf_backtest  # noqa: F401
from etf_tab_ai import render_etf_ai  # noqa: F401
