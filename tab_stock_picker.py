"""🎯 智慧選股 TAB — 三階段濾網（基本面 / 籌碼技術 / AI 綜合建議）

Per CLAUDE.md §2 設計：使用者輸入觀察清單 10-30 檔，按鈕觸發批次跑（不全市場掃描避免 API 風暴）

三階段邏輯（全 15 項條件實作完成 — Stage 1 ×9 + Stage 2 ×6 + Stage 3 AI）
==========================================================================

Stage 1：基本面防禦與成長（9 項）
- ✅ 負債比 < 50%（FinMind 資產負債表，金融股標 ⚠️ 不誤殺）
- ✅ 三率三升 YoY（毛利率 / 營益率 / 淨利率 — FinMind 損益表 8 季）
- ✅ 連續 5 年配息 + 平均殖利率 > 7%（yfinance.dividends）
- ✅ PE 河流圖區間（真 TTM EPS = 近 4 季加總；便宜 <10 / 合理 <15 / 昂貴）
- ✅ 應收帳款周轉天數穩定（季變動 < 30%）
- ✅ 存貨周轉率年化 > 4 次
- ✅ 資本支出積極（CapEx > 股東權益 5%）
- ✅ 淨流動值為正（流動資產 > 總負債）
- ✅ 合約負債 YoY > 20% + 連 2 季增（FinMind BS 多季）

Stage 2：籌碼與技術面鎖定（6 項）
- ✅ 股價站穩 MA20 + 月線翻揚
- ✅ MACD 綠轉紅 / 柱狀體收斂轉發散
- ✅ KD 低檔黃金交叉（K < 20）
- ✅ 布林通道剛開口（band 寬度近 5 日 > 前 20 日 1.3 倍）
- ✅ 投信連續 5 日買超（FinMind 法人買賣超）
- ✅ 大戶 ≥1000 張級距持股近 2 週比例增加（FinMind 集保股權分散）

Stage 3：AI 綜合建議
- ✅ Gemini Markdown 報告 — 積極型 / 保守型 / 止損紀律三型分析

呼叫端
======
- app.py 於「💎 高息網」(tab_screener) 候選清單下方呼叫，candidates 帶入 render_yield_screener() 的篩選結果
"""
from __future__ import annotations

import streamlit as st


