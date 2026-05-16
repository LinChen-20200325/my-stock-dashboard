"""ETF 歷史回測 TAB — 從 etf_dashboard.py 抽出（PR P2-B Phase 6-C）

依賴策略
========
- Top-level: streamlit
- 函式內 late import 13 個依賴：
  * stdlib: pandas, plotly.graph_objects
  * 外部: unified_decision.render_unified_decision
  * etf_dashboard.py 內部 helper (9):
    _colored_box / _etf_ai_backtest / _render_monte_carlo / _teacher_conclusion
    / calc_cagr / calc_mdd / calc_sharpe / fetch_etf_dividends / fetch_etf_price

呼叫端
======
- app.py 經 etf_dashboard re-export 取用
"""
from __future__ import annotations

import streamlit as st


def render_etf_backtest(gemini_fn=None):
    # ─ Late imports（避免循環 import）─
    import pandas as pd
    import plotly.graph_objects as go
    from unified_decision import render_unified_decision
    from etf_dashboard import (
        _colored_box, _etf_ai_backtest, _render_monte_carlo, _teacher_conclusion,
        calc_cagr, calc_mdd, calc_sharpe,
        fetch_etf_dividends, fetch_etf_price,
    )

    mkt_info = st.session_state.get('mkt_info', {})
    regime   = mkt_info.get('regime', 'neutral')

    st.markdown('#### 📋 回測設定（沿用上方「輸入持股組合」）')
    _port_rows = st.session_state.get('etf_portfolio_rows')
    if not _port_rows:
        st.info('💡 請先到上方「📋 輸入持股組合」區塊輸入持股並點「計算組合」，回測會自動沿用同一份組合。')
        return

    col_w, col_p, col_i = st.columns(3)
    _weight_mode = col_w.radio(
        '回測權重來源',
        ['希望比例%（規劃驗證）', '現值比例%（實況回放）'],
        index=0, key='etf_bt_weight_mode', horizontal=False,
        help='希望比例：模擬「按你規劃配置」過去表現；現值比例：模擬「目前實際配置」過去表現')
    period  = col_p.selectbox('回測期間', ['3y', '5y', '10y', '1y'],
                               index=1, key='etf_bt_period')
    initial = col_i.number_input('初始資金（元）', value=100000,
                                  step=10000, key='etf_bt_init')
    if st.button('🚀 開始回測', key='etf_bt_btn', use_container_width=True):
        st.session_state['etf_bt_active'] = True

    if not st.session_state.get('etf_bt_active'):
        st.info('💡 選好權重來源、期間後點擊「開始回測」')
        return

    # 從持股組合萃取回測 rows（ticker + 權重）
    _pct_key = 'target_pct' if _weight_mode.startswith('希望') else 'actual_pct'
    rows = []
    for _r in _port_rows:
        _w = float(_r.get(_pct_key) or 0)
        if _w > 0 and _r.get('ticker'):
            rows.append({'ticker': _r['ticker'].upper(),
                          'weight': _w / 100})
    if not rows:
        st.error('❌ 持股組合內無有效權重，請回上方檢查')
        return
    st.caption(f'📊 回測組合：{len(rows)} 檔｜權重來源：{_weight_mode}')

    # 正規化權重
    w_sum = sum(r['weight'] for r in rows)
    if abs(w_sum - 1.0) > 0.05:
        st.warning(f'⚠️ 權重合計 {w_sum*100:.0f}%，已自動正規化')
        for r in rows:
            r['weight'] /= w_sum

    # 載入資料
    with st.spinner('載入回測資料中（請稍候）...'):
        price_dict = {}
        for r in rows:
            df_t = fetch_etf_price(r['ticker'], period=period)
            if not df_t.empty:
                price_dict[r['ticker']] = df_t['Close']

    if not price_dict:
        st.error('❌ 無法取得任何ETF資料')
        return

    # 對齊資料
    prices = pd.DataFrame(price_dict).ffill().dropna()
    if len(prices) < 20:
        st.error('❌ 有效資料不足，請確認代號或縮短回測期間')
        return

    # ── 配息稅費磨損（台灣二代健保 × 0.95）─────────────────────
    # 所有含「.TW」的 ETF 配息乘以 0.95 扣除二代健保補充費
    apply_tax = any(t.endswith('.TW') for t in [r['ticker'] for r in rows])
    TAX_FACTOR = 0.95  # 二代健保補充費磨損（約 2.11%，取保守 5%）

    # 加權組合資產價值（含稅費磨損）
    norm     = prices / prices.iloc[0]
    weights  = {r['ticker']: r['weight'] for r in rows if r['ticker'] in norm.columns}

    # 計算各ETF配息貢獻並套用稅費磨損
    div_adjustment = {}
    for r in rows:
        t = r['ticker']
        if t not in norm.columns:
            continue
        if apply_tax and t.endswith('.TW'):
            try:
                divs_t = fetch_etf_dividends(t)
                if not divs_t.empty:
                    annual_div = float(divs_t.resample('Y').sum().mean())
                    avg_price  = float(prices[t].mean())
                    div_yield  = annual_div / avg_price if avg_price > 0 else 0
                    # 稅後磨損 = 配息 × (1 - TAX_FACTOR) 每年從報酬扣除
                    div_adjustment[t] = div_yield * (1 - TAX_FACTOR)
                else:
                    div_adjustment[t] = 0.0
            except Exception:
                div_adjustment[t] = 0.0
        else:
            div_adjustment[t] = 0.0

    port_val = sum(norm[t] * w for t, w in weights.items()) * initial

    # 套用稅費磨損（每日複利扣除）
    if apply_tax:
        n_years = len(prices) / 252
        for t, w in weights.items():
            loss_factor = (1 - div_adjustment.get(t, 0)) ** n_years
            port_val = port_val - (norm[t] * w * initial * (1 - loss_factor))

    total_tax_drag = sum(div_adjustment.get(t, 0) * w for t, w in weights.items()) * 100

    # 基準
    bench_ticker = '0050.TW' if any(t.endswith('.TW') for t in weights) else '^GSPC'
    with st.spinner(f'載入基準 {bench_ticker}...'):
        bench_df = fetch_etf_price(bench_ticker, period=period)
    bench_val = None
    if not bench_df.empty:
        bc = bench_df['Close'].reindex(prices.index).ffill().dropna()
        bench_val = bc / bc.iloc[0] * initial

    # ── 資金成長曲線 ──────────────────────────────────────────
    st.markdown('#### 📈 資金成長曲線')
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=port_val.index, y=port_val.values,
                              name='📦 ETF組合',
                              line=dict(color='#58a6ff', width=2.5)))
    if bench_val is not None:
        fig.add_trace(go.Scatter(x=bench_val.index, y=bench_val.values,
                                  name=f'📊 {bench_ticker}（基準）',
                                  line=dict(color='#3fb950', width=1.5, dash='dash')))
    fig.update_layout(
        template='plotly_dark', height=380,
        yaxis_title='資產價值（元）',
        margin=dict(l=0, r=0, t=20, b=0),
        paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
        legend=dict(orientation='h', yanchor='bottom', y=1.01),
    )
    st.plotly_chart(fig, width='stretch')

    # ── 年化績效指標 ──────────────────────────────────────────
    st.markdown('#### 🏆 年化績效指標')
    port_df    = pd.DataFrame({'Close': port_val})
    cagr       = calc_cagr(port_df)
    sharpe     = calc_sharpe(port_df)
    mdd        = calc_mdd(port_df)
    vol        = round(float(port_val.pct_change().dropna().std() * (252**0.5) * 100), 2)
    final_val  = float(port_val.iloc[-1])
    cum_ret    = round((final_val - initial) / initial * 100, 2)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric('累積報酬',    f'{cum_ret:.1f}%')
    c2.metric('CAGR（年化）', f'{cagr:.2f}%')
    c3.metric('年化波動率',   f'{vol:.2f}%')
    c4.metric('夏普值',       f'{sharpe:.2f}')
    c5.metric('最大回撤',     f'{mdd:.1f}%')

    # ── 績效評級總結卡（老師標準）──────────────────────────────
    _grade_pts = 0
    if cagr >= 10:
        _grade_pts += 3
    elif cagr >= 6:
        _grade_pts += 2
    elif cagr >= 3:
        _grade_pts += 1
    if sharpe >= 1.0:
        _grade_pts += 3
    elif sharpe >= 0.5:
        _grade_pts += 1
    if abs(mdd) <= 10:
        _grade_pts += 3
    elif abs(mdd) <= 20:
        _grade_pts += 1
    _grade_label = ('⭐⭐⭐ 優秀' if _grade_pts >= 7 else
                    '⭐⭐ 良好' if _grade_pts >= 4 else '⭐ 普通')
    _grade_color = ('#3fb950' if _grade_pts >= 7 else
                    '#d29922' if _grade_pts >= 4 else '#f85149')
    _sharpe_note = ('夏普值≥1.0，承擔風險有充分補償' if sharpe >= 1.0 else
                    '夏普值<0.5，波動大但報酬低，需檢視配置' if sharpe < 0.5 else
                    '夏普值介於0.5-1.0，風險報酬比尚可')
    _mdd_note = ('最大回撤≤10%，心理壓力小，適合長期持有' if abs(mdd) <= 10 else
                 '最大回撤>20%，空頭時需有足夠心理準備' if abs(mdd) > 20 else
                 '最大回撤10-20%，合理範圍，按計畫執行')
    st.markdown(
        f'<div style="background:#0d1117;border:2px solid {_grade_color};border-radius:10px;'
        f'padding:12px 16px;margin:10px 0;">'
        f'<div style="font-size:16px;font-weight:900;color:{_grade_color};">📊 績效評級：{_grade_label}</div>'
        f'<div style="font-size:12px;color:#c9d1d9;margin-top:6px;">'
        f'CAGR {cagr:.2f}% | 夏普值 {sharpe:.2f} | 最大回撤 {mdd:.1f}%</div>'
        f'<div style="font-size:11px;color:#8b949e;margin-top:4px;">💡 {_sharpe_note} ／ {_mdd_note}</div>'
        f'</div>', unsafe_allow_html=True)
    # 老師動態結論
    if cagr >= 10 and sharpe >= 1.0:
        _bt_concl = f'CAGR {cagr:.1f}% + 夏普值 {sharpe:.2f}，風報比頂尖，長期持有無疑'
        _bt_act   = '全倉持有，定期再平衡'
    elif cagr >= 6 and abs(mdd) <= 20:
        _bt_concl = f'CAGR {cagr:.1f}%，最大回撤 {mdd:.1f}%，穩健成長型組合'
        _bt_act   = '維持配置，夏普值 < 1.0 可優化標的'
    elif cagr < 3:
        _bt_concl = f'CAGR {cagr:.1f}%，報酬不如定存，需重新審視配置'
        _bt_act   = '更換低費率或高 CAGR 的 ETF，如 0050 / SPY'
    else:
        _bt_concl = f'CAGR {cagr:.1f}%，最大回撤 {mdd:.1f}%，表現普通'
        _bt_act   = '評估是否增加股票型 ETF 比例以提升 CAGR'
    _teacher_conclusion('春哥', f'回測評級 {_grade_label}', _bt_concl, _bt_act)

    # ── 個別 ETF 績效 ─────────────────────────────────────────
    st.markdown('#### 📋 個別 ETF 績效')
    indiv = []
    for t, w in weights.items():
        if t in prices.columns:
            df_i = pd.DataFrame({'Close': prices[t]})
            ret_series = prices[t].pct_change().dropna()
            indiv.append({
                'ETF': t, '權重': f'{w*100:.0f}%',
                'CAGR': f'{calc_cagr(df_i):.2f}%',
                '波動率': f'{round(float(ret_series.std()*(252**0.5)*100),2):.2f}%',
                '最大回撤': f'{calc_mdd(df_i):.1f}%',
                '夏普值': f'{calc_sharpe(df_i):.2f}',
            })
    st.dataframe(pd.DataFrame(indiv), use_container_width=True, hide_index=True)

    # ── 稅費磨損提示 ──────────────────────────────────────────
    if apply_tax and total_tax_drag > 0:
        _colored_box(
            f'💸 配息稅費磨損（台灣二代健保 ×0.95）：'
            f'加權年均磨損約 <b>{total_tax_drag:.3f}%</b>，'
            f'長期持有需列入報酬估算', 'yellow')

    # ── 蒙地卡羅模擬（延遲執行，避免頁面切換時自動佔用 CPU）──────
    st.markdown('#### 🎲 蒙地卡羅模擬（10,000 路徑，1 年）')
    _mc_key = f'etf_mc_done_{hash(str(weights))}'
    if st.session_state.get(_mc_key):
        _render_monte_carlo(port_val, initial, vol)
    else:
        st.info('點擊下方按鈕執行蒙地卡羅模擬（10,000 路徑）。此運算約需 3-5 秒，手動觸發以避免頁面切換卡頓。')
        if st.button('🎲 執行蒙地卡羅模擬', key='etf_mc_btn'):
            st.session_state[_mc_key] = True
            _render_monte_carlo(port_val, initial, vol)

    # 存入 session_state
    st.session_state['etf_backtest_data'] = {
        'weights': weights, 'period': period, 'initial': initial,
        'cagr': cagr, 'sharpe': sharpe, 'mdd': mdd, 'vol': vol,
        'cum_ret': cum_ret, 'regime': regime,
    }

    if gemini_fn:
        _etf_ai_backtest(gemini_fn, cagr, sharpe, mdd, vol, weights, regime)

    # ── 統一投資決策分析模組 ──────────────────────────────────
    render_unified_decision(gemini_fn, {
        'type': 'portfolio',
        'id':   'etf_backtest',
        'data': {
            '組合權重':   {t: f'{w*100:.0f}%' for t, w in weights.items()},
            'CAGR':       f'{cagr:.2f}%',
            'Sharpe比率': round(sharpe, 2),
            '最大回撤MDD': f'{mdd:.1f}%',
            '年化波動率':  f'{vol:.2f}%',
            '大盤狀態':    regime,
        },
    })
