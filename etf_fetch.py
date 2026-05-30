"""
ETF 抓取層（fetch layer）
從 etf_dashboard.py 抽出的純 I/O 函式：價格 / 配息 / 基本資訊 / 費用率 / NAV / 類股漲跌
無內部依賴；可被 etf_calc、etf_render、tab_* 模組安全 import。
"""
import streamlit as st
import pandas as pd
import yfinance as yf


def _fetch_news_for(ticker: str, name: str = "", n: int = 4) -> str:
    """抓取個股/ETF 相關新聞，回傳格式化字串。失敗時回傳空字串。
    走 NAS 中繼站 → Squid proxy(帶 CONSENT cookie 繞 Google 同意頁) → 直連。"""
    try:
        import feedparser as _fp
        import html as _h
        from urllib.parse import quote as _uq
    except ImportError:
        return ""
    try:
        from proxy_helper import fetch_url as _furl, nas_relay_fetch as _nasf
    except ImportError:
        _furl = _nasf = None
    _feeds = [
        f'https://news.google.com/rss/search?q={_uq(f"{ticker} {name}".strip())}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant',
        f'https://news.google.com/rss/search?q={_uq(f"Taiwan ETF {ticker}".strip())}&hl=en-US&gl=US&ceid=US:en',
    ]
    _hdr = {'Cookie': 'CONSENT=YES+cb; SOCS=CAI',
            'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.5'}
    _out = []
    for _url in _feeds:
        try:
            _fd = None
            if _nasf is not None:
                _rr = _nasf(_url, timeout=15)
                if _rr is not None:
                    _fd = _fp.parse(_rr.content)  # 餵 bytes（避免 str+encoding 宣告被拒解析）
            if (_fd is None or not getattr(_fd, 'entries', None)) and _furl is not None:
                _rs = _furl(_url, headers=_hdr, timeout=10)
                if _rs is not None:
                    _fd = _fp.parse(_rs.content)
            if _fd is None or not getattr(_fd, 'entries', None):
                _fd = _fp.parse(_url, request_headers=_hdr)
            for _e in _fd.entries:
                _t = _h.unescape(_e.get('title', '')).strip()
                _p = str(_e.get('published', ''))[:10]
                if _t:
                    _out.append(f'- {_t}（{_p}）')
                if len(_out) >= n:
                    break
        except Exception:
            pass
        if len(_out) >= n:
            break
    return '\n'.join(_out[:n]) if _out else '（暫無相關新聞）'


# ── MK 規格 條件 B：台灣 ETF 發行價對照表（用於破發檢測）──────
# 台灣常見 ETF 發行價（多為 10/15/20/30/40 元）；債券 ETF 多為 40 元
_TW_ETF_LAUNCH_PRICE = {
    '0050': 36.98, '0051': 25.57, '0052': 36.99, '0053': 22.20,
    '0055': 12.95, '0056': 25.20, '0057': 38.10,
    '006203': 25, '006204': 30, '006208': 30, '00646': 20,
    '00692': 20, '00701': 20, '00713': 20, '00730': 20,
    '00731': 20, '00733': 20, '00735': 20, '00850': 20,
    '00878': 15, '00881': 15, '00882': 15, '00891': 15,
    '00892': 15, '00893': 15, '00895': 15, '00896': 15,
    '00897': 15, '00898': 15, '00899': 15, '00900': 15,
    '00901': 15, '00902': 15, '00903': 15, '00904': 15,
    '00905': 15, '00907': 15, '00910': 15, '00911': 15,
    '00912': 15, '00913': 15, '00915': 15, '00916': 15,
    '00918': 15, '00919': 20, '00920': 15, '00921': 15,
    '00922': 15, '00923': 15, '00924': 15, '00925': 15,
    '00927': 15, '00929': 15, '00930': 15, '00932': 15,
    '00934': 10, '00935': 10, '00936': 10, '00939': 15,
    '00940': 10, '00941': 10, '00942B': 15, '00943': 15,
    '00944': 10, '00945B': 15, '00946': 10, '00947': 10,
    # 債券 ETF 多為 40 元起始
    '00679B': 40, '00687B': 40, '00696B': 40, '00697B': 40,
    '00710B': 40, '00711B': 40, '00712':  20, '00714':  30,
    '00718B': 40, '00719B': 40, '00720B': 40, '00721B': 40,
    '00722B': 40, '00723B': 40, '00724B': 40, '00725B': 40,
    '00726B': 40, '00727B': 40, '00772B': 40, '00773B': 40,
    '00777B': 40, '00778B': 40, '00779B': 40, '00780B': 40,
    '00781B': 40, '00782B': 40, '00783B': 40, '00784B': 40,
    '00785B': 40, '00786B': 40, '00787B': 40, '00788B': 40,
    '00795B': 40, '00834B': 40, '00836B': 40, '00837B': 40,
    '00840B': 40, '00845B': 40, '00846B': 40, '00847B': 40,
    '00848B': 40, '00849B': 40, '00853B': 40, '00857B': 40,
    '00859B': 40, '00860B': 40, '00862B': 40, '00863B': 40,
    '00864B': 40, '00865B': 40, '00867B': 40, '00870B': 40,
    '00883B': 40, '00890B': 40, '00937B': 40,
}


def _get_etf_launch_price(ticker: str, df: "pd.DataFrame|None" = None):
    """取得 ETF 發行價（用於 MK 規格條件 B 破發檢測）。

    優先序：
    1. 內建台灣 ETF 對照表（最精準）
    2. df 首個交易日收盤價（已還原權息，僅供 fallback 估算）

    Returns
    -------
    float | None
    """
    _code = (ticker or '').replace('.TWO', '').replace('.TW', '').upper().strip()
    _v = _TW_ETF_LAUNCH_PRICE.get(_code)
    if _v is not None:
        return float(_v)
    # fallback：用 df 第一筆收盤估算（僅當美股 ETF / 未收錄者）
    try:
        if df is not None and len(df) > 0:
            return float(df['Close'].iloc[0])
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600, max_entries=10)
def fetch_etf_price(ticker: str, period: str = '5y') -> pd.DataFrame:
    """取得 ETF 歷史價格（auto_adjust=True 還原權息）"""
    try:
        df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df.ffill()
    except Exception as e:
        st.error(f'❌ 無法取得 {ticker} 價格：{e}')
        return pd.DataFrame()


@st.cache_data(ttl=3600, max_entries=10)
def fetch_etf_dividends(ticker: str) -> pd.Series:
    """取得 ETF 歷史配息"""
    try:
        divs = yf.Ticker(ticker).dividends
        if divs.empty:
            return pd.Series(dtype=float)
        divs.index = pd.to_datetime(divs.index).tz_localize(None)
        return divs
    except Exception:
        return pd.Series(dtype=float)


@st.cache_data(ttl=3600, max_entries=10)
def fetch_etf_info(ticker: str) -> dict:
    """取得 ETF 基本資訊（費用率/Beta/AUM）"""
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