def render_tab_stock_picker(gemini_fn=None, candidates=None):
    # ─ Late imports（避免循環 import + 啟動時間）─
    import datetime as _dt_sp
    import pandas as pd
    import yfinance as yf

    st.markdown('### 🎯 智慧選股 — 三階段濾網')
    st.caption('專業台股投資策略：① 基本面防禦 → ② 籌碼技術 → ③ AI 綜合建議。'
               '從上方「💎 高息網」候選清單勾選標的，系統自動跑三階段篩選並提供配置建議。')
    st.caption('💡 全 15 項條件實作完成：Stage 1 基本面 ×9 + Stage 2 籌碼技術 ×6 + Stage 3 AI 建議。')

    with st.expander('💡 三階段濾網在篩什麼？（基本面 → 籌碼技術 → AI）', expanded=False):
        st.markdown(
            '**Stage 1 · 基本面防禦（9 項）**：負債比、三率三升（毛利/營益/淨利率同步走高）、連續 5 年配息且均殖利率>7%、本益比估值區、應收帳款週轉、存貨週轉、資本支出/股東權益、淨值比、合約負債 YoY。→ 過 5 項以上視為體質健康。\n\n'
            '**Stage 2 · 籌碼技術（6 項）**：站上 20MA 且上彎、MACD 翻多、KD 黃金交叉、布林通道開口、三大法人買超、集保大戶持股增加。→ 抓「便宜又剛要發動」的時機。\n\n'
            '**Stage 3 · AI 綜合建議**：把上述量化結果＋新聞餵給 AI，輸出客觀的進場/觀望總結與配置權重。\n\n'
            '🎯 核心邏輯：**先用基本面排除地雷，再用籌碼技術抓發動點** —— 避免買到便宜卻沒人要的「價值陷阱」。'
        )

    # ── Section 1：候選清單來自高息網篩選結果 ─────────────────────
    st.markdown('#### 📋 候選清單（來自上方「高息網」篩選結果，勾選後跑三階段）')
    if candidates is None or len(candidates) == 0:
        st.info('💡 請先在上方「💎 高息網」設定殖利率 / 本益比條件，篩出候選清單後，'
                '這裡會自動帶入供你勾選。')
        return

    # 去重保序取出純代碼
    _codes: list[str] = []
    for _, _row in candidates.iterrows():
        _c = str(_row.get('代碼') or '').strip()
        if _c and _c not in _codes:
            _codes.append(_c)
    if not _codes:
        st.info('💡 高息網候選清單為空，請放寬殖利率 / 本益比條件。')
        return

    _sel = st.multiselect(
        f'從高息網 {len(_codes)} 檔候選中勾選（建議 10-30 檔，避免 API 風暴）',
        _codes, default=_codes[:10], key='picker_multiselect',
        help='預設帶入殖利率最高的前 10 檔，可自由增減；上限 30 檔')

    if not st.button('🎯 開始三階段篩選', key='picker_btn',
                     use_container_width=True, type='primary'):
        st.info('💡 勾選候選股票後按「🎯 開始三階段篩選」')
        return

    # ── 解析清單 ─────────────────────────────────────────────
    _tickers = list(dict.fromkeys(_sel))
    if not _tickers:
        st.error('❌ 請至少勾選一檔候選股票')
        return
    if len(_tickers) > 30:
        st.warning(f'⚠️ 超過 30 檔（{len(_tickers)}），僅取前 30 檔避免 API 風暴')
        _tickers = _tickers[:30]

    # ── 跑三階段篩選 ─────────────────────────────────────────
    _today = _dt_sp.date.today()
    results: list[dict] = []
    with st.spinner(f'三階段篩選中（{len(_tickers)} 檔）...'):
        for _tk in _tickers:
            _r = _check_one_stock(_tk, _today, yf)
            results.append(_r)

    # ── Stage 1：基本面表 ─────────────────────────────────────
    st.markdown('---')
    st.markdown('#### 📊 Stage 1：基本面防禦與成長')
    _s1_df = pd.DataFrame([{
        '代號':       r['ticker'],
        '負債比':     r['debt_ratio_label'],
        '三率三升':   r['three_rate_label'],
        '5Y 配息':    r['div_5y_label'],
        'PE 區間':    r['pe_zone_label'],
        '應收周轉':   r['ar_turnover_label'],
        '存貨周轉':   r['inv_turnover_label'],
        '資本支出':   r['capex_label'],
        '淨流動值':   r['book_value_label'],
        '合約負債':   r['contract_liab_label'],
        'S1 通過':    f"{r['s1_pass_cnt']}/9",
    } for r in results])
    st.dataframe(_s1_df, hide_index=True, use_container_width=True)
    st.caption('💡 通過數 = 9 項實作條件中過的個數；5+ 通過視為基本面健康。'
               '「應收周轉」穩定 = 季變動 < 30%；「存貨周轉」OK = 年化 > 4 次；'
               '「資本支出」積極 = CapEx > 股東權益 5%；「淨流動值」OK = 流動資產 > 總負債；'
               '「合約負債」OK = YoY > 20% 且連 2 季增。')

    # ── Stage 2：籌碼 + 技術 ──────────────────────────────────
    st.markdown('#### ⚡ Stage 2：籌碼與技術面鎖定（發動訊號）')
    _s2_df = pd.DataFrame([{
        '代號':       r['ticker'],
        'MA20 站穩':  r['ma20_label'],
        'MACD 翻紅':  r['macd_label'],
        'KD 黃叉':    r['kd_label'],
        '布林開口':   r['boll_label'],
        '投信買超':   r['inst_label'],
        '大戶持股':   r['major_label'],
        'S2 通過':    f"{r['s2_pass_cnt']}/6",
    } for r in results])
    st.dataframe(_s2_df, hide_index=True, use_container_width=True)
    st.caption('💡 S1 ≥ 5/9 且 S2 ≥ 3/6 → 進入 Stage 3 AI 重點分析。'
               '「布林開口」= 近 5 日 band 寬度 > 前 20 日 1.3 倍；'
               '「投信買超」= 近 5 日連續買超；「大戶持股」= ≥1000 張級距近 2 週比例增加。')

    # ── 通過清單（門檻：S1 ≥ 5/9 & S2 ≥ 3/6）─────────────────
    _qualified = [r for r in results if r['s1_pass_cnt'] >= 5 and r['s2_pass_cnt'] >= 3]
    if _qualified:
        st.success(f'✅ 通過兩階段濾網：{len(_qualified)} 檔 → {[r["ticker"] for r in _qualified]}')
    else:
        st.warning('⚠️ 觀察清單中沒有同時通過 Stage 1 (5/9) + Stage 2 (3/6) 的標的')

    # ── Stage 3：AI 綜合建議 ──────────────────────────────────
    st.markdown('---')
    st.markdown('#### 🧠 Stage 3：AI 綜合操作建議')
    if not gemini_fn:
        st.warning('⚠️ 未設定 GEMINI_API_KEY，無法生成 AI 建議')
        return
    if not _qualified:
        st.info('💡 無通過標的可生成 AI 建議；可嘗試擴大觀察清單或放寬條件')
        return
    if st.button('🤖 生成 AI 三型建議報告（積極 / 保守 / 止損紀律）',
                 key='picker_ai_btn', use_container_width=True, type='primary'):
        with st.spinner('AI 三型策略分析中（約 8-12 秒）...'):
            _md = _generate_ai_report(gemini_fn, _qualified, results)
        st.markdown(_md)


# ══════════════════════════════════════════════════════════════
# 主檢測函式：對單檔個股跑完所有可實作條件
# ══════════════════════════════════════════════════════════════

