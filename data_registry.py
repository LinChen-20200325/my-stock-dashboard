"""data_registry.py — 資料源中央註冊表 (Single Source of Truth)

設計目的：
  • 集中管理所有第一手資料端點的 metadata
  • 支援「資料診斷」Tab 動態渲染
  • 支援「即時 Ping 測試」(限核心端點)
  • 純宣告式：未來新增資料源只要加一筆 dict，無需改診斷頁

使用方式：
    from data_registry import DATA_REGISTRY, get_state_value, ping_endpoint
    for entry in DATA_REGISTRY:
        ...

註冊表欄位定義：
  category:      分類（用於分組顯示）
  name:          資料中文名稱
  source:        資料來源（FRED / FinMind / TWSE / yfinance ...）
  endpoint:      API endpoint（簡化顯示用）
  identifier:    Ticker / dataset / series_id
  frequency:     daily / monthly / quarterly / yearly / event
  requires_key:  None / 'FRED_API_KEY' / 'FINMIND_TOKEN' / 'GEMINI_API_KEY'
  usage:         用途說明（一句話）
  state_key:     從 session_state 取狀態的 dot 路徑（None=未連動）
  pingable:      是否支援即時測試（True/False）
  ping_url:      測試用完整 URL（None=不測試）

教學內容（EDU_GUIDE，依 identifier 對應）：
  meaning:           白話定義（這是什麼）
  how_to_read:       判讀規則 list[(門檻, 訊號)]
  pair_with:         搭配看的指標清單
  historical_anchor: 歷史錨點對照
  upstream:          上游因（誰會影響它）
  downstream:        下游果（它會影響誰）
"""
from __future__ import annotations
from typing import Any