def fetch_sitca_expense_ratio(ticker: str, *, attempts: int = 1):
    """從 SITCA 投信投顧公會抓台股 ETF 內扣費用率（Primary，海外 IP 走 NAS proxy）。

    URL: https://www.sitca.org.tw/ROC/Industry/IN2211.aspx?pid=IN2222_01

    Returns
    -------
    float | None  比例形式（0.0036 = 0.36%）；找不到 ticker 或抓取失敗回 None。
    """
    from proxy_helper import fetch_url as _fu_sit
    import pandas as _pd_sit, re as _re_sit
    _t = (ticker or '').replace('.TW', '').replace('.tw', '').strip()
    if not _t or not _t.isdigit():
        return None  # SITCA 只收純台股 ETF 數字代號（0050、00878 等）
    try:
        r = _fu_sit(
            'https://www.sitca.org.tw/ROC/Industry/IN2211.aspx?pid=IN2222_01',
            timeout=15, attempts=attempts,
        )
        if r is None or r.status_code != 200:
            return None
        r.encoding = 'utf-8'
        # ASP.NET 頁面通常一張總費用率表；多表都試找含「代號」+「費用率」欄位的那張
        tables = _pd_sit.read_html(r.text)
        # ticker 標準化：去掉 leading 0（治 pandas 把 "0050" parse 成 int 50 的場景）
        _tn = _t.lstrip('0') or '0'
        for tbl in tables:
            # 注意：column 可能是 MultiIndex tuple，比對用 str(c)，但取值用原物件 c
            code_col = next((c for c in tbl.columns
                             if any(k in str(c) for k in ('代號', 'ETF', 'Code'))), None)
            rate_col = next((c for c in tbl.columns
                             if '費用率' in str(c) or '費用比率' in str(c)), None)
            if code_col is None or rate_col is None:
                continue
            # 雙向 leading-zero 容忍：cell 也 strip leading 0 後比對
            _digits = tbl[code_col].astype(str).str.replace(r'\D', '', regex=True)
            row = tbl[_digits.where(_digits != '', '0').str.lstrip('0').replace('', '0') == _tn]
            if row.empty:
                continue
            raw = str(row[rate_col].iloc[0])
            m = _re_sit.search(r'(\d+(?:\.\d+)?)', raw)
            if not m:
                continue
            v = float(m.group(1))
            # SITCA 表格數字常見已是百分比（0.36 = 0.36%），標準化成「比例」回傳
            print(f'[SITCA/expense] ✅ {_t} = {v}% (col={rate_col})')
            return v / 100.0
        print(f'[SITCA/expense] ⚠️ {_t} 未找到符合 column 的表格 (tables={len(tables)})')
        return None
    except Exception as e:
        print(f'[SITCA/expense] ❌ {_t}: {type(e).__name__}: {e}')
        return None


def fetch_moneydj_expense_ratio(ticker: str):
    """從 MoneyDJ ETF Basic0004 頁面抓「經理費 + 保管費」總費用率（私募/已下市 ETF 備援）。

    URL: https://www.moneydj.com/ETF/X/Basic/Basic0004.xdjhtm?etfid=XXXX.TW

    Returns
    -------
    float | None  比例形式（0.0036 = 0.36%）；找不到或抓取失敗回 None。
    """
    import re as _re_mdje
    _t = (ticker or '').replace('.tw', '.TW').strip()
    if not _t:
        return None
    # MoneyDJ etfid 通常吃 '0050.TW' 格式；純數字補 .TW
    if _t.isdigit():
        _t = f'{_t}.TW'
    _url = f'https://www.moneydj.com/ETF/X/Basic/Basic0004.xdjhtm?etfid={_t}'
    _hdrs = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8',
        'Referer': 'https://www.moneydj.com/',
    }
    try:
        # curl_cffi Chrome TLS 指紋優先；失敗降級 requests
        try:
            from curl_cffi import requests as _cffi_mdje
            _r = _cffi_mdje.get(_url, impersonate='chrome124', timeout=12)
        except Exception:
            import requests as _rq_mdje
            _r = _rq_mdje.get(_url, headers=_hdrs, timeout=12, verify=False)
        if _r.status_code != 200:
            print(f'[MoneyDJ/expense] {_t}: HTTP {_r.status_code}')
            return None
        _txt = _r.text
        # 直掃「經理費 X.XX%」與「保管費 X.XX%」合計；MoneyDJ Basic0004 表格常以 td 緊鄰呈現
        _mng = _re_mdje.search(r'經理費[^\d%]{0,30}?(\d+(?:\.\d+)?)\s*%', _txt)
        _cus = _re_mdje.search(r'保管費[^\d%]{0,30}?(\d+(?:\.\d+)?)\s*%', _txt)
        if _mng and _cus:
            _total = float(_mng.group(1)) + float(_cus.group(1))
            print(f'[MoneyDJ/expense] ✅ {_t} = {_total}% (mng={_mng.group(1)}+cus={_cus.group(1)})')
            return _total / 100.0
        # Fallback：找「總費用率 / 內含費用率」單一欄位
        _tot = _re_mdje.search(r'(?:總費用率|內含費用率|費用率)[^\d%]{0,30}?(\d+(?:\.\d+)?)\s*%', _txt)
        if _tot:
            _v = float(_tot.group(1))
            print(f'[MoneyDJ/expense] ✅ {_t} = {_v}% (總費用率欄位)')
            return _v / 100.0
        print(f'[MoneyDJ/expense] ⚠️ {_t} 頁面無「經理費/保管費/總費用率」欄位')
        return None
    except Exception as _e:
        print(f'[MoneyDJ/expense] ❌ {_t}: {type(_e).__name__}: {_e}')
        return None


def _fetch_holdings_yahoo_tw(symbol_yf: str):
    """台灣 Yahoo 股市 ETF 持股頁（國內版 Yahoo，海外 IP 可直連、繞過 MoneyDJ 403）。

    URL：https://tw.stock.yahoo.com/quote/{symbol}/holding
    symbol_yf：yfinance 格式代號（如 '00980A.TW' / '0050.TW'）。
    解析雙策略：① 頁面內嵌 JSON（名稱+權重鍵）② BeautifulSoup 表格列（中文名 + n.nn%）。
    回 {個股名稱: 權重%} 或 None（抓不到 / 解析不出）。
    """
    import re as _re_y
    try:
        from proxy_helper import fetch_url as _fu_y
    except Exception:
        return None
    _url = f'https://tw.stock.yahoo.com/quote/{symbol_yf}/holding'
    try:
        _r = _fu_y(_url, timeout=15, attempts=2)
    except Exception as _e:
        print(f'[Holdings/YahooTW] fetch 異常 {symbol_yf}: {type(_e).__name__}: {_e}')
        return None
    if _r is None or getattr(_r, 'status_code', None) != 200:
        print(f'[Holdings/YahooTW] {symbol_yf} 無回應 / 非 200')
        return None
    try:
        _r.encoding = 'utf-8'
    except Exception:
        pass
    _html = _r.text or ''
    _out = {}
    # ── 策略 A：頁面內嵌 JSON（名稱鍵 + 權重鍵就近配對）──
    for _m in _re_y.finditer(
        r'"(?:name|symbolName|holdingName|stockName)"\s*:\s*"([^"]{1,40})"'
        r'[^{}]{0,200}?"(?:weighting|holdingPercent|percent|weight|ratio)"'
        r'\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?',
        _html
    ):
        _nm = _m.group(1).strip()
        try:
            _w = float(_m.group(2))
        except ValueError:
            continue
        if _w <= 1.5:           # 小數表示（0.05）→ 轉百分比
            _w *= 100
        if _nm and not _nm.isdigit() and 0 < _w <= 100 and _nm not in _out:
            _out[_nm] = round(_w, 4)
        if len(_out) >= 60:
            break
    if _out:
        print(f'[Holdings/YahooTW] ✅(JSON) {symbol_yf} {len(_out)} 檔')
        return _out
    # ── 策略 B：表格純文字（中文股名 + n.nn% 同列）──
    try:
        from bs4 import BeautifulSoup as _BS_y
        _txt = _BS_y(_html, 'html.parser').get_text(' ', strip=True)
        for _m in _re_y.finditer(
            r'([一-鿿][一-鿿A-Za-z0-9&\.\-]{1,29})\s+'
            r'([0-9]{1,2}\.[0-9]{1,2})\s*%', _txt
        ):
            _nm = _m.group(1).strip()
            try:
                _w = float(_m.group(2))
            except ValueError:
                continue
            if (_nm and not _nm.isdigit() and 0 < _w <= 100
                    and _nm not in _out
                    and _nm not in ('持股權重', '權重', '比例', '持股比例')):
                _out[_nm] = _w
            if len(_out) >= 60:
                break
    except Exception as _eb:
        print(f'[Holdings/YahooTW] BS 解析異常 {symbol_yf}: {type(_eb).__name__}: {_eb}')
    if _out:
        print(f'[Holdings/YahooTW] ✅(HTML) {symbol_yf} {len(_out)} 檔')
        return _out
    print(f'[Holdings/YahooTW] ⚪ {symbol_yf} 頁面無可解析持股')
    return None


