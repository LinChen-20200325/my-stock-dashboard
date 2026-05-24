"""ETF 歷史回測 TAB — 從 etf_dashboard.py 抽出（PR P2-B Phase 6-C）

依賴策略
========
- Top-level: streamlit
- 函式內 late import：
  * stdlib: pandas, plotly.graph_objects
  * etf_dashboard.py 內部 helper (9):
    _colored_box / _etf_ai_backtest / _render_monte_carlo / _teacher_conclusion
    / calc_cagr / calc_mdd / calc_sharpe / fetch_etf_dividends / fetch_etf_price

去重歷史
========
- PR #19+：刪 render_unified_decision 呼叫（與 etf_tab_ai.py「ETF AI 首席策略師」重疊）
  保留 _etf_ai_backtest（CAGR/Sharpe 速評，與 ETF AI 戰情報告角度不同）

呼叫端
======
- app.py 經 etf_dashboard re-export 取用
"""
from __future__ import annotations

import streamlit as st

from etf_helpers import norm_lower_better, norm_return


def render_etf_backtest(gemini_fn=None):
    # ─ Late imports（避免循環 import）─
    import pandas as pd
    import plotly.graph_objects as go
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

    with st.expander('💡 這項數據代表什麼？（CAGR · 夏普值 · 最大回撤 · 波動率）', expanded=False):
        st.markdown(
            '- **CAGR（年化報酬率）**：把整段報酬換算成「每年平均賺幾 %」，方便跨期間、跨組合比較。\n'
            '- **夏普值（Sharpe）**：每承擔 1 單位波動換到多少報酬，**越高越好**。>1 風報優秀、0.5-1 尚可、<0.5 波動大但賺不多。\n'
            '- **最大回撤（MDD）**：歷史從最高點跌到最低點的最大跌幅，反映**最痛時要忍受多少帳面虧損**。≤10% 壓力小、>20% 空頭需強心臟。\n'
            '- **年化波動率**：報酬起伏幅度（標準差年化），越低代表走勢越穩。'
        )

    # ── 五維風報雷達圖（組合 vs 基準）────────────────────────────
    # 各維度 0-100 正規化（越大越好）：norm_return / norm_lower_better 抽至 etf_helpers
    _port_scores = [
        norm_return(cum_ret, lo=-50, mid=0, hi=80),
        norm_return(cagr, lo=-5, mid=5, hi=15),
        norm_lower_better(vol, best=8, mid=20, worst=35),
        norm_return(sharpe * 50, lo=-50, mid=50, hi=150),  # sharpe -1~3 → 0-100
        norm_lower_better(mdd, best=5, mid=20, worst=35),
    ]
    # 基準分數（從 bench_val 計算）
    _bench_scores = None
    if bench_val is not None and len(bench_val) > 10:
        _bench_df  = pd.DataFrame({'Close': bench_val})
        _b_cagr    = calc_cagr(_bench_df)
        _b_sharpe  = calc_sharpe(_bench_df)
        _b_mdd     = calc_mdd(_bench_df)
        _b_vol     = round(float(bench_val.pct_change().dropna().std() * (252**0.5) * 100), 2)
        _b_cum     = round((float(bench_val.iloc[-1]) - initial) / initial * 100, 2)
        _bench_scores = [
            norm_return(_b_cum, lo=-50, mid=0, hi=80),
            norm_return(_b_cagr, lo=-5, mid=5, hi=15),
            norm_lower_better(_b_vol, best=8, mid=20, worst=35),
            norm_return(_b_sharpe * 50, lo=-50, mid=50, hi=150),
            norm_lower_better(_b_mdd, best=5, mid=20, worst=35),
        ]

    _radar_labels = ['累積報酬', 'CAGR', '低波動', '夏普值', '低回撤']
    _fig_radar = go.Figure()
    _fig_radar.add_trace(go.Scatterpolar(
        r=_port_scores + [_port_scores[0]],
        theta=_radar_labels + [_radar_labels[0]],
        fill='toself', name='📦 ETF組合',
        line=dict(color='#58a6ff', width=2),
        fillcolor='rgba(88,166,255,0.25)'))
    if _bench_scores is not None:
        _fig_radar.add_trace(go.Scatterpolar(
            r=_bench_scores + [_bench_scores[0]],
            theta=_radar_labels + [_radar_labels[0]],
            fill='toself', name=f'📊 {bench_ticker}（基準）',
            line=dict(color='#3fb950', width=1.5, dash='dash'),
            fillcolor='rgba(63,185,80,0.15)'))
    _fig_radar.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100],
                            gridcolor='#30363d', tickfont=dict(color='#8b949e', size=9)),
            angularaxis=dict(gridcolor='#30363d', tickfont=dict(color='#c9d1d9', size=11)),
            bgcolor='#0d1117'),
        paper_bgcolor='#0d1117', font=dict(color='#c9d1d9'),
        height=380, margin=dict(l=40, r=40, t=20, b=20),
        legend=dict(orientation='h', yanchor='bottom', y=-0.1))
    st.plotly_chart(_fig_radar, width='stretch')
    st.caption('💡 雷達圖：5 維風報指標正規化 0-100 分（面積越大越好）。波動率/最大回撤已反向，外圍=低波動低回撤。')

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

    # ── 個別 ETF 績效（4 圖比較）───────────────────────────────
    st.markdown('#### 📋 個別 ETF 績效（4 維比較圖）')
    _indiv_rows = []
    for t, w in weights.items():
        if t in prices.columns:
            df_i = pd.DataFrame({'Close': prices[t]})
            ret_series = prices[t].pct_change().dropna()
            _indiv_rows.append({
                'ETF': t,
                '權重': round(w * 100, 1),
                'CAGR': round(calc_cagr(df_i), 2),
                '波動率': round(float(ret_series.std() * (252**0.5) * 100), 2),
                '最大回撤': round(calc_mdd(df_i), 1),
                '夏普值': round(calc_sharpe(df_i), 2),
            })

    if _indiv_rows:
        from plotly.subplots import make_subplots
        _tickers_i = [r['ETF'] for r in _indiv_rows]
        _fig_indiv = make_subplots(
            rows=2, cols=2,
            subplot_titles=('CAGR（年化報酬）', '年化波動率', '最大回撤（MDD）', '夏普值'),
            vertical_spacing=0.18, horizontal_spacing=0.12)
        # CAGR：越高越好 → 綠色，負值紅
        _cagr_vals = [r['CAGR'] for r in _indiv_rows]
        _fig_indiv.add_trace(go.Bar(
            x=_tickers_i, y=_cagr_vals, name='CAGR',
            marker_color=['#3fb950' if v >= 6 else ('#d29922' if v >= 0 else '#f85149') for v in _cagr_vals],
            text=[f'{v:.2f}%' for v in _cagr_vals], textposition='outside'),
            row=1, col=1)
        # 波動率：越低越好 → 反向色階
        _vol_vals = [r['波動率'] for r in _indiv_rows]
        _fig_indiv.add_trace(go.Bar(
            x=_tickers_i, y=_vol_vals, name='波動率',
            marker_color=['#3fb950' if v <= 15 else ('#d29922' if v <= 25 else '#f85149') for v in _vol_vals],
            text=[f'{v:.2f}%' for v in _vol_vals], textposition='outside'),
            row=1, col=2)
        # MDD：絕對值越小越好（負值往下長）→ 反向色階
        _mdd_vals = [r['最大回撤'] for r in _indiv_rows]
        _fig_indiv.add_trace(go.Bar(
            x=_tickers_i, y=_mdd_vals, name='MDD',
            marker_color=['#3fb950' if abs(v) <= 10 else ('#d29922' if abs(v) <= 20 else '#f85149') for v in _mdd_vals],
            text=[f'{v:.1f}%' for v in _mdd_vals], textposition='outside'),
            row=2, col=1)
        # 夏普值：>= 1 優、>= 0.5 可、< 0.5 弱
        _sharpe_vals = [r['夏普值'] for r in _indiv_rows]
        _fig_indiv.add_trace(go.Bar(
            x=_tickers_i, y=_sharpe_vals, name='夏普值',
            marker_color=['#3fb950' if v >= 1 else ('#d29922' if v >= 0.5 else '#f85149') for v in _sharpe_vals],
            text=[f'{v:.2f}' for v in _sharpe_vals], textposition='outside'),
            row=2, col=2)
        _fig_indiv.update_layout(
            height=560, showlegend=False,
            paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
            font=dict(color='#c9d1d9', size=11),
            margin=dict(l=20, r=20, t=50, b=20))
        _fig_indiv.update_xaxes(gridcolor='#21262d', tickfont=dict(size=10))
        _fig_indiv.update_yaxes(gridcolor='#21262d', tickfont=dict(size=10))
        # 各 subplot 標題顏色
        for _ann in _fig_indiv.layout.annotations:
            _ann.font = dict(color='#8b949e', size=12)
        st.plotly_chart(_fig_indiv, width='stretch')
        # 權重小註腳，避免完全沒有數字脈絡
        _weights_txt = '　'.join([f'{r["ETF"]} {r["權重"]:.0f}%' for r in _indiv_rows])
        st.caption(f'⚖️ 權重：{_weights_txt}　｜　🟢 優秀 🟡 普通 🔴 待加強')

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