def _check_one_stock(ticker: str, today, yf) -> dict:
    """對單檔個股跑完 Stage 1 + Stage 2 — 失敗條件統一回灰色 ❓ 不阻斷流程。"""
    _r = {
        'ticker': ticker,
        'note':   '',
        # Stage 1 labels (9 條件)
        'debt_ratio_label':   '❓ N/A',
        'three_rate_label':   '❓ N/A',
        'div_5y_label':       '❓ N/A',
        'pe_zone_label':      '❓ N/A',
        'ar_turnover_label':  '❓ N/A',
        'inv_turnover_label': '❓ N/A',
        'capex_label':        '❓ N/A',
        'book_value_label':   '❓ N/A',
        'contract_liab_label':'❓ N/A',
        's1_pass_cnt':        0,
        # Stage 2 labels (6 條件)
        'ma20_label':         '❓ N/A',
        'macd_label':         '❓ N/A',
        'kd_label':           '❓ N/A',
        'boll_label':         '❓ N/A',
        'inst_label':         '❓ N/A',
        'major_label':        '❓ N/A',
        's2_pass_cnt':        0,
    }
    # ── 抓 K 線（yfinance + .TW / .TWO 雙後綴重試）──
    _df = None
    for _sfx in ('.TW', '.TWO'):
        try:
            _t_yf = yf.Ticker(f'{ticker}{_sfx}')
            _df_tmp = _t_yf.history(period='1y')
            if _df_tmp is not None and not _df_tmp.empty and len(_df_tmp) >= 60:
                _df = _df_tmp
                break
        except Exception:
            continue
    if _df is None:
        _r['ma20_label'] = '❌ 抓不到 K 線'
        _r['macd_label'] = '❌ 抓不到 K 線'
        _r['kd_label'] = '❌ 抓不到 K 線'
        _r['boll_label'] = '❌ 抓不到 K 線'
        return _r

    # ── 一次抓財報（多個 Stage 1 helpers 共用）──────────────
    _fs = _fetch_fs_safe(ticker)
    _qis = _fetch_quarterly_is(ticker)   # 多季損益表（三率三升 + PE TTM 共用）

    # ── Stage 1 條件 ──────────────────────────────────────────
    _r['debt_ratio_label']  = _check_debt_ratio(_fs)
    _r['three_rate_label']  = _check_three_rate_growth(_qis)
    _r['div_5y_label']      = _check_dividend_5y(_df, _t_yf)
    _r['pe_zone_label']     = _check_pe_zone(_qis, _df)
    _r['ar_turnover_label'] = _check_ar_turnover(_fs)
    _r['inv_turnover_label']= _check_inventory_turnover(_fs)
    _r['capex_label']       = _check_capex_vs_equity(_fs)
    _r['book_value_label']    = _check_book_value(_fs, _df)
    _r['contract_liab_label'] = _check_contract_liab_yoy(ticker)
    _r['s1_pass_cnt'] = sum(1 for k in (
        'debt_ratio_label', 'three_rate_label', 'div_5y_label', 'pe_zone_label',
        'ar_turnover_label', 'inv_turnover_label', 'capex_label', 'book_value_label',
        'contract_liab_label',
    ) if _r[k].startswith('✅'))

    # ── Stage 2 條件 ──────────────────────────────────────────
    _r['ma20_label']  = _check_ma20_uptrend(_df)
    _r['macd_label']  = _check_macd_bullish(_df)
    _r['kd_label']    = _check_kd_golden_cross(_df)
    _r['boll_label']  = _check_bollinger_opening(_df)
    _r['inst_label']  = _check_institutional_buying(ticker)
    _r['major_label'] = _check_major_holders(ticker)
    _r['s2_pass_cnt'] = sum(1 for k in ('ma20_label', 'macd_label', 'kd_label',
                                          'boll_label', 'inst_label', 'major_label')
                              if _r[k].startswith('✅'))
    return _r


def _fetch_fs_safe(stock_id: str) -> dict:
    """安全包裝 data_loader.fetch_financial_statements。失敗回 {}。"""
    try:
        from data_loader import fetch_financial_statements
        _r = fetch_financial_statements(stock_id)
        return _r if isinstance(_r, dict) and 'error' not in _r else {}
    except Exception as e:
        print(f'[picker/fs] {stock_id}: {type(e).__name__}: {e}')
        return {}


# ══════════════════════════════════════════════════════════════
# Stage 1 純函式（基本面）
# ══════════════════════════════════════════════════════════════

def _check_debt_ratio(fs: dict) -> str:
    """負債比 < 50%（金融股例外，但本版簡化不分業）。"""
    if not fs:
        return '❓ 無財報'
    _ratio = fs.get('負債比率(%)')
    if _ratio is None:
        return '❓ N/A'
    try:
        _v = float(_ratio)
    except (TypeError, ValueError):
        return '❓ N/A'
    if fs.get('is_finance'):
        return f'⚠️ 金融股 {_v:.1f}%'
    return f'✅ {_v:.1f}%' if _v < 50 else f'❌ {_v:.1f}%'