def _enrich_tw_holding_name(raw_name: str, symbol) -> str:
    """持股顯示成「中文名 (代碼)」。

    - symbol 形如 '2330.TW'：台股代號（4-6 碼數字，末可帶字母）→ 以
      stock_names.get_stock_name 補中文；查無中文時退回「原名 (代碼)」至少帶出代碼。
    - 海外成分股（如美股 ETF 的 AAPL）或無法判別 → 原樣回傳，不畫蛇添足。
    """
    import re as _re_n
    _code = str(symbol or '').upper().replace('.TWO', '').replace('.TW', '').strip()
    if not _re_n.fullmatch(r'\d{4,6}[A-Z]?', _code):
        return raw_name
    _zh = ''
    try:
        from stock_names import get_stock_name as _gsn
        _zh = _gsn(_code) or ''
    except Exception:
        _zh = ''
    if _zh and _re_n.search(r'[一-鿿]', _zh):
        return f'{_zh} ({_code})'
    return f'{raw_name} ({_code})'


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_etf_holdings(ticker: str):
    """抓 ETF 成份股清單（個股名稱 → 權重 %）。台股 ETF 為主，海外 ETF 走 yfinance 兜底。

    多段備援（按順序嘗試，任一成功即返回）：
      1. yfinance `.funds_data.top_holdings` — 海外 ETF 主源；台股通常 None
      1.5 台灣 Yahoo 股市 /quote/{sym}/holding — 台股 ETF 主源（海外 IP 可直連）
      2. MoneyDJ 三條 URL 並掃（備源，海外 IP 需 NAS proxy）：
         - Basic0007.xdjhtm（持股明細）
         - Basic0008.xdjhtm（投資配置）
         - RankA0001.xdjhtm（持股排名）
      3. 全失敗回 None（UI 端標 ⚪ N/A）

    Returns
    -------
    dict[str, float] | None
        key=個股名稱（中/英文），value=權重百分比（如 5.23 代表 5.23%）
        無資料 / 抓取失敗回 None。

    Cache
    -----
    TTL 86400 秒（1 日），因 ETF 成份股月度才更新。
    """
    import re as _re_h
    _t = (ticker or '').replace('.tw', '.TW').strip()
    if not _t:
        return None
    _t_yf = _t if '.' in _t else (f'{_t}.TW' if _t.isdigit() else _t)
    _t_mdj = _t_yf  # MoneyDJ etfid 同 yfinance ticker

    # ── 1. yfinance funds_data（海外 ETF 主源）──────────────────
    try:
        _yt = yf.Ticker(_t_yf)
        _fd = getattr(_yt, 'funds_data', None)
        if _fd is not None:
            _th = getattr(_fd, 'top_holdings', None)
            if _th is not None and hasattr(_th, 'iterrows') and not _th.empty:
                _out = {}
                for _idx, _row in _th.iterrows():
                    _name = str(_row.get('Name', _idx) or _idx).strip()
                    _sym  = _row.get('Symbol', _idx)  # top_holdings index 多為代號
                    _w_raw = _row.get('Holding Percent', _row.get('% of Net Assets', None))
                    if _w_raw is None or _name == '':
                        continue
                    try:
                        _w = float(_w_raw)
                    except (TypeError, ValueError):
                        continue
                    # yfinance 多以小數表示（0.05 = 5%）；> 1 視為已是百分比
                    if _w <= 1.5:
                        _w = _w * 100
                    if _w > 0:
                        _out[_enrich_tw_holding_name(_name, _sym)] = round(_w, 4)
                if _out:
                    print(f'[Holdings/yf] ✅ {_t_yf} {len(_out)} 檔')
                    return _out
    except Exception as _ey:
        print(f'[Holdings/yf] {_t_yf}: {type(_ey).__name__}: {_ey}')

    # ── 1.5 台灣 Yahoo 股市（國內版 Yahoo，台股 ETF 主源）────────
    # Yahoo CDN 海外 IP 可直連，繞過 MoneyDJ 對海外 IP 的 403 封鎖
    _yh = _fetch_holdings_yahoo_tw(_t_yf)
    if _yh:
        return _yh

    # ── 2. MoneyDJ 三條 URL 嘗試（台股 ETF 備源）────────────────
    # 走 proxy_helper（NAS Squid 台灣 IP）為主源 — MoneyDJ 反爬擋海外 IP 回 403；
    # curl_cffi 留作 fallback（本機開發或 proxy 掛掉時）
    _urls = [
        f'https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={_t_mdj}',
        f'https://www.moneydj.com/ETF/X/Basic/Basic0008.xdjhtm?etfid={_t_mdj}',
        f'https://www.moneydj.com/ETF/X/Basic/RankA0001.xdjhtm?etfid={_t_mdj}',
    ]
    for _url in _urls:
        _txt = None
        # ── 2a. proxy_helper 主源 ───
        try:
            from proxy_helper import fetch_url as _fu_h
            _r = _fu_h(_url, timeout=15, attempts=2)
            if _r is not None and _r.status_code == 200:
                _r.encoding = 'utf-8'
                _txt = _r.text
        except Exception as _eph:
            print(f'[Holdings/MDJ] proxy 異常 {_t_mdj}: {type(_eph).__name__}: {_eph}')
        # ── 2b. curl_cffi fallback ─
        if _txt is None:
            try:
                from curl_cffi import requests as _cffi_h
                _r2 = _cffi_h.get(_url, impersonate='chrome124', timeout=15)
                if _r2.status_code == 200:
                    _txt = _r2.text
                else:
                    print(f'[Holdings/MDJ] curl_cffi {_t_mdj} {_url[-30:]}: HTTP {_r2.status_code}')
            except Exception as _eh:
                print(f'[Holdings/MDJ] curl_cffi 異常 {_t_mdj} {_url[-30:]}: {type(_eh).__name__}: {_eh}')
        if _txt is None:
            continue
        # ── 寬鬆 regex 擷取：個股名（中文/英數）+ 後續百分比 ──
        try:
            _stocks = {}
            for _m in _re_h.finditer(
                r'>([一-鿿 A-Z0-9&\.\-]{2,30})</[^>]+>[^<]*<[^>]+>\s*(\d{1,2}\.\d{1,3})\s*%',
                _txt
            ):
                _nm = _m.group(1).strip()
                if (_nm and not _nm.isdigit() and not _nm.replace('.', '').isdigit()
                        and _nm not in ('持股比例', '比例', '持股比重', '權重', '個股名稱', '名稱')
                        and len(_nm) >= 2):
                    try:
                        _w = float(_m.group(2))
                        if 0 < _w <= 100 and _nm not in _stocks:
                            _stocks[_nm] = _w
                    except ValueError:
                        continue
                if len(_stocks) >= 50:
                    break
            if _stocks:
                print(f'[Holdings/MDJ] ✅ {_t_mdj} {len(_stocks)} 檔 ({_url[-30:]})')
                return _stocks
        except Exception as _eh2:
            print(f'[Holdings/MDJ] regex 異常 {_t_mdj} {_url[-30:]}: {type(_eh2).__name__}: {_eh2}')
            continue

    print(f'[Holdings] ❌ {_t} — yf/MoneyDJ 三條 URL 全失敗')
    return None


