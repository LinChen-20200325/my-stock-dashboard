"""
data_config.py — 資料來源優先順序與快取 TTL 設定 (v4.1)
集中管理所有資料抓取策略，避免散落各處的魔術數字。
"""

# 各資料類型的來源優先順序（由高到低）
PRIORITY = {
    "institutional":   ["TWSE", "FinMind", "Cache"],
    "margin_balance":  ["FinMind", "Wearn", "TWSE", "Cache"],
    "futures":         ["TAIFEX", "FinMind", "Cache"],
    "volume":          ["TWSE_OpenAPI", "YFinance", "Cache"],
    "index":           ["YFinance", "TWSE"],
    "adl":             ["Cache", "YFinance"],
}

# 快取存活時間（秒）— 短=當日關鍵數據，長=歷史數據
TTL_CONFIG = {
    "institutional":   1800,   # 30 分鐘 — 法人買賣（收盤後更新，日頻）
    "margin_balance":  1800,   # 30 分鐘 — 融資融券餘額（日頻）
    "futures":         900,    # 15 分鐘 — 期貨選擇權法人
    "volume":          600,    # 10 分鐘 — 成交量
    "historical":      86400,  # 24 小時 — 歷史/不常變的資料
}

# pickle 快取根目錄（Streamlit Cloud /tmp 重啟後自動清除）
PKL_DIR = "/tmp/stock_cache"
