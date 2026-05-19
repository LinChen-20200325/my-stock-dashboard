"""Google Sheet 持股組合雲端儲存 (PR #5)

Schema (單一 worksheet `portfolios`)：
    name | ticker | lots | avg_price | updated_at

多組命名 = 多列共用同一 worksheet；同一個 name 多列 = 該組合的所有持股。

依賴
====
- gspread>=6.0
- google-auth>=2.0

呼叫端
======
- etf_tab_portfolio.py 經「💾 雲端儲存」expander 取用

設計
====
- 純函式 API：is_configured / list_portfolios / load_portfolio / save_portfolio / delete_portfolio
- 例外不吞，往上拋給 caller（UI 層用 try/except 顯示 st.error）
- 客戶端與 worksheet handle 用 st.cache_resource 共享，避免重複 OAuth
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

try:
    import streamlit as st
except ImportError:
    st = None

_WORKSHEET_NAME = 'portfolios'
_HEADERS = ['name', 'ticker', 'lots', 'avg_price', 'updated_at']


def is_configured() -> bool:
    """檢查 st.secrets 是否備齊 `portfolio_sheet_id` + `gcp_service_account`。"""
    if st is None:
        return False
    try:
        _ = st.secrets['portfolio_sheet_id']
        _ = st.secrets['gcp_service_account']
        return True
    except (KeyError, FileNotFoundError, AttributeError):
        return False


def _get_worksheet():
    """取得 (或建立) `portfolios` worksheet，並確保 header 列存在。"""
    import gspread
    from google.oauth2.service_account import Credentials

    sheet_id = st.secrets['portfolio_sheet_id']
    sa_info = dict(st.secrets['gcp_service_account'])

    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open_by_key(sheet_id)

    try:
        ws = sh.worksheet(_WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=_WORKSHEET_NAME, rows=200, cols=10)
        ws.append_row(_HEADERS)
        return ws

    first_row = ws.row_values(1)
    if first_row != _HEADERS:
        ws.update('A1:E1', [_HEADERS])
    return ws


def _ws():
    """取得 worksheet handle。Streamlit 環境用 cache_resource 共享。"""
    if st is None:
        return _get_worksheet()
    cached = getattr(_ws, '_cached', None)
    if cached is None:
        cached = st.cache_resource(_get_worksheet)
        _ws._cached = cached
    return cached()


def _all_records() -> list[dict[str, Any]]:
    """回傳全表（含 header 後的所有列）為 dict list。"""
    return _ws().get_all_records()


def list_portfolios() -> list[str]:
    """列出所有不重複的組合名稱（按字母排序）。"""
    names: set[str] = set()
    for rec in _all_records():
        n = str(rec.get('name', '')).strip()
        if n:
            names.add(n)
    return sorted(names)


def load_portfolio(name: str) -> list[dict[str, Any]]:
    """讀取指定名稱的組合，回傳 `[{ticker, lots, avg_price}, ...]`。"""
    name = (name or '').strip()
    if not name:
        return []
    out: list[dict[str, Any]] = []
    for rec in _all_records():
        if str(rec.get('name', '')).strip() != name:
            continue
        tk = str(rec.get('ticker', '')).strip()
        if not tk:
            continue
        try:
            lots = float(rec.get('lots') or 0)
            avg = float(rec.get('avg_price') or 0)
        except (TypeError, ValueError):
            continue
        if lots <= 0 or avg <= 0:
            continue
        out.append({'ticker': tk, 'lots': lots, 'avg_price': avg})
    return out


def save_portfolio(name: str, rows: list[dict[str, Any]]) -> int:
    """儲存（覆蓋）指定名稱的組合，回傳寫入的列數。

    rows 預期格式：每筆含 `ticker` / `lots` / `avg_price`。其它欄位忽略。
    """
    name = (name or '').strip()
    if not name:
        raise ValueError('組合名稱不可為空')
    if not rows:
        raise ValueError('組合內容不可為空')

    ws = _ws()
    existing = ws.get_all_values()
    keep_rows = [r for r in existing[1:] if (r and r[0].strip() != name)]

    ts = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_rows = []
    for r in rows:
        tk = str(r.get('ticker', '')).strip().upper()
        if not tk:
            continue
        try:
            lots = float(r.get('lots') or 0)
            avg = float(r.get('avg_price') or 0)
        except (TypeError, ValueError):
            continue
        if lots <= 0 or avg <= 0:
            continue
        new_rows.append([name, tk, lots, avg, ts])

    if not new_rows:
        raise ValueError('無有效持股可儲存（檢查代號、張數、均價）')

    ws.clear()
    ws.append_row(_HEADERS)
    if keep_rows:
        ws.append_rows(keep_rows)
    ws.append_rows(new_rows)
    return len(new_rows)


def delete_portfolio(name: str) -> int:
    """刪除指定名稱的組合（所有持股列），回傳刪除的列數。"""
    name = (name or '').strip()
    if not name:
        return 0
    ws = _ws()
    existing = ws.get_all_values()
    if len(existing) <= 1:
        return 0
    keep_rows = [r for r in existing[1:] if (r and r[0].strip() != name)]
    deleted = (len(existing) - 1) - len(keep_rows)
    if deleted == 0:
        return 0
    ws.clear()
    ws.append_row(_HEADERS)
    if keep_rows:
        ws.append_rows(keep_rows)
    return deleted