# ══════════════════════════════════════════════════════════════
# 主動式 ETF 判別 + 經理人查詢（PR — claude/etf-weakness-manager）
# ══════════════════════════════════════════════════════════════
# 主動式台股 ETF 白名單（代號末多帶字母 A/D/T；2024-2026 元大/復華/野村等募集）
# 補：純數字代號的主動式 ETF（如未來新版）需手動加進來
_ACTIVE_TW_ETF_WHITELIST = {
    # 元大主動式系列（2024 Q4 ~ 2026）
    '00980A', '00982A', '00984A', '00989A', '00992A',
    '00982T', '00980D',
    # 復華 / 國泰 / 中信 / 野村 主動式（補充清單，依公告陸續加入）
    '00981A', '00983A', '00985A', '00986A', '00987A',
    '00988A', '00990A', '00991A', '00993A', '00994A',
    '00995A', '00996A', '00997A',
}


def is_active_etf(ticker: str) -> bool:
    """判別 ETF 是主動式 (Active) 還是被動式 (Passive)。

    判別優先序：
      1. 白名單命中 → True
      2. 代號末位 = 'B' (債券型) 或 'K' (槓桿) → False（純被動）
      3. 代號末位為字母（A/D/T 等非 B/K）→ True（多為主動）
      4. 純數字代號 → False（多為被動追蹤指數，如 0050/00878/00940）
    """
    if not ticker:
        return False
    _code = str(ticker).replace('.TW', '').replace('.TWO', '').replace('.tw', '').upper().strip()
    if _code in _ACTIVE_TW_ETF_WHITELIST:
        return True
    if not _code:
        return False
    _last = _code[-1]
    if _last in ('B', 'K'):  # 債券型 / 槓桿型 = 被動追蹤
        return False
    if _last.isalpha():       # 其他字母結尾 (A/D/T) 多為主動式
        return True
    return False              # 純數字 = 被動追蹤指數


def _fetch_yuanta_active_etf_meta(ticker: str) -> dict | None:
    """元大投信官網 fallback — 抓主動式 ETF 經理人 / 費用率 / NAV。

    為何需要：MoneyDJ Basic0001/0006/0011 / SITCA 對主動式 ETF（00980A 等）
    無經理人欄位，元大投信官網才是源頭。多 URL 嘗試，HTML regex 解析。

    Returns
    -------
    dict | None
        成功：{
            'manager':   str | None,    經理人姓名
            'expense':   float | None,  總費用率（小數，0.0085 = 0.85%）
            'nav_latest': float | None, 最近一日 NAV
            'nav_date':   str | None,   NAV 日期 YYYY-MM-DD
            'source':     'yuanta-official',
            'url':        str,
        }
        失敗：None
    """
    import re as _re_y
    _code = (ticker or '').replace('.TW', '').replace('.TWO', '').strip().upper()
    if not _code or not is_active_etf(ticker):
        return None
    _urls = [
        f'https://www.yuantaetfs.com/product/detail/{_code}/profile',
        f'https://www.yuantaetfs.com/product/detail/{_code}',
        f'https://www.yuantaetfs.com/RtnPercent/Detail/{_code}',
    ]
    for _url in _urls:
        _txt = None
        try:
            from proxy_helper import fetch_url as _fu_y
            _r = _fu_y(_url, timeout=12, attempts=2)
            if _r is not None and _r.status_code == 200 and len(_r.text or '') > 500:
                _r.encoding = 'utf-8'
                _txt = _r.text
        except Exception as _ey:
            print(f'[Yuanta/{_code}] proxy 異常 {_url}: {type(_ey).__name__}: {_ey}')
            continue
        if not _txt:
            continue
        _out: dict = {'manager': None, 'expense': None,
                      'nav_latest': None, 'nav_date': None,
                      'source': 'yuanta-official', 'url': _url}
        _m = _re_y.search(
            r'(?:基金)?經理人[\s\:：]*([一-鿿]{2,8}(?:\s*[\/、，]\s*[一-鿿]{2,8})*)',
            _txt,
        )
        if _m:
            _out['manager'] = _m.group(1).strip().replace(' ', '')
        _e = _re_y.search(
            r'(?:總費用率|經理費[\s\S]{0,80}?保管費[\s\S]{0,40}?)[\s\:：]{0,5}(\d+\.\d{1,3})\s*%',
            _txt,
        )
        if _e:
            try:
                _out['expense'] = float(_e.group(1)) / 100.0
            except ValueError:
                pass
        _n = _re_y.search(
            r'(?:淨值|單位淨值|NAV)[\s\:：]*(\d+\.\d{2,4})',
            _txt,
        )
        if _n:
            try:
                _out['nav_latest'] = float(_n.group(1))
            except ValueError:
                pass
        _nd = _re_y.search(r'(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})', _txt)
        if _nd:
            try:
                from datetime import date as _date_y
                _y, _mo, _d = (int(_nd.group(i)) for i in (1, 2, 3))
                _out['nav_date'] = _date_y(_y, _mo, _d).isoformat()
            except (ValueError, OverflowError):
                pass
        if any(_out.get(k) for k in ('manager', 'expense', 'nav_latest')):
            print(f'[Yuanta/{_code}] ✅ via {_url[:60]}... '
                  f'manager={_out.get("manager")} '
                  f'expense={_out.get("expense")} '
                  f'nav={_out.get("nav_latest")}')
            return _out
    return None