# ══════════════════════════════════════════════════════════════════════════════
# 中央註冊表
# ══════════════════════════════════════════════════════════════════════════════
DATA_REGISTRY: list[dict[str, Any]] = [
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 🌍 一、美國總經（FRED）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {'category':'🌍 美國總經', 'name':'美國核心 CPI 年增率', 'source':'FRED',
     'endpoint':'fred.stlouisfed.org/graph/fredgraph.csv', 'identifier':'CPILFESL',
     'frequency':'monthly', 'requires_key':'FRED_API_KEY',
     'usage':'通膨判讀、Fed 升降息預測',
     'state_key':'macro_info.us_core_cpi.date', 'pingable':True,
     'ping_url':'https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPILFESL'},
    {'category':'🇹🇼 台灣總經', 'name':'台灣製造業 PMI (CIER)', 'source':'CIER+MacroMicro+StockFeel+鉅亨 4 段',
     'endpoint':'cier.edu.tw / macromicro.me/charts/22 / stockfeel / cnyes',
     'identifier':'cier-pmi',
     'frequency':'monthly', 'requires_key':None,
     'usage':'台灣製造業景氣領先指標 (>50 擴張，CIER 中華經濟研究院每月第一個工作日公布)',
     'state_key':'macro_info.ism_pmi.date', 'pingable':True,
     'ping_url':'https://www.macromicro.me/charts/22/taiwan-pmi'},
    {'category':'🌍 美國總經', 'name':'BLS CPI 備援', 'source':'BLS',
     'endpoint':'api.bls.gov/publicAPI/v2/timeseries/data', 'identifier':'CUUR0000SA0',
     'frequency':'monthly', 'requires_key':None,
     'usage':'FRED CPI 失敗時的備援來源',
     'state_key':None, 'pingable':False, 'ping_url':None},

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 🌐 二、國際金融指數（yfinance）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {'category':'🌐 國際金融', 'name':'道瓊工業指數', 'source':'yfinance',
     'endpoint':'query1.finance.yahoo.com', 'identifier':'^DJI',
     'frequency':'daily', 'requires_key':None,
     'usage':'美股大盤代表指數',
     'state_key':'cl_data.intl', 'pingable':False, 'ping_url':None},
    {'category':'🌐 國際金融', 'name':'S&P 500', 'source':'yfinance',
     'endpoint':'query1.finance.yahoo.com', 'identifier':'^GSPC',
     'frequency':'daily', 'requires_key':None,
     'usage':'美股大盤指標',
     'state_key':'cl_data.intl', 'pingable':False, 'ping_url':None},
    {'category':'🌐 國際金融', 'name':'那斯達克', 'source':'yfinance',
     'endpoint':'query1.finance.yahoo.com', 'identifier':'^IXIC',
     'frequency':'daily', 'requires_key':None,
     'usage':'科技股指標',
     'state_key':'cl_data.intl', 'pingable':False, 'ping_url':None},
    {'category':'🌐 國際金融', 'name':'費城半導體 SOX', 'source':'yfinance',
     'endpoint':'query1.finance.yahoo.com', 'identifier':'^SOX',
     'frequency':'daily', 'requires_key':None,
     'usage':'半導體景氣領先（與台股高度連動）',
     'state_key':'cl_data.intl', 'pingable':False, 'ping_url':None},
    {'category':'🌐 國際金融', 'name':'美元指數 DXY', 'source':'yfinance',
     'endpoint':'query1.finance.yahoo.com', 'identifier':'DX-Y.NYB',
     'frequency':'daily', 'requires_key':None,
     'usage':'美元強弱、外資流向判讀',
     'state_key':'cl_data.intl', 'pingable':False, 'ping_url':None},
    {'category':'🌐 國際金融', 'name':'美債 10Y 殖利率', 'source':'yfinance',
     'endpoint':'query1.finance.yahoo.com', 'identifier':'^TNX',
     'frequency':'daily', 'requires_key':None,
     'usage':'長天期利率、市場避險情緒',
     'state_key':'cl_data.intl', 'pingable':False, 'ping_url':None},
    {'category':'🌐 國際金融', 'name':'VIX 恐慌指數', 'source':'yfinance',
     'endpoint':'query1.finance.yahoo.com', 'identifier':'^VIX',
     'frequency':'daily', 'requires_key':None,
     'usage':'市場恐慌程度（>30 警戒）',
     'state_key':'macro_info.vix.current', 'pingable':False, 'ping_url':None},
    {'category':'🌐 國際金融', 'name':'銅博士', 'source':'yfinance',
     'endpoint':'query1.finance.yahoo.com', 'identifier':'HG=F',
     'frequency':'daily', 'requires_key':None,
     'usage':'全球景氣領先指標',
     'state_key':None, 'pingable':False, 'ping_url':None},

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 🇹🇼 三、台股大盤（TWSE / yfinance）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {'category':'🇹🇼 台股大盤', 'name':'加權指數 OHLCV', 'source':'yfinance',
     'endpoint':'query1.finance.yahoo.com', 'identifier':'^TWII',
     'frequency':'daily', 'requires_key':None,
     'usage':'台股大盤主指數',
     'state_key':'cl_data.tw', 'pingable':True,
     'ping_url':'https://query1.finance.yahoo.com/v8/finance/chart/^TWII?range=1d&interval=1d'},
    {'category':'🇹🇼 台股大盤', 'name':'櫃買指數 OHLCV', 'source':'yfinance',
     'endpoint':'query1.finance.yahoo.com', 'identifier':'^TWOII',
     'frequency':'daily', 'requires_key':None,
     'usage':'OTC 市場指數',
     'state_key':'cl_data.tw', 'pingable':False, 'ping_url':None},
    {'category':'🇹🇼 台股大盤', 'name':'大盤成交統計', 'source':'TWSE OpenAPI',
     'endpoint':'/v1/exchangeReport/FMTQIK', 'identifier':'FMTQIK',
     'frequency':'daily', 'requires_key':None,
     'usage':'每日成交量、成交筆數',
     'state_key':None, 'pingable':True,
     'ping_url':'https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK'},
    {'category':'🇹🇼 台股大盤', 'name':'個股本益比/殖利率/PBR', 'source':'TWSE OpenAPI',
     'endpoint':'/v1/exchangeReport/BWIBBU_d', 'identifier':'BWIBBU_d',
     'frequency':'daily', 'requires_key':None,
     'usage':'💎 高息網漏斗篩選資料源',
     'state_key':None, 'pingable':True,
     'ping_url':'https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d'},
    {'category':'🇹🇼 台股大盤', 'name':'個股日均價', 'source':'TWSE OpenAPI',
     'endpoint':'/v1/exchangeReport/STOCK_DAY_AVG_ALL', 'identifier':'STOCK_DAY_AVG_ALL',
     'frequency':'daily', 'requires_key':None,
     'usage':'全市場個股日均價',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🇹🇼 台股大盤', 'name':'上市公司基本資料', 'source':'TWSE OpenAPI',
     'endpoint':'/v1/opendata/t187ap03_L', 'identifier':'t187ap03_L',
     'frequency':'event', 'requires_key':None,
     'usage':'公司名稱、產業類別查詢',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🇹🇼 台股大盤', 'name':'漲跌家數 ADL', 'source':'TWSE',
     'endpoint':'/rwd/zh/afterTrading/MI_INDEX', 'identifier':'MI_INDEX',
     'frequency':'daily', 'requires_key':None,
     'usage':'市場廣度（旌旗指數計算用）',
     'state_key':'cl_data.adl', 'pingable':False, 'ping_url':None},
    {'category':'🇹🇼 台股大盤', 'name':'除權息預告', 'source':'TWSE',
     'endpoint':'/rwd/zh/exRight/TWT49U', 'identifier':'TWT49U',
     'frequency':'event', 'requires_key':None,
     'usage':'除權息日期查詢',
     'state_key':None, 'pingable':False, 'ping_url':None},

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 💰 四、籌碼資料（TWSE / TPEX / TAIFEX）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {'category':'💰 籌碼', 'name':'三大法人現貨買賣超', 'source':'TWSE',
     'endpoint':'/rwd/zh/fund/BFI82U', 'identifier':'BFI82U',
     'frequency':'daily', 'requires_key':None,
     'usage':'外資/投信/自營買賣超（核心籌碼指標）',
     'state_key':'cl_data.inst', 'pingable':False, 'ping_url':None},
    {'category':'💰 籌碼', 'name':'個股法人買賣超', 'source':'TWSE',
     'endpoint':'/fund/T86', 'identifier':'T86',
     'frequency':'daily', 'requires_key':None,
     'usage':'個股級法人籌碼',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'💰 籌碼', 'name':'融資餘額', 'source':'TWSE',
     'endpoint':'/rwd/zh/marginTrading/MI_MARGN', 'identifier':'MI_MARGN',
     'frequency':'daily', 'requires_key':None,
     'usage':'散戶情緒指標（>2500 億過熱）',
     'state_key':'cl_data.margin', 'pingable':False, 'ping_url':None},
    {'category':'💰 籌碼', 'name':'OTC 主板每日報價', 'source':'TPEX OpenAPI',
     'endpoint':'/openapi/v1/tpex_mainboard_daily_close_quotes',
     'identifier':'tpex_mainboard',
     'frequency':'daily', 'requires_key':None,
     'usage':'櫃買市場全市場報價',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'💰 籌碼', 'name':'OTC 三大法人', 'source':'TPEX',
     'endpoint':'/web/stock/3insti/daily_report/3itrade_hedge_result.php',
     'identifier':'3itrade_hedge',
     'frequency':'daily', 'requires_key':None,
     'usage':'櫃買法人籌碼',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'💰 籌碼', 'name':'外資期貨留倉', 'source':'TAIFEX',
     'endpoint':'/cht/3/largeTraderFutQryTbl', 'identifier':'largeTraderFutQry',
     'frequency':'daily', 'requires_key':None,
     'usage':'外資期貨多空（先行指標）',
     'state_key':'li_latest', 'pingable':False, 'ping_url':None},
    {'category':'💰 籌碼', 'name':'期貨契約日資料', 'source':'TAIFEX',
     'endpoint':'/cht/3/futContractsDate', 'identifier':'futContractsDate',
     'frequency':'daily', 'requires_key':None,
     'usage':'期貨未平倉、結算日',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'💰 籌碼', 'name':'期貨日盤行情', 'source':'TAIFEX',
     'endpoint':'/cht/3/futDailyMarketReport', 'identifier':'futDailyMarketReport',
     'frequency':'daily', 'requires_key':None,
     'usage':'期貨成交、未平倉',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'💰 籌碼', 'name':'選擇權契約日資料', 'source':'TAIFEX',
     'endpoint':'/cht/3/callsAndPutsDate', 'identifier':'callsAndPutsDate',
     'frequency':'daily', 'requires_key':None,
     'usage':'選擇權成交、未平倉',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'💰 籌碼', 'name':'PCR Put/Call Ratio', 'source':'TAIFEX',
     'endpoint':'/cht/3/pcRatio', 'identifier':'pcRatio',
     'frequency':'daily', 'requires_key':None,
     'usage':'選擇權多空情緒（>1 偏空）',
     'state_key':None, 'pingable':True,
     'ping_url':'https://www.taifex.com.tw/cht/3/pcRatio'},
    {'category':'💰 籌碼', 'name':'前五大留倉', 'source':'TAIFEX',
     'endpoint':'/cht/3/largeTraderFutQryTbl', 'identifier':'前五大留倉',
     'frequency':'daily', 'requires_key':None,
     'usage':'前五大主力期貨多空（最強領先籌碼）',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'💰 籌碼', 'name':'前十大留倉', 'source':'TAIFEX',
     'endpoint':'/cht/3/largeTraderFutQryTbl', 'identifier':'前十大留倉',
     'frequency':'daily', 'requires_key':None,
     'usage':'前十大主力期貨多空（含反向 ETF 避險）',
     'state_key':None, 'pingable':False, 'ping_url':None},

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 🏢 五、個股財報（FinMind / MOPS / Goodinfo）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {'category':'🏢 個股財報', 'name':'個股 K線 OHLCV', 'source':'FinMind',
     'endpoint':'api.finmindtrade.com', 'identifier':'TaiwanStockPrice',
     'frequency':'daily', 'requires_key':'FINMIND_TOKEN',
     'usage':'個股日線資料（含成交量）',
     'state_key':'t2_data.df', 'pingable':False, 'ping_url':None},
    {'category':'🏢 個股財報', 'name':'月營收', 'source':'FinMind',
     'endpoint':'api.finmindtrade.com', 'identifier':'TaiwanStockMonthRevenue',
     'frequency':'monthly', 'requires_key':'FINMIND_TOKEN',
     'usage':'每月 10 日公布的營收',
     'state_key':'t2_data.rev', 'pingable':False, 'ping_url':None},
    {'category':'🏢 個股財報', 'name':'季財報（IS）', 'source':'FinMind',
     'endpoint':'api.finmindtrade.com', 'identifier':'TaiwanStockFinancialStatement',
     'frequency':'quarterly', 'requires_key':'FINMIND_TOKEN',
     'usage':'EPS / 毛利率 / 營業利益率',
     'state_key':'t2_data.qtr', 'pingable':False, 'ping_url':None},
    {'category':'🏢 個股財報', 'name':'季資產負債表', 'source':'FinMind',
     'endpoint':'api.finmindtrade.com', 'identifier':'TaiwanStockBalanceSheet',
     'frequency':'quarterly', 'requires_key':'FINMIND_TOKEN',
     'usage':'存貨 / 合約負債 / 總負債',
     'state_key':'t2_data.qtr_extra', 'pingable':False, 'ping_url':None},
    {'category':'🏢 個股財報', 'name':'季現金流量表', 'source':'FinMind',
     'endpoint':'api.finmindtrade.com', 'identifier':'TaiwanStockCashFlowsStatement',
     'frequency':'quarterly', 'requires_key':'FINMIND_TOKEN',
     'usage':'CapEx 資本支出 / FCF 自由現金流',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🏢 個股財報', 'name':'個股法人買賣超', 'source':'FinMind',
     'endpoint':'api.finmindtrade.com',
     'identifier':'TaiwanStockInstitutionalInvestorsBuySell',
     'frequency':'daily', 'requires_key':'FINMIND_TOKEN',
     'usage':'個股級三大法人買賣超',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🏢 個股財報', 'name':'三大法人合計', 'source':'FinMind',
     'endpoint':'api.finmindtrade.com',
     'identifier':'TaiwanStockTotalInstitutionalInvestors',
     'frequency':'daily', 'requires_key':'FINMIND_TOKEN',
     'usage':'大盤總計法人買賣',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🏢 個股財報', 'name':'配息歷史', 'source':'FinMind',
     'endpoint':'api.finmindtrade.com', 'identifier':'TaiwanStockDividend',
     'frequency':'yearly', 'requires_key':'FINMIND_TOKEN',
     'usage':'歷年現金/股票股利',
     'state_key':'t2_data.yearly', 'pingable':False, 'ping_url':None},
    {'category':'🏢 個股財報', 'name':'公司基本資料', 'source':'FinMind',
     'endpoint':'api.finmindtrade.com', 'identifier':'TaiwanStockInfo',
     'frequency':'event', 'requires_key':'FINMIND_TOKEN',
     'usage':'產業分類、上市日期',
     'state_key':None, 'pingable':True,
     'ping_url':'https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo&stock_id=2330&date=2024-01-01'},
    {'category':'🏢 個股財報', 'name':'MOPS 財報 備援', 'source':'MOPS',
     'endpoint':'mops.twse.com.tw/mops/web/ajax_t164sb03',
     'identifier':'ajax_t164sb03',
     'frequency':'quarterly', 'requires_key':None,
     'usage':'FinMind 失敗時的財報備援',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🏢 個股財報', 'name':'MOPS 月營收彙總 備援', 'source':'MOPS',
     'endpoint':'mops.twse.com.tw/nas/t21/sii/t21sc03_*.html',
     'identifier':'t21sc03',
     'frequency':'monthly', 'requires_key':None,
     'usage':'全市場月營收彙總',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🏢 個股財報', 'name':'Goodinfo 財報 備援', 'source':'Goodinfo',
     'endpoint':'goodinfo.tw/tw/StockFinDetail.asp',
     'identifier':'StockFinDetail',
     'frequency':'quarterly', 'requires_key':None,
     'usage':'IFRS 命名異常時的備援',
     'state_key':None, 'pingable':False, 'ping_url':None},

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 🇹🇼 六、台灣總經
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {'category':'🇹🇼 台灣總經', 'name':'M1B / M2 貨幣供給', 'source':'CBC',
     'endpoint':'cbc.gov.tw/public/Attachment/ms1.json', 'identifier':'ms1.json',
     'frequency':'monthly', 'requires_key':None,
     'usage':'資金動能（M1B-M2 黃金交叉）',
     'state_key':'m1b_m2_info.m1b_yoy', 'pingable':True,
     'ping_url':'https://www.cbc.gov.tw/public/Attachment/ms1.json'},
    {'category':'🇹🇼 台灣總經', 'name':'央行貨幣供給 API', 'source':'CBC',
     'endpoint':'cpx.cbc.gov.tw/API/DataAPI/Get', 'identifier':'cpx-api',
     'frequency':'monthly', 'requires_key':None,
     'usage':'CBC 官方 API 備援',
     'state_key':None, 'pingable':False, 'ping_url':None},
    # NDC 景氣燈號 v10.57.0 改抓 StockFeel + MacroMicro 雙源（舊 NDC 官方 JSON/CKAN 全失效）
    {'category':'🇹🇼 台灣總經', 'name':'NDC 景氣燈號（StockFeel）', 'source':'StockFeel',
     'endpoint':'stockfeel.com.tw/景氣對策信號-景氣指標-編制-國發會',
     'identifier':'NDC_signal_v2',
     'frequency':'monthly', 'requires_key':None,
     'usage':'台灣景氣綜合分數（45 分制，月更新）',
     'state_key':'macro_info.ndc_signal.score', 'pingable':False, 'ping_url':None},
    {'category':'🇹🇼 台灣總經', 'name':'NDC 景氣燈號（MacroMicro）', 'source':'MacroMicro',
     'endpoint':'macromicro.me/collections/10/tw-monitoring-indicators-relative',
     'identifier':'NDC_signal_v2_fallback',
     'frequency':'monthly', 'requires_key':None,
     'usage':'NDC 雙源 fallback',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🇹🇼 台灣總經', 'name':'財政部出口統計', 'source':'MOF',
     'endpoint':'service.mof.gov.tw/public/Data/statistic/trade',
     'identifier':'trade-csv',
     'frequency':'monthly', 'requires_key':None,
     'usage':'台灣月出口金額',
     'state_key':'macro_info.tw_export.yoy', 'pingable':False, 'ping_url':None},
    {'category':'🇹🇼 台灣總經', 'name':'MOF 出口 API', 'source':'MOF',
     'endpoint':'mof.gov.tw/API/statistics/trade/total', 'identifier':'trade-api',
     'frequency':'monthly', 'requires_key':None,
     'usage':'財政部出口備援',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🇹🇼 台灣總經', 'name':'FRED 台灣出口 備援', 'source':'FRED',
     'endpoint':'fred.stlouisfed.org/graph/fredgraph.csv',
     'identifier':'VALEXPTWM052N',
     'frequency':'monthly', 'requires_key':'FRED_API_KEY',
     'usage':'MOF 失敗時的台灣出口備援',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🇹🇼 台灣總經', 'name':'IMF M1B 備援', 'source':'IMF',
     'endpoint':'imf.org/external/datamapper/api/v1/MABMM301/TW',
     'identifier':'IMF-M1B',
     'frequency':'monthly', 'requires_key':None,
     'usage':'CBC 失敗時的 M1B 備援',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🇹🇼 台灣總經', 'name':'政府開放資料', 'source':'data.gov.tw',
     'endpoint':'data.gov.tw/api/3/action/package_search',
     'identifier':'package_search',
     'frequency':'event', 'requires_key':None,
     'usage':'通用備援查詢',
     'state_key':None, 'pingable':False, 'ping_url':None},

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 🏦 七、ETF / 基金
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {'category':'🏦 ETF / 基金', 'name':'ETF K線 OHLCV', 'source':'yfinance',
     'endpoint':'query1.finance.yahoo.com', 'identifier':'(各 ETF .TW)',
     'frequency':'daily', 'requires_key':None,
     'usage':'ETF 日線資料 (auto_adjust=True)',
     'state_key':'etf_single_data.price_df', 'pingable':False, 'ping_url':None},
    {'category':'🏦 ETF / 基金', 'name':'ETF 規模/Beta/費用率', 'source':'yfinance',
     'endpoint':'query1.finance.yahoo.com', 'identifier':'Ticker.info',
     'frequency':'daily', 'requires_key':None,
     'usage':'ETF AUM、Beta、Expense Ratio',
     'state_key':'etf_single_data.aum', 'pingable':False, 'ping_url':None},
    {'category':'🏦 ETF / 基金', 'name':'ETF NAV 淨值', 'source':'FinMind',
     'endpoint':'api.finmindtrade.com',
     'identifier':'TaiwanETFNetAssetValue',
     'frequency':'daily', 'requires_key':'FINMIND_TOKEN',
     'usage':'ETF 折溢價計算',
     'state_key':'etf_single_data.premium', 'pingable':False, 'ping_url':None},
    {'category':'🏦 ETF / 基金', 'name':'TWSE ETF API', 'source':'TWSE OpenAPI',
     'endpoint':'/v1/ETF/{op_id}', 'identifier':'ETF/v1',
     'frequency':'daily', 'requires_key':None,
     'usage':'ETF NAV 備援',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🏦 ETF / 基金', 'name':'MoneyDJ ETF 基本資料', 'source':'MoneyDJ',
     'endpoint':'moneydj.com/ETF/X/Basic/Basic0004.xdjhtm',
     'identifier':'Basic0004',
     'frequency':'event', 'requires_key':None,
     'usage':'ETF 成分股、追蹤指數',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🏦 ETF / 基金', 'name':'基金淨值', 'source':'MoneyDJ',
     'endpoint':'moneydj.com/funddj/yb/YP010001.djhtm',
     'identifier':'YP010001',
     'frequency':'daily', 'requires_key':None,
     'usage':'基金淨值查詢',
     'state_key':None, 'pingable':False, 'ping_url':None},

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 📰 八、新聞 RSS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {'category':'📰 新聞 RSS', 'name':'Google News (中文)', 'source':'Google News',
     'endpoint':'news.google.com/rss/search', 'identifier':'gnews-tw',
     'frequency':'event', 'requires_key':None,
     'usage':'個股/總經中文新聞',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'📰 新聞 RSS', 'name':'Google News (英文)', 'source':'Google News',
     'endpoint':'news.google.com/rss/search', 'identifier':'gnews-en',
     'frequency':'event', 'requires_key':None,
     'usage':'國際財經新聞',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'📰 新聞 RSS', 'name':'Reuters 商業新聞', 'source':'Reuters',
     'endpoint':'feeds.reuters.com/reuters/businessNews',
     'identifier':'reuters-business',
     'frequency':'event', 'requires_key':None,
     'usage':'國際財經事件追蹤',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'📰 新聞 RSS', 'name':'CNBC 新聞', 'source':'CNBC',
     'endpoint':'search.cnbc.com/rs/search/combinedcms/view.xml',
     'identifier':'cnbc-rss',
     'frequency':'event', 'requires_key':None,
     'usage':'美股/國際新聞',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'📰 新聞 RSS', 'name':'Yahoo Finance 新聞', 'source':'Yahoo Finance',
     'endpoint':'finance.yahoo.com/news/rssindex',
     'identifier':'yahoo-finance-rss',
     'frequency':'event', 'requires_key':None,
     'usage':'美股相關新聞',
     'state_key':None, 'pingable':False, 'ping_url':None},

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 🔄 九、三方備援
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {'category':'🔄 三方備援', 'name':'HiStock 融資餘額', 'source':'HiStock',
     'endpoint':'histock.tw/stock/margin.aspx', 'identifier':'margin.aspx',
     'frequency':'daily', 'requires_key':None,
     'usage':'融資餘額第 3 段備援',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🔄 三方備援', 'name':'Goodinfo 融資餘額', 'source':'Goodinfo',
     'endpoint':'goodinfo.tw/tw/ShowMarginChart.asp',
     'identifier':'goodinfo-margin',
     'frequency':'daily', 'requires_key':None,
     'usage':'融資餘額第 4 段備援（v10.55.0 新增）',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🔄 三方備援', 'name':'TWSE rwd dayMargin', 'source':'TWSE',
     'endpoint':'/rwd/zh/marginTrading/dayMargin', 'identifier':'dayMargin',
     'frequency':'daily', 'requires_key':None,
     'usage':'融資餘額第 5 段備援（v10.55.0 新增）',
     'state_key':None, 'pingable':False, 'ping_url':None},
    {'category':'🔄 三方備援', 'name':'Wearn 早期資料', 'source':'Wearn',
     'endpoint':'stock.wearn.com/margin.asp', 'identifier':'wearn-margin',
     'frequency':'daily', 'requires_key':None,
     'usage':'多層備援的最後一線',
     'state_key':None, 'pingable':False, 'ping_url':None},

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 🤖 十、AI 服務
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {'category':'🤖 AI 服務', 'name':'Google Gemini', 'source':'Google',
     'endpoint':'generativelanguage.googleapis.com/v1beta',
     'identifier':'gemini-2.5-flash',
     'frequency':'event', 'requires_key':'GEMINI_API_KEY',
     'usage':'AI 整合報告、總經摘要',
     'state_key':None, 'pingable':False, 'ping_url':None},
]