def _fetch_quarterly_is(stock_id: str) -> dict:
    """抓 FinMind 近 8 季損益表 → {date: {type: value}}（多 helper 共用，避免重複打 API）。

    回傳 dict（含 '_dates' key 為由近到遠排序的日期 list）；失敗回 {}。
    """
    import os as _os_q
    import datetime as _dt_q
    import requests as _rq_q
    try:
        _tok = _os_q.environ.get('FINMIND_TOKEN', '')
        _start = (_dt_q.date.today() - _dt_q.timedelta(days=900)).strftime('%Y-%m-%d')
        _p = {'dataset': 'TaiwanStockFinancialStatements',
              'data_id': stock_id, 'start_date': _start}
        if _tok:
            _p['token'] = _tok
        _r = _rq_q.get('https://api.finmindtrade.com/api/v4/data',
                       params=_p, timeout=15)
        _data = _r.json().get('data', []) if _r.status_code == 200 else []
        if not _data:
            return {}
        _quarters: dict = {}
        for _row in _data:
            _d = _row.get('date', '')
            _t = _row.get('type', '')
            try:
                _v = float(str(_row.get('value', 0) or 0).replace(',', ''))
            except (TypeError, ValueError):
                continue
            _quarters.setdefault(_d, {})[_t] = _v
        _quarters['_dates'] = sorted([d for d in _quarters if d != '_dates'], reverse=True)
        return _quarters
    except Exception as _e:
        print(f'[picker/is] {stock_id}: {type(_e).__name__}: {_e}')
        return {}


def _check_three_rate_growth(qis: dict) -> str:
    """三率三升：毛利率 / 營益率 / 淨利率近季 YoY 同步成長（用共用 _fetch_quarterly_is 結果）。"""
    if not qis:
        return '❓ FinMind 無資料'
    _dates = qis.get('_dates', [])
    if len(_dates) < 5:
        return f'❓ 僅 {len(_dates)} 季'
    _lat, _yoy = qis[_dates[0]], qis[_dates[4]]

    def _margin(slot, num_keys, denom='Revenue'):
        _r = slot.get(denom, 0)
        if _r <= 0:
            return None
        _n = sum(slot.get(k, 0) for k in num_keys)
        return _n / _r * 100 if _r else None

    _now_gm = _margin(_lat, ['GrossProfit', 'GrossProfitLoss'])
    _yoy_gm = _margin(_yoy, ['GrossProfit', 'GrossProfitLoss'])
    _now_om = _margin(_lat, ['OperatingIncome', 'OperatingIncomeLoss'])
    _yoy_om = _margin(_yoy, ['OperatingIncome', 'OperatingIncomeLoss'])
    _now_nm = _margin(_lat, ['IncomeAfterTaxes', 'NetIncome', 'ProfitAfterTax'])
    _yoy_nm = _margin(_yoy, ['IncomeAfterTaxes', 'NetIncome', 'ProfitAfterTax'])
    _pairs = [(_now_gm, _yoy_gm), (_now_om, _yoy_om), (_now_nm, _yoy_nm)]
    _valid = [(n, y) for n, y in _pairs if n is not None and y is not None]
    if not _valid:
        return '❓ 利潤欄位缺'
    _ups = sum(1 for n, y in _valid if n > y)
    return f'✅ {_ups}/3 升' if _ups == 3 else f'❌ {_ups}/3 升'



def _check_dividend_5y(df, yf_ticker) -> str:
    """連續 5 年配息 + 平均殖利率 > 7%。"""
    try:
        _divs = yf_ticker.dividends
        if _divs is None or _divs.empty or len(_divs) < 5:
            return '❌ 配息 <5 次'
        # 年度化 — 最近 5 年除息總額
        import pandas as _pd_d
        _divs.index = _pd_d.to_datetime(_divs.index)
        try:
            _divs.index = _divs.index.tz_localize(None)
        except Exception:
            pass
        _last5y = _divs.last('5Y') if hasattr(_divs, 'last') else _divs.tail(5)
        # 5 年平均年配
        _avg_annual_div = _last5y.sum() / 5 if len(_last5y) > 0 else 0
        _cur_price = float(df['Close'].iloc[-1])
        _yield_pct = (_avg_annual_div / _cur_price * 100) if _cur_price > 0 else 0
        if len(_divs.last('5Y') if hasattr(_divs, 'last') else _divs) >= 5 and _yield_pct > 7:
            return f'✅ {_yield_pct:.2f}%'
        elif _yield_pct > 0:
            return f'❌ {_yield_pct:.2f}%'
        else:
            return '❌ 無配息'
    except Exception as _e:
        return f'❓ {type(_e).__name__}'


