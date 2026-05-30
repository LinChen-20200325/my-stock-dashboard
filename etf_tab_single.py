"""ETF 單一深度診斷 TAB — 從 etf_dashboard.py 抽出（PR P2-B Phase 6-A）

依賴策略
========
- Top-level: streamlit（最穩定）
- 函式內 late import 依賴，避免循環 import：
  * stdlib: pandas, datetime.timedelta
  * 外部: ai_structured_summary.build_structured_summary_prompt（按鈕觸發時）
          / etf_fetch._fetch_news_for（按鈕觸發時）
  * etf_dashboard.py 內部 helper (21):
    - 渲染類: _colored_box / _plot_etf_chart / _render_bias
      / _teacher_conclusion / macro_allocation_banner
    - 計算類: auto_detect_benchmark / calc_avg_yield / calc_cagr / calc_current_yield
      / calc_premium_discount / calc_total_return_1y / calc_tracking_error
      / check_vcp_signal / compute_etf_peer_ranking
    - 抓取類: fetch_etf_dividends / fetch_etf_info / fetch_etf_nav_history
      / fetch_etf_price / get_etf_expense_ratio_safe / _get_etf_launch_price

呼叫端
======
- app.py 經 etf_dashboard re-export 取用：`from etf_dashboard import render_etf_single`
"""
from __future__ import annotations

import streamlit as st