# ══════════════════════════════════════════════════════════════════════════════
# 工具函式
# ══════════════════════════════════════════════════════════════════════════════
def get_state_value(session_state, key_path: str | None) -> Any:
    """從 session_state 用 dot 路徑取值。
    e.g. 'macro_info.us_core_cpi.date' →
         session_state['macro_info']['us_core_cpi']['date']
    """
    if not key_path:
        return None
    try:
        parts = key_path.split('.')
        cur = session_state.get(parts[0]) if hasattr(session_state, 'get') else None
        for p in parts[1:]:
            if cur is None:
                return None
            if isinstance(cur, dict):
                cur = cur.get(p)
            elif hasattr(cur, p):
                cur = getattr(cur, p)
            else:
                return None
        return cur
    except Exception:
        return None


def get_categories() -> list[str]:
    """回傳所有類別（依註冊順序去重）"""
    _seen, _out = set(), []
    for _e in DATA_REGISTRY:
        _c = _e.get('category', '其他')
        if _c not in _seen:
            _seen.add(_c)
            _out.append(_c)
    return _out


def get_by_category(category: str) -> list[dict]:
    """取得指定類別的所有資料源"""
    return [e for e in DATA_REGISTRY if e.get('category') == category]


def get_pingable_endpoints() -> list[dict]:
    """取得可即時測試的端點清單"""
    return [e for e in DATA_REGISTRY if e.get('pingable') and e.get('ping_url')]