def _check_pe_zone(qis: dict, df) -> str:
    """PE 河流圖區間 — 用真正 TTM EPS（近 4 季 EPS 加總），三分位判讀便宜/合理/昂貴。

    回退：若多季 IS 不足 4 季，無法算真 TTM → 回 ❓（不再用單季 ×4 粗估誤判）。
    """
    if not qis:
        return '❓ 無財報'
    _dates = qis.get('_dates', [])
    if len(_dates) < 4:
        return f'❓ EPS 僅 {len(_dates)} 季'
    try:
        # TTM EPS = 近 4 季 EPS 加總
        _eps_ttm = 0.0
        _found = 0
        for _d in _dates[:4]:
            _slot = qis[_d]
            _eps_q = _slot.get('EPS')
            if _eps_q is None:
                continue
            _eps_ttm += float(_eps_q)
            _found += 1
        if _found < 4:
            return f'❓ EPS 缺 {4 - _found} 季'
        if _eps_ttm <= 0:
            return '⚠️ 虧損股'
        _cur = float(df['Close'].iloc[-1])
        _pe = _cur / _eps_ttm
        if _pe < 10:
            return f'✅ 便宜 {_pe:.1f}'
        elif _pe < 15:
            return f'✅ 合理 {_pe:.1f}'
        elif _pe < 20:
            return f'❌ 昂貴 {_pe:.1f}'
        else:
            return f'❌ 超昂貴 {_pe:.1f}'
    except (TypeError, ValueError, ZeroDivisionError) as _e:
        return f'❓ {type(_e).__name__}'


def _check_ar_turnover(fs: dict) -> str:
    """應收周轉天數穩定（季增率 < 30% 變化視為穩定）。"""
    if not fs:
        return '❓ 無財報'
    _days = fs.get('應收帳款天數')
    _chg = fs.get('應收帳款季增率(%)')
    if _days is None:
        return '❓ N/A'
    try:
        _d = float(_days)
        # 季增率 None or 在 ±30% 內 視為穩定
        _stable = _chg is None or abs(float(_chg)) < 30
        return f'✅ {_d:.0f}天' if _stable else f'❌ {_d:.0f}天 季變{_chg:+.0f}%'
    except (TypeError, ValueError):
        return '❓ N/A'


def _check_inventory_turnover(fs: dict) -> str:
    """存貨周轉率 = COGS / 平均存貨（年化） — 近季未異常下滑（>4 OK）。"""
    if not fs:
        return '❓ 無財報'
    _cogs = fs.get('營業成本(千)') or 0
    _inv = fs.get('存貨(千)') or 0
    _inv_p = fs.get('存貨前期(千)') or 0
    if _inv <= 0 and _inv_p <= 0:
        return '⚠️ 無存貨（金融/服務業）'
    try:
        _avg_inv = (float(_inv) + float(_inv_p)) / 2 if (_inv_p > 0) else float(_inv)
        if _avg_inv <= 0:
            return '❓ 存貨=0'
        _turnover = (float(_cogs) * 4) / _avg_inv   # 年化
        return f'✅ {_turnover:.1f}次/年' if _turnover > 4 else f'❌ {_turnover:.1f}次/年'
    except (TypeError, ValueError, ZeroDivisionError):
        return '❓ N/A'


def _check_capex_vs_equity(fs: dict) -> str:
    """資本支出積極（近一季 CapEx > 股東權益 0.05 倍 → 年化約 0.2，視為積極擴廠）。

    註：原 prompt 寫「資本支出 > 股本 0.8 倍」，但「股本」未在 fetch_fin 出，改用「股東權益」
    更穩定的 proxy；閾值校正為單季 0.05 ≈ 年化 0.2。
    """
    if not fs:
        return '❓ 無財報'
    _capex = fs.get('資本支出(千)') or 0
    _equity = fs.get('股東權益(千)') or 0
    if _equity <= 0:
        return '❓ N/A'
    try:
        _ratio = abs(float(_capex)) / float(_equity)
        return f'✅ {_ratio*100:.1f}%/權益' if _ratio > 0.05 else f'❌ {_ratio*100:.1f}%/權益'
    except (TypeError, ValueError, ZeroDivisionError):
        return '❓ N/A'


def _check_book_value(fs: dict, df) -> str:
    """簡化清算價值：(流動資產 - 總負債) > 0 視為股東有淨清算保護。

    完整清算價值需流通股數，本版用「淨流動資產為正」判讀。
    """
    if not fs:
        return '❓ 無財報'
    _ca = fs.get('流動資產(千)') or 0
    _liab = fs.get('總負債(千)') or 0
    if _ca <= 0:
        return '❓ N/A'
    try:
        # fs 值單位為「千元」→ 換算億元：千 / 1e5
        _ncw_yi = (float(_ca) - float(_liab)) / 1e5
        if _ncw_yi > 0:
            return f'✅ 淨流動 +{_ncw_yi:,.0f}億'
        else:
            return f'❌ 淨流動 {_ncw_yi:,.0f}億'
    except (TypeError, ValueError):
        return '❓ N/A'