@st.cache_data(ttl=604800, show_spinner=False)
def fetch_etf_manager(ticker: str):
    """從 MoneyDJ ETF 抓「現任經理人 + 任期起始日」。

    抓取策略
    --------
    多 URL 嘗試（同 proxy，不同 endpoint）：
      1. Basic0001.xdjhtm — 基本資料（傳統入口）
      2. Basic0006.xdjhtm — 基金概觀（基金資訊類，新 ETF 可能在此）
      3. Basic0011.xdjhtm — 基金特色（少見但部分基金有）
    每 URL 內：proxy_helper 主源 → curl_cffi fallback。

    Regex 寬鬆策略
    --------------
    名字：「經理人」「基金經理人」「現任經理人」(中間可有 HTML/whitespace) 後接中文 2-8 字
    任期：「到職日」「上任日」「任期」「管理基金日」「派任日」其中之一 + 日期

    Returns
    -------
    dict | None
        成功：{'name': '張三', 'since': '2024-04-15', 'tenure_days': 400}
        失敗：None；失敗原因寫入 st.session_state['_etf_manager_last_err'][ticker]
    """
    import re as _re_mg
    from datetime import date as _date_mg
    _t = (ticker or '').replace('.tw', '.TW').strip()
    if not _t:
        return None
    if '.' not in _t:
        _t = f'{_t}.TW'

    _urls = [
        f'https://www.moneydj.com/ETF/X/Basic/Basic0001.xdjhtm?etfid={_t}',
        f'https://www.moneydj.com/ETF/X/Basic/Basic0006.xdjhtm?etfid={_t}',
        f'https://www.moneydj.com/ETF/X/Basic/Basic0011.xdjhtm?etfid={_t}',
    ]
    _err_trace: list[str] = []

    for _url in _urls:
        _txt = None
        _endpoint = _url.split('/')[-1].split('?')[0]
        # ── 1. proxy_helper（NAS Squid 台灣 IP）主源 ─────────────
        try:
            from proxy_helper import fetch_url as _fu_mg
            _r = _fu_mg(_url, timeout=12, attempts=2)
            if _r is not None and _r.status_code == 200 and len(_r.text or '') > 500:
                _r.encoding = 'utf-8'
                _txt = _r.text
            else:
                _code = _r.status_code if _r is not None else 'None'
                _ln = len(_r.text or '') if _r is not None else 0
                _err_trace.append(f'proxy {_endpoint}: HTTP {_code} len={_ln}')
                print(f'[MDJ/manager] proxy {_t} {_endpoint}: HTTP {_code} len={_ln}')
        except Exception as _ep:
            _err_trace.append(f'proxy {_endpoint}: {type(_ep).__name__}')
            print(f'[MDJ/manager] proxy 異常 {_t} {_endpoint}: {type(_ep).__name__}: {_ep}')

        # ── 2. curl_cffi fallback ────────────────────────────────
        if _txt is None:
            try:
                from curl_cffi import requests as _cffi_mg
                _r2 = _cffi_mg.get(_url, impersonate='chrome124', timeout=12)
                if _r2.status_code == 200 and len(_r2.text or '') > 500:
                    _txt = _r2.text
                else:
                    _err_trace.append(f'cffi {_endpoint}: HTTP {_r2.status_code}')
                    print(f'[MDJ/manager] curl_cffi {_t} {_endpoint}: HTTP {_r2.status_code}')
            except Exception as _ec:
                _err_trace.append(f'cffi {_endpoint}: {type(_ec).__name__}')
                print(f'[MDJ/manager] curl_cffi 異常 {_t} {_endpoint}: {type(_ec).__name__}: {_ec}')

        if _txt is None:
            continue

        # ── 3. 寬鬆 regex 嘗試解析 ────────────────────────────────
        try:
            # 名字：經理人 / 基金經理人 / 現任經理人 ... 中文 2-8 字
            _name_m = _re_mg.search(
                r'(?:基金|現任)?\s*經理人[^<>]{0,50}?>\s*([一-鿿]{2,8})\s*[<\(]',
                _txt,
            )
            # 寬鬆 fallback：經理人後直接接中文（無 > 標籤）
            if not _name_m:
                _name_m = _re_mg.search(
                    r'(?:基金|現任)?\s*經理人[^一-鿿\d]{0,30}?([一-鿿]{2,8})',
                    _txt,
                )
            _date_m = _re_mg.search(
                r'(?:到職日|上任日|任期|管理基金日|派任日|起聘日)[^\d]{0,30}?(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})',
                _txt,
            )
            if not _name_m:
                _err_trace.append(f'{_endpoint}: 200 但 regex 無經理人')
                print(f'[MDJ/manager] ⚠️ {_t} {_endpoint}: 200 但 regex 無經理人')
                continue
            _name = _name_m.group(1).strip()
            _since, _days = None, None
            if _date_m:
                _y, _mo, _d = (int(_date_m.group(i)) for i in (1, 2, 3))
                try:
                    _dt = _date_mg(_y, _mo, _d)
                    _since = _dt.strftime('%Y-%m-%d')
                    _days = (_date_mg.today() - _dt).days
                except ValueError:
                    pass
            print(f'[MDJ/manager] ✅ {_t} = {_name} via {_endpoint} (since={_since}, days={_days})')
            return {'name': _name, 'since': _since, 'tenure_days': _days}
        except Exception as _e:
            _err_trace.append(f'{_endpoint}: regex 例外 {type(_e).__name__}')
            print(f'[MDJ/manager] ❌ regex parse {_t} {_endpoint}: {type(_e).__name__}: {_e}')

    # ── 4. SITCA fallback — 與費用率同 proxy 路徑（已證可走）────────
    if _t.replace('.TW', '').replace('.TWO', '').isdigit():
        _sitca = _fetch_sitca_manager(_t)
        if _sitca and _sitca.get('name'):
            print(f'[SITCA/manager] ✅ {_t} = {_sitca["name"]}')
            return _sitca
        else:
            _err_trace.append('sitca: 多 URL/多 column 比對全失敗')

    # ── 5. Yuanta 官網 fallback — 主動式 ETF 專屬（v1.1）─────────────
    _yu = _fetch_yuanta_active_etf_meta(_t)
    if _yu and _yu.get('manager'):
        print(f'[Yuanta/manager] ✅ {_t} = {_yu["manager"]}')
        return {'name': _yu['manager'], 'since': None, 'tenure_days': None,
                'source': 'yuanta-official'}
    elif _yu is not None:
        _err_trace.append('yuanta: 200 但 regex 無經理人')
    else:
        if is_active_etf(_t):
            _err_trace.append('yuanta: 3 URL 全 fail')

    # 全部失敗 — 寫 session_state 給診斷面板讀
    try:
        if st is not None:
            _store = st.session_state.setdefault('_etf_manager_last_err', {})
            _store[_t] = ' | '.join(_err_trace) if _err_trace else 'unknown'
    except Exception:
        pass
    return None


@st.cache_data(ttl=604800, show_spinner=False)
def _fetch_sitca_manager(ticker: str):
    """SITCA fallback：投信投顧公會基金經理人查詢。

    跟 fetch_sitca_expense_ratio 同 proxy 路徑（已驗證可走）；pd.read_html 後動態
    掃描所有表格找「代號／基金代碼」+「經理人／基金經理人」雙欄。

    Returns
    -------
    dict | None  {'name': ..., 'since': None, 'tenure_days': None}（任期 SITCA 通常不揭露）
    """
    from proxy_helper import fetch_url as _fu_sm
    import pandas as _pd_sm
    _t = (ticker or '').replace('.TW', '').replace('.tw', '').replace('.TWO', '').strip()
    if not _t or not _t.isdigit():
        return None
    _tn = _t.lstrip('0') or '0'

    _urls = [
        'https://www.sitca.org.tw/ROC/Industry/IN2401.aspx?pid=IN2401_01',
        'https://www.sitca.org.tw/ROC/Industry/IN2421.aspx?pid=IN2421_01',
        'https://www.sitca.org.tw/ROC/Industry/IN2422.aspx?pid=IN2422_01',
        'https://www.sitca.org.tw/ROC/Industry/IN2411.aspx?pid=IN2411_01',
    ]
    for _url in _urls:
        try:
            r = _fu_sm(_url, timeout=15, attempts=2)
            if r is None or r.status_code != 200 or len(r.text or '') < 500:
                continue
            r.encoding = 'utf-8'
            try:
                tables = _pd_sm.read_html(r.text)
            except ValueError:
                continue
            for tbl in tables:
                code_col = next((c for c in tbl.columns
                                 if any(k in str(c) for k in
                                        ('代號', '代碼', '基金統編', '統一編號', 'Code'))), None)
                mgr_col = next((c for c in tbl.columns
                                if any(k in str(c) for k in
                                       ('經理人', '基金經理', '現任經理'))), None)
                if code_col is None or mgr_col is None:
                    continue
                _digits = tbl[code_col].astype(str).str.replace(r'\D', '', regex=True)
                row = tbl[_digits.where(_digits != '', '0').str.lstrip('0').replace('', '0') == _tn]
                if row.empty:
                    continue
                _raw = str(row[mgr_col].iloc[0]).strip()
                if not _raw or _raw.lower() == 'nan' or _raw.isdigit():
                    continue
                # 多人共同經理用「、」「,」分隔；可能附括號註記，取首位淨化
                _name = _raw.split('、')[0].split(',')[0].split('(')[0].split('（')[0].strip()
                if 2 <= len(_name) <= 8:
                    print(f'[SITCA/manager] ✅ {_t} = {_name} (url={_url[-30:]})')
                    return {'name': _name, 'since': None, 'tenure_days': None}
        except Exception as e:
            print(f'[SITCA/manager] {_t} {_url[-30:]}: {type(e).__name__}: {e}')
            continue
    return None


