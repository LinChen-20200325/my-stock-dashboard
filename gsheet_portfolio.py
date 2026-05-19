"""Google Sheet 持股組合雲端儲存 (PR #5 + OAuth 擴充)

Schema (單一 worksheet `portfolios`)：
    name | ticker | lots | avg_price | updated_at

多組命名 = 多列共用同一 worksheet；同一個 name 多列 = 該組合的所有持股。

雙模式認證
==========
- OAuth（推薦）：使用者在 sidebar 用 Google 登入，自帶 Sheet
  - secrets：`[google_oauth]` 或 in-app wizard 設定（client_id/secret/redirect_uri）
  - 個人 Sheet ID：UI 輸入 → session_state['portfolio_sheet_id']
- Service Account（向後相容）：管理員部署
  - secrets：`portfolio_sheet_id` + `[gcp_service_account]`

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
- OAuth client 由 oauth_state._get_oauth_client() 提供
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


def _oauth_active() -> bool:
    """OAuth 模式：已設 OAuth Client + 已登入 + 有 sheet id。"""
    if st is None:
        return False
    try:
        from oauth_state import is_oauth_configured
    except Exception:
        return False
    if not is_oauth_configured():
        return False
    if not st.session_state.get('gsheet_tokens'):
        return False
    if not _get_active_sheet_id():
        return False
    return True


def _sa_configured() -> bool:
    """Service Account 模式：兩個 secrets 都有。"""
    if st is None:
        return False
    try:
        _ = st.secrets['portfolio_sheet_id']
        _ = st.secrets['gcp_service_account']
        return True
    except (KeyError, FileNotFoundError, AttributeError):
        return False


def is_configured() -> bool:
    """OAuth 已登入＋有 Sheet ID，或 SA 已備齊；任一條件即可。"""
    return _oauth_active() or _sa_configured()


def _get_active_sheet_id() -> str:
    """OAuth 模式下取使用者輸入的 sheet id；SA 模式回 secrets 的值。"""
    if st is None:
        return ''
    sid = str(st.session_state.get('portfolio_sheet_id', '') or '').strip()
    if sid:
        return sid
    try:
        return str(st.secrets.get('portfolio_sheet_id', '') or '').strip()
    except (KeyError, FileNotFoundError, AttributeError):
        return ''


def _has_oauth_tokens() -> bool:
    """是否已透過 OAuth 登入（不要求 Sheet ID 已設定）。

    `_oauth_active()` 額外要求 sheet_id，會擋掉「列檔挑 Sheet」的場景；
    建構 client 只需要看「有沒有登入 + OAuth Client 有設」。

    用 `is_oauth_configured()` 動態解析（取代 stale module-level `_oauth_configured`）—
    in-app wizard 套用 OAuth config 後不必重啟 streamlit 也能立刻生效。
    """
    if st is None:
        return False
    try:
        from oauth_state import is_oauth_configured
    except Exception:
        return False
    if not is_oauth_configured():
        return False
    if not st.session_state.get('gsheet_tokens'):
        return False
    return True


def _build_client():
    """依當前模式建一個 gspread client。OAuth 優先；fallback SA。

    OAuth 判斷只看「有 token + 有 OAuth Client」，不綁 sheet_id —
    讓「列檔挑 Sheet」流程能在 sheet_id 還沒設定前先建 client。
    """
    if _has_oauth_tokens():
        from oauth_state import _get_oauth_client
        cli = _get_oauth_client()
        if cli is not None:
            return cli
    # Fallback: Service Account（OAuth 沒登入或建 client 失敗才走這條）
    if not _sa_configured():
        raise RuntimeError(
            '尚未登入 Google 也未設定 Service Account — 請先「🔐 用 Google 登入」'
            '或請管理員設定 `[gcp_service_account]` secret')
    import gspread
    from google.oauth2.service_account import Credentials
    sa_info = dict(st.secrets['gcp_service_account'])
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    return gspread.authorize(creds)


def _get_worksheet():
    """取得 (或建立) `portfolios` worksheet，並確保 header 列存在。"""
    import gspread

    sheet_id = _get_active_sheet_id()
    if not sheet_id:
        raise RuntimeError('尚未設定 Sheet ID（OAuth 模式請在雲端儲存區塊輸入）')
    client = _build_client()
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
    """取得 worksheet handle。每次重新建立（OAuth token 可能 refresh）。"""
    return _get_worksheet()


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


def list_user_sheets(folder_id: str = '') -> list[dict]:
    """OAuth 模式列出使用者 Google Drive 內 Spreadsheets。

    Args:
        folder_id: 若提供，僅列出此資料夾內的 Sheets（gspread 6.x 原生支援）；
                   留空則列全部（既有行為）。

    需要 OAuth scope `drive.metadata.readonly`（infra/oauth.py 已內建）。
    回傳 [{'id': ..., 'name': ...}, ...] 依名稱排序；非 OAuth 模式回空 list。
    """
    if not _has_oauth_tokens():
        # 未登入 OAuth → 無法列檔（SA 沒 drive.metadata.readonly scope）
        return []
    client = _build_client()
    try:
        files = client.list_spreadsheet_files(
            folder_id=(folder_id.strip() or None))
    except Exception as e:
        raise RuntimeError(f'列出 Drive Sheets 失敗：[{type(e).__name__}] {e}') from e
    out: list[dict] = []
    for f in (files or []):
        _id = f.get('id') if isinstance(f, dict) else getattr(f, 'id', None)
        _nm = f.get('name') if isinstance(f, dict) else getattr(f, 'name', None)
        if _id and _nm:
            out.append({'id': _id, 'name': _nm})
    out.sort(key=lambda x: x['name'].lower())
    return out


def list_user_folders() -> list[dict]:
    """OAuth 模式列出使用者 Google Drive 內所有資料夾（含共享）。

    透過 gspread client 的 http_client 直接打 Drive v3 API；
    需要 OAuth scope `drive.metadata.readonly`。
    回傳 [{'id': ..., 'name': ...}, ...] 依名稱排序；非 OAuth 模式回空 list。
    """
    if not _has_oauth_tokens():
        return []
    client = _build_client()
    url = 'https://www.googleapis.com/drive/v3/files'
    params = {
        'q': 'mimeType="application/vnd.google-apps.folder" and trashed=false',
        'pageSize': 1000,
        'supportsAllDrives': True,
        'includeItemsFromAllDrives': True,
        'fields': 'nextPageToken,files(id,name)',
    }
    folders: list[dict] = []
    page_token: str | None = None
    try:
        while True:
            if page_token:
                params['pageToken'] = page_token
            resp = client.http_client.request('get', url, params=params)
            data = resp.json()
            for f in (data.get('files') or []):
                _id, _nm = f.get('id'), f.get('name')
                if _id and _nm:
                    folders.append({'id': _id, 'name': _nm})
            page_token = data.get('nextPageToken')
            if not page_token:
                break
    except Exception as e:
        raise RuntimeError(f'列出 Drive 資料夾失敗：[{type(e).__name__}] {e}') from e
    folders.sort(key=lambda x: x['name'].lower())
    return folders


def create_new_sheet(title: str = '台股 Dashboard - 投資組合') -> tuple[str, str]:
    """建立新 Google Sheet 並回傳 (sheet_id, sheet_url)。

    OAuth 模式下 `drive.file` scope 已允許 app 建立並擁有此檔，
    不需要 `drive.metadata.readonly` — 可避開「token 缺中繼權限」的卡關。
    """
    if not _has_oauth_tokens():
        raise RuntimeError('建立新 Sheet 需先「🔐 用 Google 登入」')
    title = (title or '').strip() or '台股 Dashboard - 投資組合'
    client = _build_client()
    try:
        sh = client.create(title)
    except Exception as e:
        raise RuntimeError(f'建立 Sheet 失敗：[{type(e).__name__}] {e}') from e
    sheet_id = getattr(sh, 'id', '') or ''
    sheet_url = getattr(sh, 'url', '') or (
        f'https://docs.google.com/spreadsheets/d/{sheet_id}/edit' if sheet_id else '')
    if not sheet_id:
        raise RuntimeError('建立 Sheet 後未取得 ID（gspread 回傳異常）')
    return sheet_id, sheet_url


def rename_sheet(new_title: str) -> bool:
    """重新命名目前作用中的 Sheet。需要編輯權限。"""
    new_title = (new_title or '').strip()
    if not new_title:
        raise ValueError('rename_sheet: 新名稱不可為空')
    sheet_id = _get_active_sheet_id()
    if not sheet_id:
        raise RuntimeError('rename_sheet: 尚未選定 Sheet ID')
    client = _build_client()
    try:
        sh = client.open_by_key(sheet_id)
        sh.update_title(new_title)
        return True
    except Exception as e:
        raise RuntimeError(f'重新命名失敗：[{type(e).__name__}] {e}') from e


def get_sheet_title(sheet_id: str = '') -> str:
    """取得指定 Sheet 的標題；sheet_id 為空時用目前作用中的。失敗回空字串。"""
    sheet_id = sheet_id or _get_active_sheet_id()
    if not sheet_id:
        return ''
    try:
        sh = _build_client().open_by_key(sheet_id)
        return getattr(sh, 'title', '') or ''
    except Exception:
        return ''


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