def _check_contract_liab_yoy(stock_id: str) -> str:
    """合約負債 YoY > 20% + 近兩季季增（在手訂單成長指標）。"""
    try:
        import os as _os_cl
        import datetime as _dt_cl
        import requests as _rq_cl
        _tok = _os_cl.environ.get('FINMIND_TOKEN', '')
        _start = (_dt_cl.date.today() - _dt_cl.timedelta(days=900)).strftime('%Y-%m-%d')
        _p = {'dataset': 'TaiwanStockBalanceSheet',
              'data_id': stock_id, 'start_date': _start}
        if _tok:
            _p['token'] = _tok
        _r = _rq_cl.get('https://api.finmindtrade.com/api/v4/data',
                         params=_p, timeout=15)
        _data = _r.json().get('data', []) if _r.status_code == 200 else []
        if not _data:
            return '❓ FinMind 無 BS'
        # 合約負債別名（含「－流動」「－非流動」需 sum）
        _aliases = ('合約負債', '合約負債－流動', '合約負債－非流動',
                    '預收款項', '遞延收入', 'ContractLiability', 'ContractLiabilities')
        _quarters: dict = {}  # date → 合約負債 sum
        for _row in _data:
            _t = str(_row.get('type', ''))
            _name = str(_row.get('origin_name', ''))
            if not any(a in _t or a in _name for a in _aliases):
                continue
            try:
                _v = float(str(_row.get('value', 0) or 0).replace(',', ''))
            except (TypeError, ValueError):
                continue
            if _v <= 0:
                continue
            _d = _row.get('date', '')
            _quarters[_d] = _quarters.get(_d, 0) + _v
        _dates = sorted(_quarters.keys(), reverse=True)
        if len(_dates) < 5:
            return f'❓ {len(_dates)}季 不足'
        _now = _quarters[_dates[0]]
        _yoy = _quarters[_dates[4]]
        _prev = _quarters[_dates[1]]
        _prev2 = _quarters[_dates[2]] if len(_dates) > 2 else 0
        _yoy_pct = (_now - _yoy) / _yoy * 100 if _yoy > 0 else 0
        _qoq_2 = _now > _prev > _prev2  # 連兩季季增
        if _yoy_pct > 20 and _qoq_2:
            return f'✅ YoY+{_yoy_pct:.0f}% 連2季增'
        if _yoy_pct > 20:
            return f'⚠️ YoY+{_yoy_pct:.0f}% 季未連增'
        return f'❌ YoY{_yoy_pct:+.0f}%'
    except Exception as _e:
        return f'❓ {type(_e).__name__}'


# ══════════════════════════════════════════════════════════════
# Stage 2 純函式（籌碼 + 技術）
# ══════════════════════════════════════════════════════════════

def _check_ma20_uptrend(df) -> str:
    """股價 > MA20 且 MA20 翻揚（近 5 日 MA20 斜率為正）。"""
    try:
        _ma20 = df['Close'].rolling(20).mean()
        if len(_ma20.dropna()) < 5:
            return '❓ 不足 25 日'
        _cur = float(df['Close'].iloc[-1])
        _ma20_now = float(_ma20.iloc[-1])
        _ma20_5d_ago = float(_ma20.iloc[-6])
        _above = _cur > _ma20_now
        _rising = _ma20_now > _ma20_5d_ago
        if _above and _rising:
            return '✅ 站穩翻揚'
        elif _above:
            return '⚠️ 站穩未翻揚'
        else:
            return '❌ 跌破'
    except Exception as _e:
        return f'❓ {type(_e).__name__}'


def _check_macd_bullish(df) -> str:
    """MACD 綠轉紅（DIF-DEA 由負轉正）or 柱狀體由收斂轉發散。"""
    try:
        _close = df['Close']
        _ema12 = _close.ewm(span=12).mean()
        _ema26 = _close.ewm(span=26).mean()
        _dif   = _ema12 - _ema26
        _dea   = _dif.ewm(span=9).mean()
        _macd  = _dif - _dea
        if len(_macd.dropna()) < 3:
            return '❓ 不足 30 日'
        _now = float(_macd.iloc[-1])
        _prev = float(_macd.iloc[-2])
        _prev2 = float(_macd.iloc[-3])
        # 綠轉紅：前一日負今日正
        if _prev < 0 and _now > 0:
            return '✅ 綠轉紅'
        # 柱狀體放大（已紅且擴大）
        if _now > 0 and _now > _prev > _prev2:
            return '✅ 柱狀放大'
        if _now > 0:
            return '⚠️ 紅但收斂'
        return '❌ 仍綠'
    except Exception as _e:
        return f'❓ {type(_e).__name__}'