def get_etf_expense_ratio_safe(ticker: str):
    """安全讀取 ETF 費用率：SITCA → MoneyDJ → Yuanta → yfinance 四段備援；缺失回 None"""
    _sit = fetch_sitca_expense_ratio(ticker)
    if _sit is not None:
        return _sit
    _mdj = fetch_moneydj_expense_ratio(ticker)
    if _mdj is not None:
        return _mdj
    # v1.1：主動式 ETF 專屬，SITCA + MDJ 都失敗時補位
    if is_active_etf(ticker):
        _yu = _fetch_yuanta_active_etf_meta(ticker)
        if _yu and _yu.get('expense') is not None:
            return _yu['expense']
    try:
        info = fetch_etf_info(ticker)
        return (info.get('annualReportExpenseRatio')
                or info.get('totalExpenseRatio')
                or info.get('expenseRatio'))
    except Exception:
        return None


# ── NAV 合理範圍常數（用於 fetch_etf_nav_history 多源 sanity check）──
_NAV_MIN, _NAV_MAX = 0.5, 100000


def _safe_float(s, strip_chars: str = ',%') -> float | None:
    """安全 float 解析：失敗回 None。

    Replaces inline `try: float(...) except: pass` pattern；避免 bare except
    吞掉 KeyboardInterrupt / SystemExit。
    """
    try:
        _t = str(s).strip()
        for _c in strip_chars:
            _t = _t.replace(_c, '')
        return float(_t) if _t else None
    except (ValueError, TypeError):
        return None