def ping_endpoint(entry: dict, timeout: int = 8) -> dict:
    """即時測試單一端點連線。
    回傳 {'ok': bool, 'status': int|None, 'elapsed_ms': int, 'error': str|None}
    走 proxy_helper.fetch_url() → 自動經 NAS Proxy
    """
    import time as _t
    _start = _t.time()
    try:
        from proxy_helper import fetch_url
        _resp = fetch_url(entry['ping_url'], timeout=timeout)
        _elapsed = int((_t.time() - _start) * 1000)
        if _resp is None:
            return {'ok': False, 'status': None, 'elapsed_ms': _elapsed,
                    'error': 'fetch_url 回傳 None'}
        _ok = _resp.status_code == 200
        return {'ok': _ok, 'status': _resp.status_code,
                'elapsed_ms': _elapsed,
                'error': None if _ok else f'HTTP {_resp.status_code}'}
    except Exception as _e:
        _elapsed = int((_t.time() - _start) * 1000)
        return {'ok': False, 'status': None, 'elapsed_ms': _elapsed,
                'error': str(_e)[:80]}


def get_summary_stats() -> dict:
    """計算註冊表摘要統計"""
    _total = len(DATA_REGISTRY)
    _connected = sum(1 for e in DATA_REGISTRY if e.get('state_key'))
    _pingable = sum(1 for e in DATA_REGISTRY if e.get('pingable'))
    _need_key = sum(1 for e in DATA_REGISTRY if e.get('requires_key'))
    _by_cat = {}
    for _e in DATA_REGISTRY:
        _c = _e.get('category', '其他')
        _by_cat[_c] = _by_cat.get(_c, 0) + 1
    return {
        'total': _total,
        'connected': _connected,
        'pingable': _pingable,
        'need_key': _need_key,
        'by_category': _by_cat,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 📖 EDU_GUIDE — 指標解讀手冊（依 identifier 對應）
# ══════════════════════════════════════════════════════════════════════════════
# 設計原則：新人看了就懂。每筆指標回答 6 個問題：
#   1. meaning           — 白話這是什麼？
#   2. how_to_read       — 數字到了哪個門檻代表什麼訊號？
#   3. pair_with         — 不能只看單一指標，要搭配誰一起看？
#   4. historical_anchor — 歷史上的關鍵數字定錨（讓人有比例尺）
#   5. upstream          — 上游：誰會影響這個指標？
#   6. downstream        — 下游：這個指標會影響誰？
EDU_GUIDE: dict[str, dict[str, Any]] = {
    # ── 美國總經 ──────────────────────────────────────────────────
    'CPILFESL': {
        'meaning': '美國「核心」消費者物價指數年增率（剔除能源、食物波動），是 Fed 升降息最看重的通膨溫度計。',
        'how_to_read': [
            ('< 2%', '🟢 通膨控制中，降息題材濃厚'),
            ('2 ~ 3%', '🟡 黏性通膨，Fed 維持高利率不動'),
            ('> 3%', '🔴 通膨頑強，升息壓力大、股債雙殺風險'),
            ('連 3 個月下滑', '🔼 趨勢轉鴿，市場提前 Pricing 降息'),
        ],
        'pair_with': ['ISM PMI（NAPM）', '美債 10Y（^TNX）', '美元指數（DXY）'],
        'historical_anchor': '2022 通膨高峰 6.6%（40 年新高）｜2008 雷曼 2.5%｜Fed 目標 2.0%',
        'upstream': '油價、薪資成長、住房成本（OER）、供應鏈成本',
        'downstream': '影響 Fed 利率決策 → 美元 → 美債殖利率 → 美股估值（殖利率上 1%，PE 下調約 10–15%）',
    },
    'NAPM': {
        'meaning': 'ISM 製造業採購經理人指數，採購主管問卷彙總，領先 GDP 約 3–6 個月。',
        'how_to_read': [
            ('> 50', '🟢 製造業擴張'),
            ('= 50', '🟡 中性線（榮枯分水嶺）'),
            ('< 50', '🔴 製造業萎縮（通常伴隨股市修正）'),
            ('< 45 持續 3 月', '🚨 衰退強烈訊號'),
        ],
        'pair_with': ['美國核心 CPI（CPILFESL）', '台灣出口 YoY', '費半 SOX'],
        'historical_anchor': '2008 雷曼跌至 33.1｜2020 疫情 41.5｜2021 復甦高點 63.7',
        'upstream': '訂單能見度、企業 CapEx、全球需求',
        'downstream': '台灣出口（領先 1–2 季）→ 台股科技股獲利 → ^SOX & ^TWII',
    },
    # ── 國際金融 ──────────────────────────────────────────────────
    '^VIX': {
        'meaning': 'CBOE 用 S&P 500 選擇權隱含波動度算出的「市場恐慌指數」，俗稱華爾街的恐慌計。',
        'how_to_read': [
            ('< 15', '🟢 市場平靜，多頭氛圍'),
            ('15 ~ 20', '🟡 正常波動'),
            ('20 ~ 30', '🟠 警戒區，留意修正'),
            ('> 30', '🔴 恐慌爆發（通常已是底部區）'),
            ('> 40', '🚨 系統性風險（極佳逢低買點）'),
        ],
        'pair_with': ['S&P 500（^GSPC）', '美元指數（DXY）', 'Put/Call Ratio'],
        'historical_anchor': '2008 雷曼 89.5｜2020 疫情 82.7｜2022 通膨高峰 36｜平時 12–18',
        'upstream': 'S&P 500 選擇權買方需求、地緣政治事件、Fed 政策意外',
        'downstream': 'VIX 急升 → 風險資產拋售 → 美元/日圓避險買盤 → 新興市場資金外流',
    },
    'DX-Y.NYB': {
        'meaning': '美元對六大主要貨幣（歐元 57.6% + 日圓 13.6% + 英鎊 11.9% + 加幣/瑞典克朗/瑞郎）的加權匯率指數。',
        'how_to_read': [
            ('< 95', '🟢 美元弱勢，新興市場資金流入、原物料漲'),
            ('95 ~ 105', '🟡 中性區間'),
            ('> 105', '🔴 美元強勢，外資撤離新興市場、台股壓力'),
            ('> 110', '🚨 強美元危機，全球流動性緊縮'),
        ],
        'pair_with': ['美債 10Y（^TNX）', '台幣匯率', 'VIX', '銅博士（HG=F）'],
        'historical_anchor': '2008 雷曼避險高 88｜2014 升息循環 100｜2022 強勢美元 114｜歷史平均 ~95',
        'upstream': 'Fed 利率（升息 → 美元強）、美國經濟相對其他國強弱、避險需求',
        'downstream': '直接影響：原物料（負相關）、新興市場資產、外資對台股流入流出',
    },
    '^TNX': {
        'meaning': '美國 10 年期公債殖利率，全球資產定價的「無風險錨」，被稱為金融市場的引力。',
        'how_to_read': [
            ('< 2%', '🟢 寬鬆環境，成長股估值放大'),
            ('2 ~ 4%', '🟡 中性區間'),
            ('> 4%', '🟠 高利率壓抑成長股估值'),
            ('> 5%', '🔴 估值殺戮區（2022/10、2023/10 雙頂歷史）'),
            ('快速上升 50bp/月', '🚨 估值殺戮加速'),
        ],
        'pair_with': ['美國核心 CPI', '美元指數（DXY）', 'S&P 500'],
        'historical_anchor': '2008 雷曼 2.04%｜2020 疫情低 0.51%｜2023 高點 4.99%｜歷史平均 4.5%',
        'upstream': 'Fed 利率預期、通膨預期、美債供需（QT）、財政赤字',
        'downstream': '殖利率 +1% → 科技股 PE 縮水 ~15%（DCF 折現率敏感）→ 那斯達克／台股科技權值股下殺',
    },
    '^SOX': {
        'meaning': '費城半導體指數，全球半導體景氣最領先的籌碼面溫度計，與台股權值股（台積電/聯發科）連動 0.85+。',
        'how_to_read': [
            ('創新高', '🟢 半導體景氣熱絡，台股科技股有撐'),
            ('跌破年線', '🟠 趨勢轉弱，外資對台股科技股減碼'),
            ('SOX vs ^TWII 背離', '⚠️ 領先訊號：費半轉弱通常領先台股 2–4 週'),
        ],
        'pair_with': ['台股加權指數（^TWII）', '台積電 ADR（TSM）', 'ISM PMI'],
        'historical_anchor': '2018/12 中美貿易戰低點｜2022/10 庫存修正低｜2024 AI 狂熱新高',
        'upstream': 'NVDA / AMD / AVGO / 台積電 ADR 權值股價 → 全球半導體訂單能見度',
        'downstream': '台股科技權值股（台積電 / 聯發科 / 鴻海）→ ^TWII 加權指數',
    },
    # ── 台股大盤 ──────────────────────────────────────────────────
    'BWIBBU_d': {
        'meaning': 'TWSE 每日盤後公布的全市場個股基本面三劍客：本益比（PE）／股價淨值比（PB）／殖利率（Y）。',
        'how_to_read': [
            ('殖利率 ≥ 7%', '🟢 高息網入場門檻（💎 高息網模組）'),
            ('PE < 15 且殖利率 > 5%', '🟢 價值股雙重訊號'),
            ('PB < 1', '⚠️ 破淨警示（需檢查是否地雷股）'),
            ('PE > 30', '🔴 高估值，本夢比股票'),
        ],
        'pair_with': ['月營收 YoY', '個股法人買賣超', 'M1B-M2 利差'],
        'historical_anchor': '台股長期殖利率 ~3.5%｜PE 中位數 ~14｜2008 低點 PB 約 1.2',
        'upstream': '盤後收盤價 + 公司公告殖利率（現金股利）',
        'downstream': '提供 💎 高息網篩選資料源；散戶基本面選股依據',
    },
    # ── 籌碼 ──────────────────────────────────────────────────────
    'BFI82U': {
        'meaning': 'TWSE 每日盤後公布的「外資 + 投信 + 自營」三大法人現貨買賣超總計，台股最權威的籌碼面風向。',
        'how_to_read': [
            ('外資 + 投信同向買超', '🟢 法人聯手作多，趨勢延續性高'),
            ('外資連續買超 5 日', '🟢 中期趨勢確立'),
            ('外資投信對作', '🟡 訊號雜訊，看大盤方向決定'),
            ('外資連續賣超 + 期貨空單擴大', '🔴 系統性下殺前兆'),
        ],
        'pair_with': ['外資期貨留倉', '融資餘額（散戶反向指標）', '台幣匯率'],
        'historical_anchor': '單日歷史最大買超 ~600 億｜單日最大賣超 ~700 億（2022/10/24）',
        'upstream': '外資匯入匯出（看美元指數）、MSCI 權重調整、季底作帳',
        'downstream': '影響加權指數、權值股股價、台幣匯率（買超台股需先換台幣 → 台幣升值）',
    },
    'MI_MARGN': {
        'meaning': '融資餘額 = 散戶向券商借錢買股的未還金額，是「散戶情緒」最直接的反向指標。',
        'how_to_read': [
            ('< 1500 億', '🟢 散戶冷卻，籌碼乾淨'),
            ('1500 ~ 2200 億', '🟡 正常區間'),
            ('> 2500 億', '🔴 散戶過熱，注意主力出貨'),
            ('融資快速增加但指數不漲', '🚨 多殺多前兆'),
        ],
        'pair_with': ['三大法人買賣超（反向看）', '台股年線乖離（^TWII）'],
        'historical_anchor': '2007 高峰 4400 億（2008 崩盤前）｜2022/4 高點 2900 億｜健康區 1500–2000 億',
        'upstream': '散戶看多情緒、券商融資利率、金管會限制',
        'downstream': '融資擴張 → 散戶進場 → 大戶通常開始減碼；急殺時融資斷頭加速跌勢',
    },
    '前五大留倉': {
        'meaning': '期交所每日公布的「台指期前五大交易人」未平倉淨部位（多單-空單，單位：口）。代表市場頂級主力（投信、外資、自營）對未來方向的下注，是台股最強的領先籌碼指標之一。',
        'how_to_read': [
            ('> +5,000 口', '🟢 前五大主力顯著淨多，多頭趨勢有撐'),
            ('±5,000 口內', '🟡 中性，多空尚未明確表態'),
            ('< -5,000 口', '🟠 前五大轉空，注意修正壓力'),
            ('接近 -10,000 口', '🔴 嚴重警訊（策略3 警戒線），系統性下殺前兆'),
            ('與外資期貨同向', '✅ 一致性強，趨勢可信度高'),
        ],
        'pair_with': ['外資期貨留倉（外資大小）', '前十大留倉', '選 PCR'],
        'historical_anchor': '健康多頭區 +3,000 ~ +8,000 口｜2022/10 修正期低點接近 -12,000 口｜2024 AI 熱潮高點 +10,000 口',
        'upstream': '外資匯出匯入、月底季底結算、突發地緣事件、Fed 利率決議',
        'downstream': '領先大盤 1-3 日；當前五大空單擴大且加權指數仍高 → 出貨訊號 → 短中期回檔',
    },
    '前十大留倉': {
        'meaning': '期交所每日公布的「台指期前十大交易人」未平倉淨部位（口）。涵蓋更廣的主力與部分中型法人，**注意：包含反向 ETF（如 00632R）的避險空單**，因此真實方向性空單通常少於帳面顯示。',
        'how_to_read': [
            ('> +10,000 口', '🟢 前十大顯著淨多，趨勢健康'),
            ('±10,000 口內', '🟡 中性，主力觀望'),
            ('< -10,000 口', '🟠 警戒區，但需扣除反向 ETF 避險口數'),
            ('接近 -20,000 口', '🔴 嚴重警訊（策略3 警戒線）'),
            ('前十大-前五大差距過大', '⚠️ 中型法人與頂級主力分歧，方向不明'),
        ],
        'pair_with': ['前五大留倉（更純粹）', '外資期貨留倉', '反向 ETF 規模'],
        'historical_anchor': '健康區 +5,000 ~ +15,000 口｜2022 修正期低點 -25,000 口｜避險空單常態 -8,000 ~ -12,000 口',
        'upstream': '頂級主力部位 + 反向 ETF 避險需求 + 投信季底調整',
        'downstream': '與前五大背離時通常是反向 ETF 在動 → 不必過度解讀單日數字，須看 5 日均量與流向',
    },
    # ── 台灣總經 ─────────────────────────────────────────────────
    'ms1.json': {
        'meaning': '央行每月公布的貨幣供給：M1B = 通貨 + 活存（活錢），M2 = M1B + 定存。M1B-M2 利差代表「活錢比例變化」。',
        'how_to_read': [
            ('M1B YoY > M2 YoY 且擴大', '🟢 黃金交叉，資金寬鬆，多頭啟動'),
            ('M1B YoY = M2 YoY', '🟡 利差收斂，留意趨勢轉折'),
            ('M1B YoY < M2 YoY', '🔴 死亡交叉，資金緊縮，熊市風險'),
            ('M1B YoY > 10%', '🚀 資金狂潮，股市熱絡'),
        ],
        'pair_with': ['NDC 景氣燈號', '加權指數（^TWII）', '融資餘額'],
        'historical_anchor': '2009 復甦 M1B YoY 26%｜2020 疫情寬鬆 21%｜2022 緊縮跌至 4%以下',
        'upstream': '央行利率政策、外匯存底變動（外資匯入 → M1B 升）、企業現金流',
        'downstream': '錢從定存搬到活存 → 股市資金動能（領先大盤 6–9 個月）',
    },
    'NDC_signal': {
        'meaning': '國發會每月公布的景氣綜合判斷分數（9 項指標加總，總分 45），用顏色燈號表示景氣熱度。',
        'how_to_read': [
            ('38–45 分（紅燈）', '🔴 景氣過熱，股市相對高點警示'),
            ('32–37 分（黃紅燈）', '🟠 趨熱，留意過熱風險'),
            ('23–31 分（綠燈）', '🟢 穩定成長，最佳持股期'),
            ('17–22 分（黃藍燈）', '🟡 趨穩，謹慎觀望'),
            ('9–16 分（藍燈）', '🔵 低迷，但股市常領先觸底反彈'),
        ],
        'pair_with': ['台灣出口 YoY', 'M1B-M2 利差', 'ISM PMI'],
        'historical_anchor': '2008 金融風暴連 9 個月藍燈｜2021 連 10 個月紅燈（出口爆發）｜健康區 24–34',
        'upstream': '出口、工業生產、批發零售、就業 9 大指標加總',
        'downstream': '常被視為股市的「同時指標」，但藍燈轉黃藍時股市已反彈過了',
    },
    'VALEXPTWM052N': {
        'meaning': '台灣每月出口金額年增率，全球景氣與台廠訂單能見度的核心指標（台灣 GDP 60% 來自出口）。',
        'how_to_read': [
            ('YoY > +20%', '🚀 出口爆發，台股科技股有撐'),
            ('YoY > 0%', '🟢 出口擴張'),
            ('YoY < 0%', '🔴 出口衰退（通常台股年線下彎）'),
            ('連 3 月衰退', '🚨 結構性衰退警訊'),
        ],
        'pair_with': ['ISM PMI', '費半 SOX', '台積電 ADR'],
        'historical_anchor': '2009 雷曼後 -41%｜2021 復甦 +49%｜2023 修正 -16%｜長期均值 +5%',
        'upstream': '美國 ISM PMI（領先 1–2 季）、全球半導體景氣、AI 訂單能見度',
        'downstream': '台股企業獲利 → ^TWII 走勢、台幣匯率（出口好台幣升）、月營收',
    },
}


def get_edu(identifier: str | None) -> dict | None:
    """依 identifier 取得教學資料；無對應則回 None。
    e.g. get_edu('CPILFESL') → {'meaning': ..., 'how_to_read': [...], ...}
    """
    if not identifier:
        return None
    return EDU_GUIDE.get(identifier)


def get_edu_count() -> int:
    """已撰寫教學內容的指標數"""
    return len(EDU_GUIDE)


def _esc(s: Any) -> str:
    """HTML escape（防止指標名稱含 < > & 時破版）"""
    if s is None:
        return ''
    return (str(s)
            .replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def render_edu_card_html(entry: dict, edu: dict) -> str:
    """渲染單一指標的教學卡 HTML 字串。
    使用 dark theme（GitHub 風格），可直接 st.markdown(html, unsafe_allow_html=True)。
    """
    _name = _esc(entry.get('name', ''))
    _id = _esc(entry.get('identifier', ''))
    _source = _esc(entry.get('source', ''))
    _freq = _esc(entry.get('frequency', ''))

    _meaning = _esc(edu.get('meaning', ''))
    _hist = _esc(edu.get('historical_anchor', ''))
    _up = _esc(edu.get('upstream', ''))
    _down = _esc(edu.get('downstream', ''))
    _pairs = edu.get('pair_with', []) or []
    _rules = edu.get('how_to_read', []) or []

    # 判讀規則 → 表格
    _rules_html = ''
    if _rules:
        _rule_rows = ''.join(
            f'<tr><td style="padding:6px 10px;font-family:monospace;color:#a5d6ff;'
            f'border-bottom:1px solid #21262d;white-space:nowrap;">{_esc(_th)}</td>'
            f'<td style="padding:6px 10px;color:#e6edf3;border-bottom:1px solid #21262d;">'
            f'{_esc(_sig)}</td></tr>'
            for _th, _sig in _rules
        )
        _rules_html = (
            '<div style="margin:8px 0 4px;font-size:11px;color:#8b949e;font-weight:600;">'
            '📐 怎麼判讀（門檻 → 訊號）</div>'
            f'<table style="width:100%;border-collapse:collapse;font-size:12px;'
            f'background:#0d1117;border-radius:6px;overflow:hidden;'
            f'border:1px solid #21262d;">{_rule_rows}</table>'
        )

    # 搭配指標 → chip
    _pair_html = ''
    if _pairs:
        _chips = ' '.join(
            f'<span style="display:inline-block;background:#161b22;border:1px solid #30363d;'
            f'color:#79c0ff;padding:2px 9px;margin:2px;border-radius:11px;font-size:11px;">'
            f'{_esc(_p)}</span>'
            for _p in _pairs
        )
        _pair_html = (
            '<div style="margin:8px 0 2px;font-size:11px;color:#8b949e;font-weight:600;">'
            '🔗 搭配看的指標</div>'
            f'<div>{_chips}</div>'
        )

    # 上下游關係（只在有資料時顯示）
    _flow_html = ''
    if _up or _down:
        _up_block = (
            f'<div style="flex:1;min-width:0;"><div style="font-size:10px;color:#8b949e;'
            f'margin-bottom:2px;">⬆️ 上游因（誰影響它）</div>'
            f'<div style="font-size:12px;color:#c9d1d9;line-height:1.5;">{_up}</div></div>'
            if _up else ''
        )
        _down_block = (
            f'<div style="flex:1;min-width:0;"><div style="font-size:10px;color:#8b949e;'
            f'margin-bottom:2px;">⬇️ 下游果（它影響誰）</div>'
            f'<div style="font-size:12px;color:#c9d1d9;line-height:1.5;">{_down}</div></div>'
            if _down else ''
        )
        _flow_html = (
            '<div style="margin-top:8px;display:flex;gap:14px;flex-wrap:wrap;">'
            f'{_up_block}{_down_block}</div>'
        )

    # 歷史錨點
    _hist_html = ''
    if _hist:
        _hist_html = (
            f'<div style="margin-top:8px;background:#1c2128;border-left:3px solid #d29922;'
            f'padding:6px 10px;border-radius:0 4px 4px 0;font-size:11px;color:#c9d1d9;">'
            f'<b style="color:#d29922;">📊 歷史錨點：</b>{_hist}</div>'
        )

    return (
        f'<div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;'
        f'padding:14px 16px;margin:10px 0;">'
        # 標題列
        f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;'
        f'border-bottom:1px solid #21262d;padding-bottom:8px;margin-bottom:10px;">'
        f'<span style="font-size:14px;font-weight:700;color:#e6edf3;">{_name}</span>'
        f'<code style="background:#161b22;color:#a5d6ff;padding:1px 8px;border-radius:4px;'
        f'font-size:11px;">{_id}</code>'
        f'<span style="font-size:10px;color:#8b949e;">{_source} ｜ {_freq}</span>'
        f'</div>'
        # 白話定義
        f'<div style="font-size:12px;color:#c9d1d9;line-height:1.6;">'
        f'<b style="color:#3fb950;">💡 是什麼：</b>{_meaning}</div>'
        # 判讀
        f'{_rules_html}'
        # 搭配
        f'{_pair_html}'
        # 上下游
        f'{_flow_html}'
        # 歷史
        f'{_hist_html}'
        f'</div>'
    )