def _check_bollinger_opening(df) -> str:
    """布林通道剛開口（band 寬度近 5 日均值 > 前 20 日均值 1.3 倍 → 突破前的瘦窄轉放大）。

    註：tech_indicators.calc_bollinger 只回最後一日純量 dict，無法算寬度時序，
    故此處自行 rolling 計算整段 band-width series。
    """
    try:
        _close = df['Close']
        if len(_close.dropna()) < 25:
            return '❓ 不足 25 日'
        _ma = _close.rolling(20).mean()
        _std = _close.rolling(20).std()
        _width = (_ma + 2 * _std - (_ma - 2 * _std)) / _ma  # = 4*std/ma 標準化寬度
        _width = _width.dropna()
        if len(_width) < 25:
            return '❓ 不足 25 日'
        _recent = _width.iloc[-5:].mean()
        _baseline = _width.iloc[-25:-5].mean()
        if _baseline <= 0:
            return '❓ baseline=0'
        _ratio = _recent / _baseline
        if _ratio > 1.3:
            return f'✅ 開口 ×{_ratio:.2f}'
        elif _ratio > 1.0:
            return f'⚠️ 微擴 ×{_ratio:.2f}'
        else:
            return f'❌ 收斂 ×{_ratio:.2f}'
    except Exception as _e:
        return f'❓ {type(_e).__name__}'


def _check_kd_golden_cross(df) -> str:
    """KD 低檔（K<20）黃金交叉。

    註：tech_indicators.calc_kd 只回最後一日純量 (k, d)，無法判斷「昨日 K<D 今日 K>D」
    的交叉，故此處自行算 K/D series。
    """
    try:
        if len(df) < 11:
            return '❓ 不足 9 日'
        _low_n = df['Low'].rolling(9).min()
        _high_n = df['High'].rolling(9).max()
        _rsv = ((df['Close'] - _low_n) / (_high_n - _low_n).replace(0, 1)) * 100
        _k = _rsv.ewm(com=2, adjust=False).mean()
        _d = _k.ewm(com=2, adjust=False).mean()
        _k = _k.dropna()
        _d = _d.dropna()
        if len(_k) < 2 or len(_d) < 2:
            return '❓ 不足 9 日'
        _k_now, _d_now = float(_k.iloc[-1]), float(_d.iloc[-1])
        _k_prev, _d_prev = float(_k.iloc[-2]), float(_d.iloc[-2])
        _golden = _k_prev < _d_prev and _k_now > _d_now
        if _golden and _k_now < 20:
            return f'✅ 低檔黃叉 K={_k_now:.1f}'
        if _golden:
            return f'⚠️ 黃叉 K={_k_now:.1f}'
        if _k_now > 80:
            return f'⚠️ 高檔 K={_k_now:.1f}'
        return f'❌ K={_k_now:.1f}'
    except Exception as _e:
        return f'❓ {type(_e).__name__}'


def _check_institutional_buying(stock_id: str) -> str:
    """投信近 5 個交易日連續買超（buy > sell）。"""
    try:
        import os as _os_in
        import datetime as _dt_in
        import requests as _rq_in
        _tok = _os_in.environ.get('FINMIND_TOKEN', '')
        _start = (_dt_in.date.today() - _dt_in.timedelta(days=20)).strftime('%Y-%m-%d')
        _p = {'dataset': 'TaiwanStockInstitutionalInvestorsBuySell',
              'data_id': stock_id, 'start_date': _start}
        if _tok:
            _p['token'] = _tok
        _r = _rq_in.get('https://api.finmindtrade.com/api/v4/data',
                         params=_p, timeout=15)
        _data = _r.json().get('data', []) if _r.status_code == 200 else []
        if not _data:
            return '❓ FinMind 無法人'
        # 過濾投信（Investment_Trust）每日 buy/sell
        _by_date: dict = {}
        for _row in _data:
            _name = str(_row.get('name', ''))
            if 'Investment_Trust' not in _name and '投信' not in _name:
                continue
            _d = _row.get('date', '')
            try:
                _buy = float(_row.get('buy', 0) or 0)
                _sell = float(_row.get('sell', 0) or 0)
            except (TypeError, ValueError):
                continue
            _by_date[_d] = _buy - _sell
        if not _by_date:
            return '❓ 無投信資料'
        _dates = sorted(_by_date.keys(), reverse=True)[:5]
        if len(_dates) < 5:
            return f'❓ 僅 {len(_dates)} 日'
        _pos = sum(1 for d in _dates if _by_date[d] > 0)
        if _pos == 5:
            return '✅ 連5日買超'
        if _pos >= 3:
            return f'⚠️ {_pos}/5 日買超'
        return f'❌ {_pos}/5 日買超'
    except Exception as _e:
        return f'❓ {type(_e).__name__}'