@st.cache_data(ttl=7200, show_spinner=False, max_entries=10)
def fetch_etf_nav_history(ticker: str, days: int = 35, ver: int = 4) -> "pd.DataFrame":
    """ETF 歷史淨值及折溢價（最近 N 個交易日）

    資料來源優先順序（5 段備援 + 1 兜底）：
      1. FinMind TaiwanETFNetAssetValue（批次，有/無 token 皆可）
      2. goodinfo.tw StockDetail（不受 TWSE IP 封鎖）
      3. TWSE OpenAPI（僅 NAS Proxy 環境）
      4. MoneyDJ BeautifulSoup
      5. yfinance navPrice
      *. 兜底：FinMind 過舊資料（前述 5 段全失敗時）

    Args
    ----
    ticker : str  ETF 代號（含 .TW 後綴）
    days   : int  目標回溯交易日（含緩衝 +10 日）
    ver    : int  cache key bumper — 升版觸發 @st.cache_data 失效；不入函式邏輯。

    Returns
    -------
    pd.DataFrame  欄位：date / price / nav / premium / premium_pct
    """
    import os
    import datetime as _dt
    import requests as _rq_etfnav
    code = ticker.replace('.TW', '').replace('.TWO', '')
    # st.secrets 優先（Streamlit Cloud secrets 不自動匯出至 os.environ）
    token = (getattr(st, 'secrets', {}).get('FINMIND_TOKEN')
             or os.environ.get('FINMIND_TOKEN', ''))
    start = (_dt.date.today() - _dt.timedelta(days=days + 10)).strftime('%Y-%m-%d')
    _df_stale = None       # 備援：FinMind 過舊資料
    _days_stale: int | None = None

    # ── 1. FinMind ETF NAV（試兩個 dataset 名稱 + 多種欄位名稱）───────────
    for _ds1 in ['TaiwanETFNetAssetValue', 'TaiwanStockETFNAV']:
        try:
            _p = {'dataset': _ds1, 'data_id': code, 'start_date': start}
            if token: _p['token'] = token
            _r = _rq_etfnav.get('https://api.finmindtrade.com/api/v4/data', params=_p,
                                  timeout=15)
            _j = _r.json()
            _jstatus = _j.get('status')
            _jdata   = _j.get('data')
            # 接受 status=200 / status=None（部分 proxy 環境）；排除已知錯誤碼
            _status_ok = str(_jstatus) not in ('400', '401', '402', '403', '404', '500')
            if _jdata and _status_ok:
                _df = pd.DataFrame(_jdata)
                # 自動偵測 NAV 欄位名稱（FinMind 兩個版本欄位名不同）
                _nav_field = next((f for f in ['nav', 'base_unit_net_value', 'NavPrice', 'netAssetValue']
                                   if f in _df.columns), None)
                if _nav_field is None:
                    print(f'[ETF NAV] {code} {_ds1}: 找不到 NAV 欄位，現有={list(_df.columns)}')
                    continue
                _df['date'] = pd.to_datetime(_df['date']).dt.date
                _df['nav']  = pd.to_numeric(_df[_nav_field], errors='coerce')
                _df = _df[_df['nav'].notna() & (_df['nav'] > 0)].sort_values('date')
                if _df.empty:
                    print(f'[ETF NAV] {code} {_ds1}: 所有 nav 欄位為空/NaN，跳過')
                    continue
                _latest_d   = _df['date'].iloc[-1]
                _days_stale = (_dt.date.today() - _latest_d).days
                _df_stale   = _df[['date', 'nav']]   # 保留，供 path 4 備援
                print(f'[ETF NAV] {code} {_ds1}(field={_nav_field}): {len(_df)} 筆, 最新={_latest_d}, 距今={_days_stale}d')
                if _days_stale <= 14:          # 14天內視為可用（含連假/公告延遲）
                    return _df_stale
                print(f'[ETF NAV] {_ds1} {code} 資料較舊({_days_stale}d)，嘗試其他來源')
                break   # 找到資料就不再嘗試第二個 dataset
            else:
                _msg = str(_j.get('msg', ''))[:80]
                print(f'[ETF NAV] FinMind {_ds1} {code}: status={_jstatus} data_len={len(_jdata) if _jdata else 0} msg={_msg}')
        except Exception as _e1:
            print(f'[ETF NAV] FinMind {_ds1} {code}: {_e1}')

    # ── 2. goodinfo.tw — 不受 TWSE IP 封鎖，抓取 ETF 淨值 ───────────────────
    try:
        from bs4 import BeautifulSoup as _BS4_gi
        import re as _re_gi
        _url_gi = f'https://goodinfo.tw/tw/StockDetail.asp?STOCK_ID={code}'
        _hdrs_gi = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'zh-TW,zh;q=0.9', 'Referer': 'https://goodinfo.tw/tw/'}
        try:
            from curl_cffi import requests as _cffi_gi
            _r_gi = _cffi_gi.get(_url_gi, impersonate='chrome124', timeout=12)
        except Exception:
            _r_gi = _rq_etfnav.get(_url_gi, headers=_hdrs_gi, timeout=12, verify=False)
        if _r_gi.status_code == 200:
            _soup_gi = _BS4_gi(_r_gi.text, 'lxml')
            _nav_gi, _prem_gi = None, None
            # 策略1：在 <td> 中找「淨值」標籤，取下一格數字
            for _td_gi in _soup_gi.find_all('td'):
                _txt_gi = _td_gi.get_text(strip=True)
                if _txt_gi in ('淨值', '每單位淨值', 'NAV'):
                    _sib_gi = _td_gi.find_next_sibling('td')
                    if _sib_gi:
                        _v = _safe_float(_sib_gi.get_text(strip=True))
                        if _v is not None and _NAV_MIN < _v < _NAV_MAX:
                            _nav_gi = _v
                    if _nav_gi:
                        break
            # 策略2：regex 掃全文
            if not _nav_gi:
                _m_gi = _re_gi.search(r'淨值[^\d<]{0,30}?(\d{1,5}\.\d{2,6})', _r_gi.text)
                if _m_gi:
                    _v = _safe_float(_m_gi.group(1))
                    if _v is not None and _NAV_MIN < _v < _NAV_MAX:
                        _nav_gi = _v
            # 嘗試抓折溢價率
            if _nav_gi:
                for _td_gi2 in _soup_gi.find_all('td'):
                    if '折溢價' in _td_gi2.get_text(strip=True):
                        _sib_gi2 = _td_gi2.find_next_sibling('td')
                        if _sib_gi2:
                            _m_p = _re_gi.search(r'([+-]?\d+\.?\d*)', _sib_gi2.get_text(strip=True))
                            if _m_p:
                                _prem_gi = _safe_float(_m_p.group(1))
                        if _prem_gi is not None:
                            break
                _row_gi = {'date': _dt.date.today(), 'nav': _nav_gi}
                if _prem_gi is not None: _row_gi['premium_pct'] = _prem_gi
                print(f'[ETF NAV] {code} goodinfo: nav={_nav_gi} prem={_prem_gi}%')
                return pd.DataFrame([_row_gi])
            else:
                print(f'[ETF NAV] {code} goodinfo: 找不到淨值欄位')
        else:
            print(f'[ETF NAV] {code} goodinfo: HTTP {_r_gi.status_code}')
    except Exception as _e_gi:
        print(f'[ETF NAV] goodinfo {code}: {_e_gi}')

    # ── 3. TWSE OpenAPI（openapi.twse.com.tw 非主站，先直連再走 Proxy）──────
    try:
        from daily_checklist import get_nas_proxy as _gnp_nav
        _nas_nav = _gnp_nav()
    except Exception:
        _nas_nav = None

    def _parse_twse_row(row_dict, ep_label):
        _nav2 = 0.0
        for _nk in ['單位淨值', '淨值', 'NetAssetValue', 'nav']:
            _v = _safe_float(row_dict.get(_nk, ''))
            if _v is not None:
                _nav2 = _v
                break
        _price2 = 0.0
        for _pk in ['收盤價', 'ClosingPrice', 'close']:
            _v = _safe_float(row_dict.get(_pk, ''))
            if _v is not None:
                _price2 = _v
                break
        _prem_key = next((k for k in row_dict if '折溢價' in str(k)), None)
        _prem2 = _safe_float(row_dict[_prem_key]) if _prem_key else None
        if _prem2 is None and _nav2 > 0 and _price2 > 0:
            _prem2 = round((_price2 - _nav2) / _nav2 * 100, 2)
        if _nav2 > 0:
            _r_out = {'date': _dt.date.today(), 'nav': _nav2}
            if _price2 > 0:
                _r_out['price'] = _price2
            if _prem2 is not None:
                _r_out['premium_pct'] = _prem2
            print(f'[ETF NAV] {code} TWSE({ep_label}): nav={_nav2} price={_price2} prem={_prem2}%')
            return _r_out
        return None

    for _proxy_candidate in ([None] + ([_nas_nav] if _nas_nav else [])):
        _ptag = 'direct' if _proxy_candidate is None else 'proxy'
        for _op_id2 in ['TaiwanStockPremiumDiscountRatio', 'TaiwanStockNetValue']:
            try:
                _ep2 = f'https://openapi.twse.com.tw/v1/ETF/{_op_id2}'
                _r2 = _rq_etfnav.get(_ep2, headers={'Accept': 'application/json',
                                                      'User-Agent': 'Mozilla/5.0'},
                                      proxies=_proxy_candidate, timeout=10, verify=False)
                _j2 = _r2.json()
                _df2 = pd.DataFrame(_j2 if isinstance(_j2, list) else [])
                if _df2.empty:
                    print(f'[ETF NAV] TWSE {_op_id2}({_ptag}): 回傳空資料'); continue
                _code_col = next((c for c in _df2.columns if '證券代號' in str(c) or c == 'code'), None)
                if _code_col is None:
                    print(f'[ETF NAV] TWSE {_op_id2}({_ptag}): 找不到 證券代號 欄位'); continue
                _match = _df2[_df2[_code_col].astype(str).str.strip() == code]
                if _match.empty:
                    print(f'[ETF NAV] TWSE {_op_id2}({_ptag}): 找不到 {code}'); continue
                _out2 = _parse_twse_row(_match.iloc[0].to_dict(), f'{_op_id2}/{_ptag}')
                if _out2:
                    return pd.DataFrame([_out2])
            except Exception as _e2:
                print(f'[ETF NAV] TWSE {_op_id2}({_ptag}) {code}: {_e2}')
        # 若無 _nas_nav，外層 list 為 [None] 單元素，loop 自然結束無需 break

    # ── 4. MoneyDJ 爬蟲（BeautifulSoup，不需 token）──────────────────────
    try:
        from bs4 import BeautifulSoup as _BS4
        _hdrs_mdj = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8',
            'Referer': 'https://www.moneydj.com/',
        }
        _url_mdj = f'https://www.moneydj.com/ETF/X/Basic/Basic0004.xdjhtm?etfid={code}'
        # 優先用 curl_cffi 模擬 Chrome TLS 指紋，繞過反爬蟲；失敗再降級 requests
        try:
            from curl_cffi import requests as _cffi_req
            _r_mdj = _cffi_req.get(_url_mdj, impersonate='chrome124', timeout=12)
        except Exception:
            _r_mdj = _rq_etfnav.get(_url_mdj, headers=_hdrs_mdj, timeout=12, verify=False)
        if _r_mdj.status_code == 200:
            _soup = _BS4(_r_mdj.text, 'lxml')
            _nav_mdj = None
            # 策略1：找含「淨值」的 th/td，取下一格數字
            for _th in _soup.find_all(['th', 'td', 'span', 'div', 'dt']):
                _t = _th.get_text(strip=True)
                if ('淨值' in _t or 'NAV' in _t) and len(_t) < 20:
                    _td = _th.find_next_sibling()
                    if _td:
                        _v = _safe_float(_td.get_text(strip=True))
                        if _v is not None and _v > 0:
                            _nav_mdj = _v
                            break
            # 策略2：regex 直接掃 HTML
            if not _nav_mdj:
                import re as _re_mdj
                _m = _re_mdj.search(r'(?:淨值|NAV)[^\d]{0,20}?(\d{1,5}\.\d{2,6})', _r_mdj.text)
                if _m:
                    _nav_mdj = _safe_float(_m.group(1))
            if _nav_mdj and _nav_mdj > 0:
                print(f'[ETF NAV] MoneyDJ {code}: nav={_nav_mdj}')
                return pd.DataFrame([{'date': _dt.date.today(), 'nav': _nav_mdj}])
            else:
                print(f'[ETF NAV] MoneyDJ {code}: HTTP {_r_mdj.status_code} 找不到淨值')
        else:
            print(f'[ETF NAV] MoneyDJ {code}: HTTP {_r_mdj.status_code}')
    except Exception as _e_mdj:
        print(f'[ETF NAV] MoneyDJ {code}: {_e_mdj}')

    # ── 5. yfinance ETF info.navPrice（加限速 retry）──────────────────────
    import time as _t3
    for _sfx3 in ('.TW', '.TWO'):
        for _retry3 in range(3):
            try:
                import yfinance as _yf3
                _tk3 = _yf3.Ticker(f'{code}{_sfx3}')
                _info3 = _tk3.info
                _nav3 = _info3.get('navPrice') or _info3.get('regularMarketNAV')
                if _nav3 and float(_nav3) > 0:
                    print(f'[ETF NAV] yfinance {code}{_sfx3}: navPrice={_nav3}')
                    return pd.DataFrame([{'date': _dt.date.today(), 'nav': float(_nav3)}])
                break  # 沒資料，不 retry
            except Exception as _e3:
                _e3s = str(_e3)
                if ('Too Many Requests' in _e3s or 'Rate' in _e3s) and _retry3 < 2:
                    _t3.sleep(2 + _retry3 * 2)  # 2s, 4s
                    print(f'[ETF NAV] yfinance {code}{_sfx3}: 限速 retry {_retry3+1}/3')
                    continue
                print(f'[ETF NAV] yfinance {code}{_sfx3}: {_e3}')
                break

    # ── 最終兜底：FinMind 過舊資料（goodinfo/MoneyDJ/yfinance 全部失敗時）────
    if _df_stale is not None and not _df_stale.empty:
        print(f'[ETF NAV] {code} 最終兜底: FinMind過舊資料({_days_stale}d)，所有即時來源失敗')
        return _df_stale

    return pd.DataFrame()