def render_etf_single(gemini_fn=None):
    # ─ Late imports（避免循環 import）─
    import pandas as pd
    from datetime import timedelta
    from etf_dashboard import (
        # 渲染類
        _colored_box, _plot_etf_chart, _render_bias, render_etf_holdings,
        _teacher_conclusion, macro_allocation_banner,
        # 計算類
        auto_detect_benchmark, calc_avg_yield, calc_cagr, calc_current_yield,
        calc_premium_discount, calc_total_return_1y, calc_tracking_error,
        check_vcp_signal, compute_etf_peer_ranking,
        # 抓取類
        fetch_etf_dividends, fetch_etf_info, fetch_etf_nav_history,
        fetch_etf_price, get_etf_expense_ratio_safe, _get_etf_launch_price,
    )

    mkt_info = st.session_state.get('mkt_info', {})
    regime   = mkt_info.get('regime', 'neutral')
    macro_allocation_banner(regime)

    st.markdown('#### 🔍 輸入 ETF 代號')
    col_l, col_r = st.columns([2, 1])
    ticker    = col_l.text_input('ETF 代號（台灣加 .TW，如 0050.TW | 美國：SPY、QQQ）',
                                  value='0050.TW', key='etf_s_ticker').strip().upper()
    benchmark = col_r.text_input('對照基準（留空自動偵測）',
                                  value='', key='etf_s_bench').strip().upper()
    if not benchmark:
        benchmark = auto_detect_benchmark(ticker)

    if st.button('🔍 開始診斷', key='etf_s_btn', use_container_width=True):
        st.session_state['etf_s_active'] = ticker

    if st.session_state.get('etf_s_active') != ticker:
        st.info('💡 輸入 ETF 代號後點擊「開始診斷」')
        return

    with st.spinner(f'載入 {ticker} 資料中...'):
        df       = fetch_etf_price(ticker)
        divs     = fetch_etf_dividends(ticker)
        info     = fetch_etf_info(ticker)
        bench_df = fetch_etf_price(benchmark)

    if df.empty:
        st.error(f'❌ 找不到 {ticker}，請確認代號（台灣ETF需加 .TW）')
        st.session_state.pop('etf_s_active', None)
        return

    etf_name = info.get('longName') or info.get('shortName') or ticker
    # 費用率走 SITCA primary（台股 ETF 官方，海外 IP 走 NAS proxy）→ yfinance fallback
    expense  = get_etf_expense_ratio_safe(ticker)
    beta     = info.get('beta') or info.get('beta3Year')
    aum      = info.get('totalAssets')

    st.markdown(f'### 🏦 {etf_name} ({ticker})')

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('最新收盤', f'{df["Close"].iloc[-1]:.2f}')
    c2.metric('內扣費用率', f'{expense*100:.2f}%' if expense else 'N/A')
    c3.metric('Beta', f'{float(beta):.2f}' if beta else 'N/A')
    c4.metric('AUM', f'{aum/1e9:.1f}B USD' if aum and aum > 1e6 else 'N/A')

    with st.expander('💡 這項數據代表什麼？（內扣費用率 · Beta · AUM）', expanded=False):
        st.markdown(
            '- **內扣費用率**：每年從資產裡自動扣的管理成本，**越低越好**（被動型多 <0.5%，主動型較高）；長期複利下 0.5% 差距很可觀。\n'
            '- **Beta（β）**：相對大盤的波動敏感度。**β≈1** 與大盤同步；**β>1** 漲跌更兇（攻擊型）；**β<1** 較抗跌（防禦型）—— 配置時用來控整體風險。\n'
            '- **AUM（基金規模）**：總管理資產。**太小（如 <10 億）有清算下市風險**；規模大則流動性好、買賣價差小。'
        )

    # ── 自製品質評等（4 因子：AUM / 費用率 / 殖利率穩定度 / Beta）──
    try:
        from etf_quality import compute_etf_quality, render_quality_badge
        _quality = compute_etf_quality(ticker)
        render_quality_badge(_quality)
    except Exception as _e_q:
        st.caption(f'⚪ 品質評等載入失敗：{type(_e_q).__name__}')

    st.markdown('---')

    # ── 策略一：以息養股避雷 ─────────────────────────────────────
    st.markdown('#### 🧠 策略一：以息養股避雷')
    total_ret = calc_total_return_1y(df, divs)
    cur_yield = calc_current_yield(df, divs)
    ca, cb    = st.columns(2)
    ca.metric('近1年含息總報酬', f'{total_ret:.2f}%')
    cb.metric('現金殖利率（近12M）', f'{cur_yield:.2f}%')
    if cur_yield > 0 and total_ret < cur_yield:
        _colored_box('⚠️ <b>紅燈警示</b>：賺了股息賠了價差，侵蝕本金中，<b>不宜作為核心資產</b>', 'red')
        _teacher_conclusion('郭俊宏',
                            f'含息總報酬 {total_ret:.1f}% < 殖利率 {cur_yield:.1f}%',
                            '本金侵蝕中，高息陷阱',
                            '換標的，找總報酬為正的 ETF')
    elif cur_yield > 0:
        _colored_box(f'✅ 含息總報酬({total_ret:.1f}%) > 殖利率({cur_yield:.1f}%)，核心資產條件通過', 'green')
        _teacher_conclusion('郭俊宏',
                            f'含息總報酬 {total_ret:.1f}%，殖利率 {cur_yield:.1f}%',
                            '價差 + 配息雙贏，核心資產條件通過',
                            '可列入長期核心持倉')
    else:
        st.info('ℹ️ 無配息紀錄（成長型ETF），以價差報酬評估')
        _teacher_conclusion('郭俊宏',
                            f'近1年總報酬 {total_ret:.1f}%，無配息',
                            '成長型ETF，以價差報酬衡量',
                            '衡量 CAGR 是否超過大盤')

    # ── MK 框架 #1+#2+#7：配息健康度 + 3Y 年化報酬（汰弱五項中前兩項 + 留強 3-3-3 第二項）──
    st.markdown('#### 💧 配息健康度 + 年化報酬（MK 框架燈號）')
    _now2 = df.index[-1]
    _12m_div = float(divs[(divs.index >= _now2 - timedelta(days=365))].sum()) if not divs.empty else 0.0
    _prev12m_div = float(divs[(divs.index >= _now2 - timedelta(days=730))
                              & (divs.index < _now2 - timedelta(days=365))].sum()) if not divs.empty else 0.0
    _div_yoy = ((_12m_div - _prev12m_div) / _prev12m_div * 100) if _prev12m_div > 0 else None
    _3y_cutoff = _now2 - timedelta(days=365 * 3)
    _df_3y = df[df.index >= _3y_cutoff]
    _cagr3 = calc_cagr(_df_3y) if len(_df_3y) >= 30 else None
    # MK 框架 #6：成立年數（yfinance firstTradeDateEpochUtc primary，df span fallback）
    _incept_yrs = None
    try:
        _ep = info.get('firstTradeDateEpochUtc') if isinstance(info, dict) else None
        if _ep:
            import datetime as _dt_inc
            _incept_yrs = (_dt_inc.datetime.now()
                           - _dt_inc.datetime.fromtimestamp(int(_ep))).days / 365.25
    except Exception:
        pass
    if _incept_yrs is None and len(df) > 0:
        _incept_yrs = (df.index[-1] - df.index[0]).days / 365.25

    _mc1, _mc2, _mc3, _mc4 = st.columns(4)
    if _div_yoy is None:
        _mc1.metric('配息 12M YoY', 'N/A', delta='—')
    elif _div_yoy < -10:
        _mc1.metric('配息 12M YoY', f'{_div_yoy:+.1f}%', delta='⚠️ 衰退 > 10%', delta_color='inverse')
    elif _div_yoy < 0:
        _mc1.metric('配息 12M YoY', f'{_div_yoy:+.1f}%', delta='略減（< 10%）', delta_color='inverse')
    else:
        _mc1.metric('配息 12M YoY', f'{_div_yoy:+.1f}%', delta='✅ 增長 / 持平', delta_color='normal')
    if cur_yield > 0 and total_ret < cur_yield:
        _mc2.metric('含息報酬 − 殖利率', f'{total_ret - cur_yield:+.1f}pp',
                    delta='🔴 本金侵蝕', delta_color='inverse')
    elif cur_yield > 0:
        _mc2.metric('含息報酬 − 殖利率', f'{total_ret - cur_yield:+.1f}pp',
                    delta='✅ 雙贏', delta_color='normal')
    else:
        _mc2.metric('含息報酬 − 殖利率', 'N/A', delta='無配息')
    if _cagr3 is None:
        _mc3.metric('近 3Y 年化報酬', 'N/A', delta='資料不足 < 90 日')
    elif _cagr3 >= 7:
        _mc3.metric('近 3Y 年化報酬', f'{_cagr3:.1f}%',
                    delta='✅ 達 7% 定存替代', delta_color='normal')
    else:
        _mc3.metric('近 3Y 年化報酬', f'{_cagr3:.1f}%',
                    delta='🟡 不及 7% 門檻', delta_color='inverse')
    if _incept_yrs is None:
        _mc4.metric('成立年數', 'N/A')
    elif _incept_yrs >= 3:
        _mc4.metric('成立年數', f'{_incept_yrs:.1f} 年',
                    delta='✅ ≥ 3 年（多空考驗）', delta_color='normal')
    else:
        _mc4.metric('成立年數', f'{_incept_yrs:.1f} 年',
                    delta='🟡 未滿 3 年（選舊不選新）', delta_color='inverse')
    st.caption(
        '⚠️ 配息來源「**平準金佔比**」需 ETF 公開說明書揭露，本系統暫無穩定 API 來源故不顯示。'
        '**手動查法**：投信官網「基金月報 / 公開說明書」或 MoneyDJ 個別 ETF「收益分配」頁。'
        '判讀：平準金佔比過高（如 >30%）代表配息有相當比例來自本金回吐（拿自己的錢配給自己），需留意「賺息賠本」。'
        '\n\n💡 **判讀標準**：4 項指標若有 ≥ 2 項 🔴/🟡 警示 → 建議汰弱換強。'
    )

    # ── 策略二：7% 存股估值 ─────────────────────────────────────
    st.markdown('#### 🧠 策略二：7% 存股估值買賣點')
    avg_yield = calc_avg_yield(df, divs, years=5)
    cc, cd    = st.columns(2)
    cc.metric('近5年平均殖利率', f'{avg_yield:.2f}%' if avg_yield else 'N/A')
    cd.metric('現今殖利率', f'{cur_yield:.2f}%')
    if avg_yield > 0:
        if cur_yield >= 7:
            _colored_box('🟢 <b>強烈買進（特價）</b>：殖利率 ≥ 7%，現值低估，值得分批佈局', 'green')
            _teacher_conclusion('孫慶龍',
                                f'現金殖利率 {cur_yield:.1f}%（5年均 {avg_yield:.1f}%）',
                                '殖利率 ≥ 7%，低估特價區，強烈買進',
                                '分批佈局，停損設 -15%')
        elif cur_yield <= 3:
            _colored_box('🔴 <b>獲利了結（昂貴）</b>：殖利率 ≤ 3%，現值高估，考慮減碼', 'red')
            _teacher_conclusion('孫慶龍',
                                f'現金殖利率 {cur_yield:.1f}%（5年均 {avg_yield:.1f}%）',
                                '殖利率 ≤ 3%，高估昂貴區，獲利了結',
                                '分批出清，等待殖利率回升到 5% 以上')
        elif cur_yield <= 5:
            _colored_box('🟡 <b>適度減碼（合理）</b>：殖利率 ≤ 5%，估值合理偏高', 'yellow')
            _teacher_conclusion('孫慶龍',
                                f'現金殖利率 {cur_yield:.1f}%（5年均 {avg_yield:.1f}%）',
                                '殖利率 3%~5%，估值合理偏高，適度減碼',
                                '不宜重倉，等待 5% 以上再加碼')
        else:
            st.info(f'殖利率 {cur_yield:.1f}% 位於 5%~7% 合理區間，中性持有')
            _teacher_conclusion('孫慶龍',
                                f'現金殖利率 {cur_yield:.1f}%（5年均 {avg_yield:.1f}%）',
                                '殖利率 5%~7% 合理區間，中性持有',
                                '可持有，待殖利率 ≥ 7% 再加碼')
    else:
        st.info('ℹ️ 無充足配息歷史，套用回測頁評估價差績效')
        _teacher_conclusion('孫慶龍',
                            '配息歷史不足',
                            '無法套用 7% 存股聖經，改看回測 CAGR',
                            '前往「ETF回測」確認年化報酬是否 ≥ 8%')

    # ── 策略三：VCP 突破 ──────────────────────────────────────
    st.markdown('#### 🧠 策略三：VCP 波幅收縮突破')
    vcp = check_vcp_signal(df)
    ce, cf, cg = st.columns(3)
    ce.metric('站上 50MA',  '✅' if vcp['above_ma50']  else '❌')
    cf.metric('站上 200MA', '✅' if vcp['above_ma200'] else '❌')
    cg.metric('量能確認',   '✅' if vcp['vol_confirm'] else '❌')
    if vcp['weekly_ranges']:
        st.caption('近5週波幅：' + ' → '.join(f'{r}%' for r in vcp['weekly_ranges']))
    if vcp['signal']:
        _colored_box(f'🚀 <b>VCP 突破買訊！</b> 嚴守 8% 停損線：{vcp["stop_loss"]}', 'green')
        _teacher_conclusion('春哥',
                            '50MA ✅ | 200MA ✅ | 量能 ✅',
                            'VCP 三條件全過，突破買進',
                            f'停損設 {vcp["stop_loss"]}（-8%），突破後嚴守紀律')
    else:
        missing = []
        if not vcp['above_ma50']:
            missing.append('未站上50MA')
        if not vcp['above_ma200']:
            missing.append('未站上200MA')
        if not vcp['vol_confirm']:
            missing.append('量能不足')
        if len(df) < 210:
            missing.append('資料不足210天')
        _miss_str = ' | '.join(missing) if missing else '波幅尚未收縮'
        st.info('⏳ VCP 條件未滿足：' + _miss_str)
        _teacher_conclusion('春哥',
                            f'VCP 缺：{_miss_str}',
                            '條件未齊，耐心等候突破訊號',
                            '加入觀察清單，條件滿足再進場')

    # ── ETF 防呆：折溢價 + 追蹤誤差 + 建議買賣時機 ──────────
    st.markdown('#### 🛡️ ETF 折溢價 — 建議買賣時機')
    prem = calc_premium_discount(info, df, ticker)   # 傳入 ticker 以使用 FinMind/TWSE NAV
    te   = calc_tracking_error(df, bench_df)

    # 折溢價建議邏輯
    _pct = prem['premium_pct']
    if _pct is not None:
        if _pct <= -2:
            _prem_color  = '#3fb950'
            _prem_action = '🟢 強烈買進時機'
            _prem_reason = f'折價 {abs(_pct):.2f}%，低於 NAV 買入，立即為你創造安全邊際'
        elif _pct <= -0.5:
            _prem_color  = '#58a6ff'
            _prem_action = '🔵 合理買進'
            _prem_reason = f'折價 {abs(_pct):.2f}%，略低於 NAV，可正常分批買入'
        elif _pct <= 1.0:
            _prem_color  = '#d29922'
            _prem_action = '🟡 中性觀望'
            _prem_reason = f'溢價 {_pct:.2f}%（±1% 正常範圍），無需急追'
        elif _pct <= 3.0:
            _prem_color  = '#f85149'
            _prem_action = '🔴 暫緩買進'
            _prem_reason = f'溢價 {_pct:.2f}%，高於 NAV，追高風險較大，等待回落'
        else:
            _prem_color  = '#f85149'
            _prem_action = '🔴 嚴禁追高'
            _prem_reason = f'溢價 {_pct:.2f}%，嚴重高溢價，等待折價或換標的'
    elif prem.get('stale_nav'):
        _prem_color  = '#8b949e'
        _prem_action = '⏳ NAV 資料延遲'
        _prem_reason = 'NAV 資料早於前一交易日（FinMind/yfinance 同步延遲），暫不顯示折溢價以免誤判'
    else:
        _prem_color  = '#8b949e'
        _prem_action = 'ℹ️ 無 NAV 資料'
        _prem_reason = 'yfinance 未提供 NAV，建議至官網確認折溢價'

    st.markdown(
        f'<div style="background:#0d1117;border:2px solid {_prem_color};border-radius:10px;'
        f'padding:14px 18px;margin-bottom:10px;">'
        f'<div style="font-size:20px;font-weight:900;color:{_prem_color};">{_prem_action}</div>'
        f'<div style="font-size:13px;color:#c9d1d9;margin-top:4px;">{_prem_reason}</div>'
        + (f'<div style="font-size:12px;color:#8b949e;margin-top:6px;">折溢價率：'
           f'<b style="color:{_prem_color};">{_pct:+.2f}%</b>'
           + (f'　<span style="color:#6e7681;">（資料日：{prem.get("data_date")}）</span>'
              if prem.get('data_date') else '')
           + '</div>' if _pct is not None else '')
        + '</div>',
        unsafe_allow_html=True)

    if _pct is not None:
        _prem_concl = ('折價買進，獲得安全邊際' if _pct <= -0.5
                       else '中性，無需急追' if _pct <= 1.0
                       else '高溢價，追高風險大，等待回落')
        _prem_act2  = ('分批買進' if _pct <= -0.5
                       else '持有觀望' if _pct <= 1.0
                       else '暫緩或換標的')
        _teacher_conclusion('宏爺', f'{ticker} 折溢價 {_pct:+.2f}%', _prem_concl, _prem_act2)

    ch, ci = st.columns(2)
    ch.metric('折溢價率', f'{_pct:+.2f}%' if _pct is not None else 'N/A')
    if te is not None:
        ci.metric(f'追蹤誤差 vs {benchmark}', f'{te:.2f}%')
        if te > 1.5:
            ci.markdown('<small style="color:#d29922;">⚠️ 追蹤誤差 >1.5%，注意隱藏成本</small>',
                        unsafe_allow_html=True)
    else:
        ci.metric('追蹤誤差', 'N/A')

    # ── 歷史淨值及折溢價表 ────────────────────────────────────
    import pandas as _pd_navtbl
    _nav_hist = fetch_etf_nav_history(ticker, days=35)
    if not _nav_hist.empty and 'nav' in _nav_hist.columns and not df.empty:
        try:
            _price_s = df[['Close']].copy()
            _price_s.index = _pd_navtbl.to_datetime(_price_s.index).normalize()
            _nav_hist2 = _nav_hist.copy()
            _nav_hist2['date'] = _pd_navtbl.to_datetime(_nav_hist2['date'])
            _nav_hist2 = _nav_hist2.set_index('date')
            _merged = _nav_hist2.join(_price_s, how='inner').dropna()
            if not _merged.empty:
                _merged['折溢價']  = (_merged['Close'] - _merged['nav']).round(2)
                _merged['折溢價%'] = ((_merged['Close'] - _merged['nav']) / _merged['nav'] * 100).round(2)
                _display = _merged.reset_index()[['date','Close','nav','折溢價','折溢價%']].tail(20)
                _display.columns = ['日期','市價','淨值','折溢價','折溢價%']
                _display['日期'] = _display['日期'].dt.strftime('%Y/%m/%d')
                st.markdown(f'**{ticker} 近期淨值及折溢價**（折溢價% = (市價-淨值)/淨值×100）')
                st.dataframe(_display.sort_values('日期', ascending=False),
                             use_container_width=True, hide_index=True)
        except Exception as _ne:
            print(f'[ETF NAV Table] {_ne}')

    # ── BIAS 乖離率 ───────────────────────────────────────────
    st.markdown('#### 📐 BIAS 乖離率（均線偏離程度）')
    _render_bias(df, ticker)

    # ── 年線乖離率(MA240) + KD — 供存股 AI 使用 ──────────────
    _close_ai = df['Close'] if 'Close' in df.columns else df.get('close', pd.Series(dtype=float))
    _bias240_ai = None
    _kv_ai = _dv_ai = None
    if len(_close_ai) >= 240:
        _ma240_ai   = float(_close_ai.rolling(240).mean().iloc[-1])
        _bias240_ai = round((float(_close_ai.iloc[-1]) - _ma240_ai) / _ma240_ai * 100, 2)
    if 'High' in df.columns and 'Low' in df.columns and len(df) >= 9:
        _h9  = df['High'].rolling(9).max()
        _l9  = df['Low'].rolling(9).min()
        _rsv = ((df['Close'] - _l9) / (_h9 - _l9).replace(0, float('nan')) * 100).fillna(50)
        _k_s = _rsv.ewm(com=2, adjust=False).mean()
        _d_s = _k_s.ewm(com=2, adjust=False).mean()
        _kv_ai = round(float(_k_s.iloc[-1]), 1)
        _dv_ai = round(float(_d_s.iloc[-1]), 1)

    # ── MK 框架 #11：標準差 σ 量化買點（年線 ± σ 位階分級）──────
    st.markdown('#### 🎯 標準差量化買點（MK 框架：跌了就買）')
    if len(df) >= 252:
        _ret_252 = df['Close'].pct_change().tail(252).dropna()
        _sigma_pct = (float(_ret_252.std()) * (252 ** 0.5) * 100) if not _ret_252.empty else 0.0
        _cur_p = float(df['Close'].iloc[-1])
        _ma240 = float(df['Close'].rolling(240).mean().iloc[-1]) if len(df) >= 240 else None
        if _ma240 and _sigma_pct > 0:
            _bias_pct = (_cur_p - _ma240) / _ma240 * 100
            _z = _bias_pct / _sigma_pct
            if _z <= -2:
                _label, _color, _action = '🟢 極佳買點（≤ -2σ）', 'green', '大跌大買 — 大幅加碼，剩餘資金主力投入'
            elif _z <= -1:
                _label, _color, _action = '🟢 進場買點（-2σ ~ -1σ）', 'green', '小跌小買 — 投入 20–30% 資金'
            elif _z <= 1:
                _label, _color, _action = '🟡 持平區（±1σ 內）', 'yellow', '保留現金，等待 ≤ -1σ 進場'
            elif _z <= 2:
                _label, _color, _action = '🟠 偏高（+1σ ~ +2σ）', 'yellow', '不追高；衛星部位可考慮停利'
            else:
                _label, _color, _action = '🔴 極端偏高（≥ +2σ）', 'red', '建議減碼；勿在 +2σ 以上加碼'
            _colored_box(
                f'<b>{_label}</b><br>'
                f'目前 {_cur_p:.2f} vs MA240 {_ma240:.2f} → '
                f'偏離 {_bias_pct:+.2f}%（年化 σ ≈ {_sigma_pct:.1f}%，z = {_z:+.2f}）<br>'
                f'<b>建議</b>：{_action}',
                _color,
            )
            _teacher_conclusion('郭俊宏',
                                f'位階 z={_z:+.2f}σ',
                                _label.split('（')[0],
                                _action)
        else:
            st.info('ℹ️ MA240 或 σ 不足，無法分級')
    else:
        st.info(f'ℹ️ 資料不足 252 日（目前 {len(df)} 日），無法計算 σ 位階')

    # ── MK 框架 #5：季線 × 趨勢 聯合警示燈號（跌破 + 下彎 = 趨勢轉弱）──
    st.markdown('#### 📉 季線 × 趨勢 聯合警示（MK 框架：技術面防禦）')
    if len(df) >= 80:
        _close_now = float(df['Close'].iloc[-1])
        _ma60_series = df['Close'].rolling(60).mean()
        _ma60_now = float(_ma60_series.iloc[-1])
        _ma60_20d = float(_ma60_series.iloc[-21])
        _above_ma60 = _close_now > _ma60_now
        _ma60_slope = (_ma60_now - _ma60_20d) / _ma60_20d * 100 if _ma60_20d > 0 else 0.0
        _ma60_up = _ma60_slope > 0
        if _above_ma60 and _ma60_up:
            _t5_label, _t5_color, _t5_action = '🟢 健康（站上季線且 MA60 上彎）', 'green', '正常持有，不需動作'
        elif _above_ma60 and not _ma60_up:
            _t5_label, _t5_color, _t5_action = '🟡 上漲乏力（站上但 MA60 下彎）', 'yellow', '觀察 MA60 是否止跌；衛星部位降槓桿'
        elif not _above_ma60 and _ma60_up:
            _t5_label, _t5_color, _t5_action = '🟡 短線回測（跌破但 MA60 仍上彎）', 'yellow', '可逢低分批布局，等回上 MA60 確認'
        else:
            _t5_label, _t5_color, _t5_action = '🔴 趨勢轉弱（跌破 MA60 且下彎）', 'red', '建議減碼或觀望，等趨勢翻轉'
        _colored_box(
            f'<b>{_t5_label}</b><br>'
            f'Close {_close_now:.2f} vs MA60 {_ma60_now:.2f}（'
            f'{(_close_now-_ma60_now)/_ma60_now*100:+.2f}%）<br>'
            f'MA60 20 日斜率：{_ma60_slope:+.2f}%（{"上彎 ↗" if _ma60_up else "下彎 ↘"}）<br>'
            f'<b>建議</b>：{_t5_action}',
            _t5_color,
        )
        _teacher_conclusion('郭俊宏',
                            f'季線 {("站上" if _above_ma60 else "跌破")}+'
                            f'{("上彎" if _ma60_up else "下彎")}',
                            _t5_label.split('（')[0],
                            _t5_action)
    else:
        st.info(f'ℹ️ 資料不足 80 日（目前 {len(df)} 日），無法計算季線 × 斜率')

    # ── MK 規格三大訊號：破發 ｜ 跌破均線買點 ｜ 死亡交叉 ────────
    st.markdown('#### 🚨 MK 規格三大訊號（破發檢測 ｜ 跌了就買 ｜ 趨勢警示）')
    _cur_price = float(df['Close'].iloc[-1]) if len(df) > 0 else None

    # ① 條件 B：破發檢測（市價 < 發行價 → 法規限制配資本利得 → 配息必縮水）
    _launch_price = _get_etf_launch_price(ticker, df)
    _vs_launch_pct = None
    _broken_issue = False
    if _launch_price and _cur_price:
        _vs_launch_pct = (_cur_price - _launch_price) / _launch_price * 100
        _broken_issue = _cur_price < _launch_price
        if _broken_issue:
            _colored_box(
                f'🔴 <b>條件 B 警訊：破發狀態</b><br>'
                f'最新市價 {_cur_price:.2f} &lt; 發行價 {_launch_price:.2f}'
                f'（{_vs_launch_pct:+.2f}%）<br>'
                f'<b>MK 提醒</b>：法規規定 ETF 淨值低於發行價時不能配發資本利得，'
                f'配息率「一定會縮水」；若同時觸發條件 A（吃本金）→ 標準汰弱訊號',
                'red')
            _teacher_conclusion('郭俊宏',
                                f'市價 {_cur_price:.2f} < 發行價 {_launch_price:.2f}',
                                '破發 → 配資本利得受限，配息將縮水',
                                '若搭配條件 A → 換股汰弱')
        else:
            _colored_box(
                f'✅ <b>條件 B 通過：未破發</b><br>'
                f'市價 {_cur_price:.2f} ≥ 發行價 {_launch_price:.2f}'
                f'（{_vs_launch_pct:+.2f}%）',
                'green')
    else:
        st.info('ℹ️ 無發行價資料（非台股 ETF 或代號未收錄）→ 跳過條件 B')

    # ② 跌了就買：跌破月線 / 季線（規格版直球買點訊號）
    _ma20 = _ma60_v = None
    _below_ma20 = _below_ma60 = False
    if len(df) >= 60 and _cur_price:
        _ma20   = float(df['Close'].rolling(20).mean().iloc[-1])
        _ma60_v = float(df['Close'].rolling(60).mean().iloc[-1])
        _below_ma20 = _cur_price < _ma20
        _below_ma60 = _cur_price < _ma60_v
        if _below_ma60:
            _colored_box(
                f'🟢🟢 <b>跌破季線：波段大買點（超跌）</b><br>'
                f'市價 {_cur_price:.2f} &lt; MA60 {_ma60_v:.2f}'
                f'（{(_cur_price-_ma60_v)/_ma60_v*100:+.2f}%）<br>'
                f'<b>MK 提醒</b>：跌破季線視為波段超跌，分批加碼黃金區',
                'green')
            _teacher_conclusion('郭俊宏',
                                f'市價 {_cur_price:.2f} < MA60 {_ma60_v:.2f}',
                                '波段超跌進場區',
                                '剩餘資金分批加碼')
        elif _below_ma20:
            _colored_box(
                f'🟢 <b>跌破月線：短線小買點</b><br>'
                f'市價 {_cur_price:.2f} &lt; MA20 {_ma20:.2f}'
                f'（{(_cur_price-_ma20)/_ma20*100:+.2f}%）<br>'
                f'<b>MK 提醒</b>：跌破月線可小量加碼',
                'green')
            _teacher_conclusion('郭俊宏',
                                f'市價 {_cur_price:.2f} < MA20 {_ma20:.2f}',
                                '短線小買點',
                                '投入 20–30% 資金小量加碼')
        else:
            _colored_box(
                f'⚪ <b>站上月線/季線</b>：市價 {_cur_price:.2f} ≥ '
                f'MA20 {_ma20:.2f} / MA60 {_ma60_v:.2f}<br>'
                f'未進入「跌了就買」區間，維持紀律扣款或觀望',
                'yellow')

        # ③ 死亡交叉：MA20 < MA60 → 趨勢偏空
        if _ma20 < _ma60_v:
            _colored_box(
                f'🟡 <b>趨勢偏空：MA20 &lt; MA60（死亡交叉）</b><br>'
                f'MA20 {_ma20:.2f} &lt; MA60 {_ma60_v:.2f}'
                f'（差 {(_ma20-_ma60_v)/_ma60_v*100:+.2f}%）<br>'
                f'<b>MK 提醒</b>：均線死叉 → 注意風險，衛星部位降槓桿',
                'yellow')
            _teacher_conclusion('郭俊宏',
                                f'MA20 {_ma20:.2f} < MA60 {_ma60_v:.2f}',
                                '均線死叉 → 趨勢偏空',
                                '衛星部位停利或減碼，核心紀律扣款')
        else:
            st.caption(f'✅ 黃金交叉狀態：MA20 {_ma20:.2f} ≥ MA60 {_ma60_v:.2f}（趨勢偏多）')
    else:
        st.info(f'ℹ️ 資料不足 60 日（目前 {len(df)} 日），無法計算月線/季線交叉')

    # ── 同儕近 3M/6M/1Y 排名 ──────────────────────────────────
    _peer_rank = compute_etf_peer_ranking(ticker)
    if _peer_rank.get('_err'):
        st.caption(f'⚪ 同儕排名：{_peer_rank["_err"]}（分類 {_peer_rank.get("category") or "未分類"}）')
    else:
        _cat = _peer_rank.get('category', '')
        st.markdown(f'#### 🏆 {ticker} 同儕排名（vs {_cat} 類）')
        _c3m, _c6m, _c1y = st.columns(3)
        for _col, _lbl, _key in [(_c3m, '近 3M', 63), (_c6m, '近 6M', 126), (_c1y, '近 1Y', 252)]:
            _data = _peer_rank.get(_key) or {}
            with _col:
                if _data.get('_err'):
                    st.metric(_lbl, 'N/A', help=_data['_err'])
                    continue
                _self = _data['self_ret']
                _med = _data['peer_median']
                _pct = _data['percentile']
                _n = _data['peer_count']
                _icon = '🟢' if _pct >= 75 else ('🟡' if _pct >= 25 else '🔴')
                _color = '#3fb950' if _pct >= 75 else ('#d29922' if _pct >= 25 else '#f85149')
                st.markdown(
                    f"<div style='border:1px solid {_color};border-left:4px solid {_color};"
                    f"border-radius:0 6px 6px 0;padding:8px 14px;background:#0d1117'>"
                    f"<div style='color:#8b949e;font-size:11px'>{_lbl}　{_icon} PR {_pct:.0f}</div>"
                    f"<div style='color:{_color};font-size:22px;font-weight:700;margin-top:2px'>"
                    f"{_self:+.2f}%</div>"
                    f"<div style='color:#6e7681;font-size:11px;margin-top:4px'>"
                    f"vs 同類 {_n} 檔（中位數 {_med:+.2f}%）</div>"
                    f"</div>", unsafe_allow_html=True)
        st.caption('PR = 百分位排名（越高代表勝率越好）；報酬已含息（yfinance auto_adjust）。'
                   '🟢 PR≥75　🟡 25-75　🔴 <25')

    # ── 走勢圖 ────────────────────────────────────────────────
    st.markdown(f'#### 📈 {ticker} 近5年走勢')
    _plot_etf_chart(df, ticker, benchmark, bench_df)

    # ── 成分股（持股明細）────────────────────────────────────
    st.markdown(f'#### 🧩 {ticker} 成分股（持股明細）')
    st.caption('💡 看這檔 ETF「真正持有哪些股票、各佔多少權重」。權重越集中代表越押注少數個股、'
               '分散效果越低；可對照前面的折溢價與走勢一起判斷。')
    render_etf_holdings(ticker, top_n=15, key=f'single_{ticker}')

    # ── 存入 session_state 供 Tab⑨ 使用 ─────────────────────
    # 海外 ETF 偵測：ticker 非 4-6 碼台灣代號（如 VOO/SCHD/QQQ）→ 本系統 NAV/費用率
    # 5 源僅限台灣 ETF（SITCA / FinMind / TWSE / goodinfo / MoneyDJ），標 ⚪ 非異常
    # 末位字母後綴允許：A=Active 主動式 / L=Leveraged / R=Reverse / B=Bond / U/F=Futures
    import re as _re_etf
    _is_overseas = not bool(_re_etf.match(r'^\d{4,6}[A-Z]?\.(TW|TWO)$', ticker))
    _nav_value = (prem or {}).get('nav')
    _likely_private = ((not _is_overseas) and (not aum)
                      and (not expense) and (_nav_value is None))
    # v1.1：主動式 ETF Yuanta fallback 仍抓不到時 → 視為「公開資料受限」
    try:
        from etf_fetch import is_active_etf as _is_act_etf
        _is_active = _is_act_etf(ticker)
    except ImportError:
        _is_active = False
    _restricted = _likely_private or _is_active
    _err_expense = None if (expense or _is_overseas or _restricted) else (
        'SITCA + MoneyDJ + yfinance.info[expenseRatio] 3 源全失敗'
        '（私募 / 已下市可能）'
    )
    _err_nav = None if (_nav_value is not None or _is_overseas or _restricted) else (
        'FinMind ETF NAV + goodinfo + TWSE OpenAPI + MoneyDJ + yfinance 5 源全失敗'
    )
    st.session_state['etf_single_data'] = {
        'ticker': ticker, 'name': etf_name,
        'cur_yield': cur_yield, 'avg_yield': avg_yield,
        'total_ret': total_ret, 'vcp': vcp,
        'premium': prem, 'te': te, 'regime': regime,
        'price_df': df,
        'expense': expense, 'beta': beta, 'aum': aum,
        'k_val': _kv_ai, 'd_val': _dv_ai,
        'bias240': _bias240_ai,
        # MK 規格三大訊號
        'launch_price':   _launch_price,
        'vs_launch_pct':  _vs_launch_pct,
        'broken_issue':   _broken_issue,
        'below_ma20':     _below_ma20,
        'below_ma60':     _below_ma60,
        'dead_cross':     (_ma20 is not None and _ma60_v is not None
                           and _ma20 < _ma60_v),
        '_is_overseas': _is_overseas,
        '_likely_private': _likely_private,
        '_is_active_etf': _is_active,
        '_err_expense': _err_expense,
        '_err_nav':     _err_nav,
    }

    # ── AI 白話結構化總結（取代舊的統一決策三卡片）─────────────
    st.markdown('### 🧠 AI 白話總結')
    st.caption('把這檔 ETF 的數據翻成「跟長輩聊天」的白話，逐項講好壞與要注意的地方。'
               '⚠️ 僅供學術研究，非投資建議。')

    # 小工具：None 一律顯示 N/A，數值補上單位
    def _fmt(_v, _suffix='', _sign=False, _nd=2):
        if _v is None:
            return 'N/A'
        try:
            _f = float(_v)
            return f'{_f:+.{_nd}f}{_suffix}' if _sign else f'{_f:.{_nd}f}{_suffix}'
        except (TypeError, ValueError):
            return str(_v)

    _prem_pct = prem.get('premium_pct') if isinstance(prem, dict) else None
    _ai_sum_key = f'etf_ai_sum_{ticker}'
    if st.button('🧠 生成 AI 白話總結', key=_ai_sum_key, use_container_width=True):
        from ai_structured_summary import build_structured_summary_prompt
        from etf_fetch import _fetch_news_for

        _sections = [
            {
                'name': '買這檔大概能領多少利息（配息）',
                'data': (
                    f'現金殖利率（你買進後一年大概能領回幾 % 現金）={_fmt(cur_yield, "%")}；'
                    f'近5年平均殖利率（過去5年平均一年領回幾 %）={_fmt(avg_yield, "%")}。'
                ),
            },
            {
                'name': '過去一年賺賠多少、現在貴不貴（報酬與位階）',
                'data': (
                    f'近1年含息總報酬（連配息一起算，過去一年賺或賠幾 %）={_fmt(total_ret, "%")}；'
                    f'年線乖離（現在價格比過去一年平均價高/低幾 %，正數=偏高偏貴、負數=偏低）='
                    f'{_fmt(_bias240_ai, "%", _sign=True) if _bias240_ai is not None else "N/A（上市未滿約一年）"}；'
                    f'KD（短線過熱或過冷的溫度計，80 以上偏熱、20 以下偏冷）='
                    f'{(f"K={_fmt(_kv_ai, _nd=1)} D={_fmt(_dv_ai, _nd=1)}") if _kv_ai is not None else "N/A"}。'
                ),
            },
            {
                'name': '這檔健不健康（買貴沒、跟得上沒、內扣貴不貴、夠不夠大）',
                'data': (
                    f'折溢價（市價比這檔真正的身價貴還是便宜，正數=買貴了、負數=撿便宜）='
                    f'{_fmt(_prem_pct, "%", _sign=True) if _prem_pct is not None else "N/A"}；'
                    f'追蹤誤差（它跟它要追的指數差多少，越小代表越貼、越乖）={_fmt(te, "%")}；'
                    f'內扣費用率（每年自動從你錢裡扣掉的管理費 %）={_fmt(expense * 100, "%") if expense else "N/A"}；'
                    f'規模 AUM（這檔總共管多少錢，越大通常越穩、越不怕清算）='
                    f'{f"{aum / 1e9:.1f}B 美元" if (aum and aum > 1e6) else "N/A"}；'
                    f'Beta（跟著大盤上下震動的幅度，>1 比大盤更激動、<1 比較穩）={_fmt(beta)}。'
                ),
            },
            {
                'name': '有沒有破發、跌破均線等警訊',
                'data': (
                    f'破發（現在市價是否已經跌破當初發行的價格）='
                    f'{("是，已破發" if _broken_issue else "否")}'
                    f'（vs 發行價 {_fmt(_vs_launch_pct, "%", _sign=True) if _vs_launch_pct is not None else "N/A"}）；'
                    f'跌破月線 MA20（短期約一個月的平均成本線）={("是" if _below_ma20 else "否")}；'
                    f'跌破季線 MA60（中期約一季的平均成本線）={("是" if _below_ma60 else "否")}；'
                    f'死亡交叉（短期均線往下穿過中期均線，常被視為轉弱訊號）='
                    f'{("是" if (_ma20 is not None and _ma60_v is not None and _ma20 < _ma60_v) else "否")}；'
                    f'目前大盤狀態={regime}。'
                ),
            },
        ]

        _news_text = _fetch_news_for(ticker, etf_name, 4)
        _prompt = build_structured_summary_prompt(
            f'{ticker} {etf_name} 這檔 ETF',
            _sections,
            news_text=_news_text,
            overall_question='這檔 ETF 適合什麼樣的人、現在買貴了沒、要注意什麼。',
        )
        if gemini_fn is None:
            st.warning('未提供 AI 服務（gemini_fn），無法生成總結。')
        else:
            with st.spinner('AI 白話總結生成中...'):
                _ai_result = gemini_fn(_prompt, max_tokens=1600)
            if _ai_result and not str(_ai_result).startswith('⚠️'):
                st.session_state[f'{_ai_sum_key}_result'] = _ai_result
            else:
                st.warning(_ai_result or 'AI 回傳為空，請確認 GEMINI_API_KEY')

    _ai_saved = st.session_state.get(f'{_ai_sum_key}_result')
    if _ai_saved:
        st.markdown(_ai_saved)
