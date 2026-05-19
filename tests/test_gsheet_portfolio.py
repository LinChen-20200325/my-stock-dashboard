"""gsheet_portfolio.py 單元測試 — mock gspread client 不打真 API。"""
from unittest.mock import MagicMock, patch

import pytest

import gsheet_portfolio as gsp


class _FakeWorksheet:
    """模擬 gspread.Worksheet：用 list[list] 存 2D 資料 + header。"""
    def __init__(self, initial_rows=None):
        self.rows = list(initial_rows or [gsp._HEADERS])

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def get_all_records(self):
        if len(self.rows) < 2:
            return []
        headers = self.rows[0]
        return [dict(zip(headers, [str(v) for v in r])) for r in self.rows[1:]]

    def row_values(self, n):
        return list(self.rows[n - 1]) if n - 1 < len(self.rows) else []

    def update(self, _range, values):
        if _range.startswith('A1') and values:
            self.rows[0] = list(values[0])

    def append_row(self, row):
        self.rows.append(list(row))

    def append_rows(self, rows):
        for r in rows:
            self.rows.append(list(r))

    def clear(self):
        self.rows = []


@pytest.fixture
def fake_ws():
    """乾淨的 worksheet，只含 header。"""
    ws = _FakeWorksheet()
    with patch.object(gsp, '_ws', return_value=ws):
        yield ws


@pytest.fixture
def populated_ws():
    """預先塞兩組組合的 worksheet。"""
    ws = _FakeWorksheet([
        gsp._HEADERS,
        ['攻擊組合', '0050.TW', 1.0, 135.5, '2026-05-19 10:00:00'],
        ['攻擊組合', '00713.TW', 0.5, 82.3, '2026-05-19 10:00:00'],
        ['存股組合', 'BND', 0.2, 72.5, '2026-05-19 10:01:00'],
    ])
    with patch.object(gsp, '_ws', return_value=ws):
        yield ws


# ── is_configured ───────────────────────────────────────────
def test_is_configured_no_streamlit():
    with patch.object(gsp, 'st', None):
        assert gsp.is_configured() is False


def test_is_configured_missing_keys():
    fake_st = MagicMock()
    fake_st.secrets = MagicMock()
    fake_st.secrets.__getitem__ = MagicMock(side_effect=KeyError('portfolio_sheet_id'))
    with patch.object(gsp, 'st', fake_st):
        assert gsp.is_configured() is False


def test_is_configured_ok():
    fake_st = MagicMock()
    fake_st.secrets = {'portfolio_sheet_id': 'abc', 'gcp_service_account': {'x': 1}}
    with patch.object(gsp, 'st', fake_st):
        assert gsp.is_configured() is True


# ── list_portfolios ─────────────────────────────────────────
def test_list_portfolios_empty(fake_ws):
    assert gsp.list_portfolios() == []


def test_list_portfolios_dedup_sorted(populated_ws):
    names = gsp.list_portfolios()
    assert names == ['存股組合', '攻擊組合']


def test_list_portfolios_skips_blank_name():
    ws = _FakeWorksheet([gsp._HEADERS, ['', '0050.TW', 1, 100, 'ts']])
    with patch.object(gsp, '_ws', return_value=ws):
        assert gsp.list_portfolios() == []


# ── load_portfolio ──────────────────────────────────────────
def test_load_portfolio_existing(populated_ws):
    rows = gsp.load_portfolio('攻擊組合')
    assert len(rows) == 2
    assert rows[0]['ticker'] == '0050.TW'
    assert rows[0]['lots'] == 1.0
    assert rows[0]['avg_price'] == 135.5
    assert rows[1]['ticker'] == '00713.TW'


def test_load_portfolio_missing_name(populated_ws):
    assert gsp.load_portfolio('不存在') == []


def test_load_portfolio_empty_name(populated_ws):
    assert gsp.load_portfolio('') == []
    assert gsp.load_portfolio('   ') == []


def test_load_portfolio_skips_invalid_rows():
    ws = _FakeWorksheet([
        gsp._HEADERS,
        ['測試', '0050.TW', 1, 100, 'ts'],
        ['測試', '0050.TW', 0, 100, 'ts'],     # 張數為 0 略過
        ['測試', '', 1, 100, 'ts'],            # 代號空略過
        ['測試', 'BND', 'abc', 100, 'ts'],     # 張數非數字略過
    ])
    with patch.object(gsp, '_ws', return_value=ws):
        rows = gsp.load_portfolio('測試')
        assert len(rows) == 1
        assert rows[0]['ticker'] == '0050.TW'


# ── save_portfolio ──────────────────────────────────────────
def test_save_portfolio_new(fake_ws):
    n = gsp.save_portfolio('新組合', [
        {'ticker': '0050.TW', 'lots': 1.0, 'avg_price': 135.5},
        {'ticker': 'BND', 'lots': 0.2, 'avg_price': 72.5},
    ])
    assert n == 2
    assert fake_ws.rows[0] == gsp._HEADERS
    assert fake_ws.rows[1][0] == '新組合'
    assert fake_ws.rows[1][1] == '0050.TW'
    assert fake_ws.rows[2][1] == 'BND'


def test_save_portfolio_overwrites_same_name(populated_ws):
    """同名儲存應覆蓋既有，不重複堆疊。"""
    n = gsp.save_portfolio('攻擊組合', [
        {'ticker': 'VOO', 'lots': 0.1, 'avg_price': 400.0},
    ])
    assert n == 1
    rows = gsp.load_portfolio('攻擊組合')
    assert len(rows) == 1
    assert rows[0]['ticker'] == 'VOO'
    # 存股組合不受影響
    assert len(gsp.load_portfolio('存股組合')) == 1


def test_save_portfolio_empty_name(fake_ws):
    with pytest.raises(ValueError, match='名稱'):
        gsp.save_portfolio('', [{'ticker': 'X', 'lots': 1, 'avg_price': 1}])


def test_save_portfolio_empty_rows(fake_ws):
    with pytest.raises(ValueError, match='內容'):
        gsp.save_portfolio('x', [])


def test_save_portfolio_all_invalid_rows(fake_ws):
    with pytest.raises(ValueError, match='有效'):
        gsp.save_portfolio('x', [
            {'ticker': '', 'lots': 1, 'avg_price': 1},
            {'ticker': 'A', 'lots': 0, 'avg_price': 1},
            {'ticker': 'B', 'lots': 1, 'avg_price': 0},
        ])


def test_save_portfolio_uppercases_ticker(fake_ws):
    gsp.save_portfolio('x', [{'ticker': '0050.tw', 'lots': 1, 'avg_price': 100}])
    rows = gsp.load_portfolio('x')
    assert rows[0]['ticker'] == '0050.TW'


# ── delete_portfolio ────────────────────────────────────────
def test_delete_portfolio_existing(populated_ws):
    n = gsp.delete_portfolio('攻擊組合')
    assert n == 2
    assert gsp.load_portfolio('攻擊組合') == []
    # 存股組合不受影響
    assert len(gsp.load_portfolio('存股組合')) == 1


def test_delete_portfolio_missing(populated_ws):
    n = gsp.delete_portfolio('不存在')
    assert n == 0
    # 原始資料不變
    assert len(gsp.list_portfolios()) == 2


def test_delete_portfolio_empty_name(populated_ws):
    assert gsp.delete_portfolio('') == 0


def test_delete_portfolio_empty_sheet(fake_ws):
    assert gsp.delete_portfolio('x') == 0