@st.cache_data(ttl=1800, max_entries=10)
def _fetch_sector_returns(tickers: tuple, period: str) -> dict:
    """批次抓取類股漲跌幅，回傳 {ticker: pct_change}"""
    result = {}
    try:
        raw = yf.download(list(tickers), period=period,
                          auto_adjust=True, progress=False, threads=True)
        if raw.empty:
            return result
        # yf.download 多 ticker 時 Close 為 MultiIndex
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw['Close'] if 'Close' in raw.columns.get_level_values(0) else raw.xs('Close', axis=1, level=0)
        else:
            close = raw[['Close']] if 'Close' in raw.columns else raw
        close = close.ffill().dropna(how='all')
        for t in tickers:
            if t in close.columns:
                series = close[t].dropna()
                if len(series) >= 2:
                    pct = round((float(series.iloc[-1]) / float(series.iloc[0]) - 1) * 100, 2)
                    result[t] = pct
    except Exception as e:
        st.warning(f'類股資料抓取部分失敗：{e}')
    return result


@st.cache_data(ttl=604800, max_entries=200, show_spinner=False)
def fetch_etf_underlying_index(ticker: str):
    """從 MoneyDJ 抓 ETF 追蹤指數名稱（yfinance 沒有此欄）。

    抓取策略：複用 fetch_etf_manager 的 proxy 通路（NAS Squid 主源 + curl_cffi fallback）。
    優先順序：Basic0001（基本資料，最常見）→ Basic0006（基金概觀）→ Basic0007（持股明細，部分有）。

    Regex 三層寬鬆策略：
      1. 表頭 + 表格儲存格：>追蹤指數</…><td…>內容</td>
      2. 冒號形式：追蹤指數：內容 / 標的指數：內容
      3. 同義詞兜底：對應/標的/追蹤 指數 後接中英文/數字 4-80 字

    Returns
    -------
    str | None
        指數名稱（如 '臺灣加權股價報酬指數' / 'MSCI Taiwan ESG Index'），找不到回 None。
    """
    import re as _re_ui
    _t = (ticker or '').replace('.tw', '.TW').strip()
    if not _t:
        return None
    if '.' not in _t:
        _t = f'{_t}.TW'

    _urls = [
        f'https://www.moneydj.com/ETF/X/Basic/Basic0001.xdjhtm?etfid={_t}',
        f'https://www.moneydj.com/ETF/X/Basic/Basic0006.xdjhtm?etfid={_t}',
        f'https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={_t}',
    ]
    _err_trace: list[str] = []

    for _url in _urls:
        _txt = None
        _endpoint = _url.split('/')[-1].split('?')[0]
        try:
            from proxy_helper import fetch_url as _fu_ui
            _r = _fu_ui(_url, timeout=12, attempts=2)
            if _r is not None and _r.status_code == 200 and len(_r.text or '') > 500:
                _r.encoding = 'utf-8'
                _txt = _r.text
            else:
                _code = _r.status_code if _r is not None else 'None'
                _err_trace.append(f'proxy {_endpoint}: HTTP {_code}')
        except Exception as _epu:
            _err_trace.append(f'proxy {_endpoint}: {type(_epu).__name__}')

        if _txt is None:
            try:
                from curl_cffi import requests as _cffi_ui
                _r2 = _cffi_ui.get(_url, impersonate='chrome124', timeout=12)
                if _r2.status_code == 200 and len(_r2.text or '') > 500:
                    _txt = _r2.text
                else:
                    _err_trace.append(f'cffi {_endpoint}: HTTP {_r2.status_code}')
            except Exception as _ecu:
                _err_trace.append(f'cffi {_endpoint}: {type(_ecu).__name__}')

        if _txt is None:
            continue

        # HTML entity 預清洗 — 避免 lazy regex 卡在 &nbsp;
        _txt = (_txt.replace('&nbsp;', ' ').replace('&#160;', ' ')
                    .replace('&amp;', '&').replace('　', ' '))

        # 排除「追蹤誤差」「指數型基金」等假陽性詞
        _idx = None
        try:
            # 1. 表頭 + 儲存格（最常見的 MoneyDJ 排版）
            _m = _re_ui.search(
                r'(?:追蹤|標的|對應)\s*指數\s*</[^>]+>\s*<[^>]+>\s*'
                r'([一-鿿A-Za-z0-9 &\.\-／/（）()]{4,80})\s*<',
                _txt,
            )
            if not _m:
                # 2. 冒號形式
                _m = _re_ui.search(
                    r'(?:追蹤|標的|對應)\s*指數\s*[：:]\s*'
                    r'([一-鿿A-Za-z0-9 &\.\-／/（）()]{4,80})',
                    _txt,
                )
            if not _m:
                # 3. 寬鬆兜底（含 HTML/whitespace 雜訊）
                _m = _re_ui.search(
                    r'(?:追蹤|標的|對應)\s*指數[^一-鿿A-Za-z\d]{0,40}?'
                    r'([一-鿿A-Za-z0-9 &\.\-／/（）()]{4,80})',
                    _txt,
                )
            if _m:
                _cand = _m.group(1)
                # HTML entity / 全形空白清洗 → 排除假陽性與長度不足
                _cand = (_cand.replace('&nbsp;', ' ').replace('　', ' ')
                              .replace('&amp;', '&').strip().rstrip('，,。.、 '))
                _bad = ('追蹤誤差', '指數股票型', '指數型基金', '基金經理',
                        '管理費', 'nbsp', 'amp;')
                if len(_cand) >= 4 and not any(_b in _cand for _b in _bad):
                    _idx = _cand
        except Exception as _ex:
            _err_trace.append(f'{_endpoint}: regex {type(_ex).__name__}')

        if _idx:
            print(f'[MDJ/index] OK {_t} = {_idx} via {_endpoint}')
            return _idx
        _err_trace.append(f'{_endpoint}: 200 但 regex 無指數')

    try:
        if st is not None:
            _store = st.session_state.setdefault('_etf_index_last_err', {})
            _store[_t] = ' | '.join(_err_trace) if _err_trace else 'unknown'
    except Exception:
        pass
    print(f'[MDJ/index] FAIL {_t} — {_err_trace[-1] if _err_trace else "no trace"}')
    return None