def _check_major_holders(stock_id: str) -> str:
    """大戶（≥1000 張 / 400 張級距）持股比例近 2 週增加（集保股權分散表）。

    FinMind dataset 欄位可能因版本而異 — 動態偵測 level / percent 欄位名；
    無資料時回 ⚠️（多為 FinMind 免費 token 不含此 premium 資料集，非錯誤）。
    """
    try:
        import os as _os_mh
        import datetime as _dt_mh
        import requests as _rq_mh
        _tok = _os_mh.environ.get('FINMIND_TOKEN', '')
        _start = (_dt_mh.date.today() - _dt_mh.timedelta(days=60)).strftime('%Y-%m-%d')
        _p = {'dataset': 'TaiwanStockHoldingSharesPer',
              'data_id': stock_id, 'start_date': _start}
        if _tok:
            _p['token'] = _tok
        _r = _rq_mh.get('https://api.finmindtrade.com/api/v4/data',
                         params=_p, timeout=15)
        _j = _r.json() if _r.status_code == 200 else {}
        _data = _j.get('data', [])
        if not _data:
            # 區分：premium 限制 vs 真無資料
            _msg = str(_j.get('msg', '')).lower()
            if 'limit' in _msg or 'permission' in _msg or 'sponsor' in _msg:
                return '⚠️ 需付費 token'
            return '⚠️ 集保無資料'
        # 動態找欄位名
        _sample = _data[0]
        _level_key = next((k for k in _sample
                           if 'level' in k.lower() or 'class' in k.lower() or '分級' in k), None)
        _pct_key = next((k for k in _sample
                         if 'percent' in k.lower() or 'ratio' in k.lower() or '比例' in k), None)
        if _level_key is None or _pct_key is None:
            return '❓ 欄位不符'
        # 鎖定大戶級距：含「1,000,001」「400,001」「以上」或數字級距 ≥ 14
        _by_date: dict = {}
        for _row in _data:
            _cls = str(_row.get(_level_key, ''))
            _is_major = ('1,000,001' in _cls or '400,001' in _cls or '以上' in _cls
                         or _cls in ('14', '15', '16', '17'))
            if not _is_major:
                continue
            _d = _row.get('date', '')
            try:
                _pct = float(_row.get(_pct_key, 0) or 0)
            except (TypeError, ValueError):
                continue
            _by_date[_d] = max(_by_date.get(_d, 0), _pct)
        if len(_by_date) < 2:
            return '⚠️ 大戶級距資料不足'
        _dates = sorted(_by_date.keys(), reverse=True)
        _now = _by_date[_dates[0]]
        _ago = _by_date[_dates[min(2, len(_dates) - 1)]]
        _chg = _now - _ago
        if _chg > 0.1:
            return f'✅ 大戶+{_chg:.2f}%'
        if _chg > -0.1:
            return f'⚠️ 持平 {_chg:+.2f}%'
        return f'❌ 大戶{_chg:+.2f}%'
    except Exception as _e:
        return f'❓ {type(_e).__name__}'


# ══════════════════════════════════════════════════════════════
# Stage 3 — Gemini AI 三型建議報告
# ══════════════════════════════════════════════════════════════

def _generate_ai_report(gemini_fn, qualified: list[dict], all_results: list[dict]) -> str:
    """生成 Markdown 戰情報告：積極型 / 保守型 / 止損紀律。"""
    _lines = ['以下為通過二階段濾網的候選個股清單，請依「積極型 / 保守型 / 止損紀律」三型給出操作建議：\n']
    for r in qualified:
        _lines.append(
            f'- **{r["ticker"]} {r.get("note","")}**：'
            f'S1=`{r["s1_pass_cnt"]}/4`（債{r["debt_ratio_label"]} · 三率{r["three_rate_label"]} '
            f'· 5Y配息{r["div_5y_label"]} · PE{r["pe_zone_label"]}）'
            f' / S2=`{r["s2_pass_cnt"]}/3`（MA20{r["ma20_label"]} · MACD{r["macd_label"]} · KD{r["kd_label"]}）'
        )
    _prompt = (
        '你是一位擁有 20 年台股經驗的「台股AI戰情室」首席策略師。'
        '依下方候選名單，輸出 Markdown 結構戰情報告：\n\n'
        + '\n'.join(_lines)
        + '\n\n請依以下結構回覆：\n\n'
        '## 🎯 三階段選股建議\n\n'
        '### 🔥 積極型投資人優先佈局\n'
        '（選 1-2 檔，說明技術面表態 + 短期催化劑）\n\n'
        '### 🛡️ 保守型存股族防禦配置\n'
        '（選 1-2 檔，說明價值安全邊際 + 殖利率支撐）\n\n'
        '### ⚠️ 限制與風險提醒\n'
        '（每檔的潛在風險：景氣循環 / 老闆畫餅 / 客戶集中等）\n\n'
        '### 📉 止損紀律建議\n'
        '（建議跌破月線出場 or 虧損 15% 出場 + 加碼條件）\n\n'
        '請務必包含上述四個章節，每項分析含具體理由。'
    )
    try:
        _r = gemini_fn(_prompt)
        return _r if _r else '⚠️ AI 回傳為空，請確認 GEMINI_API_KEY'
    except Exception as e:
        return f'❌ AI 生成失敗：{type(e).__name__}: {e}'
