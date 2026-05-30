"""
test_tw_backtest.py — TWII 倒掛翻正回測單元測試

驗證重點：
1. find_uninversion_events 事件識別（合成序列）
2. _forward_return 日期搜尋邏輯
3. backtest_twii_turning_points 無 FRED key 時優雅降級
4. 完整 mock 流程：T10Y2Y + ^TWII 都有資料 → 回傳 events + summary
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import tw_backtest


# ════════════════════════════════════════════════════════════
# find_uninversion_events
# ════════════════════════════════════════════════════════════

def test_no_inversion_returns_empty():
    s = pd.Series([0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
                  index=pd.date_range('2020-01-01', periods=6, freq='D'))
    assert tw_backtest.find_uninversion_events(s) == []


def test_single_inversion_and_uninvert():
    """合成：T10Y2Y 從 +0.5 → -0.3 → +0.1 → 連 5 日 ≥0 → 應識別 1 事件。"""
    vals = [0.5, 0.3, 0.0, -0.1, -0.3, -0.3, -0.2, 0.1, 0.2, 0.3, 0.4, 0.5]
    idx = pd.date_range('2020-01-01', periods=len(vals), freq='D')
    s = pd.Series(vals, index=idx)
    events = tw_backtest.find_uninversion_events(s, min_inversion_depth=-0.1,
                                                  stable_days=5)
    assert len(events) == 1
    assert events[0]['t10y2y_min_pre'] == -0.3
    # 事件日期應該是第 8 個（index=7）— 翻正首日 0.1
    assert events[0]['date'] == idx[7]


def test_cooldown_blocks_back_to_back_events():
    """連續 2 個倒掛區段，cooldown_days=365 應只保留 1 個。"""
    vals = [0.5, -0.2, -0.2, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1,
            -0.3, -0.3, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2]
    idx = pd.date_range('2020-01-01', periods=len(vals), freq='D')
    s = pd.Series(vals, index=idx)
    events = tw_backtest.find_uninversion_events(s, min_inversion_depth=-0.1,
                                                  stable_days=3,
                                                  cooldown_days=365)
    assert len(events) == 1  # 第二個事件被 cooldown 擋


# ════════════════════════════════════════════════════════════
# _forward_return
# ════════════════════════════════════════════════════════════

def test_forward_return_basic():
    """指數從 100 漲到 110，182 日後報酬 +10%。"""
    idx = pd.date_range('2020-01-01', periods=300, freq='D')
    s = pd.Series(np.linspace(100, 130, 300), index=idx)
    r = tw_backtest._forward_return(s, idx[0], 182)
    assert r is not None
    # 第 0 日 = 100；第 182 日約 = 100 + (130-100)*182/299 ≈ 118.27
    assert 15 < r < 25


def test_forward_return_window_not_reached():
    """窗口超出資料末尾 → 回 None。"""
    idx = pd.date_range('2020-01-01', periods=10, freq='D')
    s = pd.Series([100] * 10, index=idx)
    assert tw_backtest._forward_return(s, idx[0], 365) is None


def test_forward_return_empty_series():
    r = tw_backtest._forward_return(pd.Series(dtype=float),
                                     pd.Timestamp('2020-01-01'), 182)
    assert r is None


# ════════════════════════════════════════════════════════════
# backtest_twii_turning_points
# ════════════════════════════════════════════════════════════

def test_no_fred_key_returns_note():
    out = tw_backtest.backtest_twii_turning_points('')
    assert out['source_ok'] is False
    assert 'FRED' in out['note']
    assert out['events'] == []


def test_fred_empty_returns_insufficient(monkeypatch):
    """FRED 抓到 < 1000 obs → 拒絕回測。"""
    def _empty_fred(sid, key, n=250):
        return pd.DataFrame(columns=['date', 'value'])
    import macro_core
    monkeypatch.setattr(macro_core, 'fetch_fred', _empty_fred)
    out = tw_backtest.backtest_twii_turning_points('dummy')
    assert out['source_ok'] is False
    assert 'T10Y2Y' in out['note']


def test_full_mock_pipeline(monkeypatch):
    """完整 mock：T10Y2Y 1500 日（含倒掛）+ TWII 5000 日 → 應回 events + summary。"""
    # 合成 T10Y2Y：1500 日，前 500 +0.5、500-700 倒掛、700+ +0.3
    n = 1500
    t_dates = pd.date_range('2018-01-01', periods=n, freq='D')
    t_vals  = np.concatenate([
        np.full(500, 0.5),    # 正
        np.full(200, -0.3),   # 倒掛
        np.full(800, 0.3),    # 翻正且持續
    ])
    df_t = pd.DataFrame({'date': t_dates, 'value': t_vals})

    def _mock_fred(sid, key, n=250):
        if sid == 'T10Y2Y':
            return df_t
        return pd.DataFrame(columns=['date', 'value'])

    # 合成 TWII：5000 日，緩步上升
    twii_dates = pd.date_range('2010-01-01', periods=5000, freq='D')
    twii_vals  = np.linspace(8000, 20000, 5000)
    twii_series = pd.Series(twii_vals, index=twii_dates, name='^TWII')

    def _mock_yf(ticker, range_='2y', interval='1d'):
        if ticker == '^TWII':
            return twii_series
        return pd.Series(dtype=float)

    import macro_core
    monkeypatch.setattr(macro_core, 'fetch_fred', _mock_fred)
    monkeypatch.setattr(macro_core, 'fetch_yf_close', _mock_yf)
    out = tw_backtest.backtest_twii_turning_points('dummy')
    assert out['source_ok'] is True
    assert out['summary']['n_events'] >= 1
    assert out['twii_series'] is not None and not out['twii_series'].empty
    # 因為 TWII 是緩步上升，所有事件後續報酬都應 > 0
    for ev in out['events']:
        for k in ('ret_6m', 'ret_12m'):
            if ev[k] is not None:
                assert ev[k] > 0


# ════════════════════════════════════════════════════════════
# hot_money 新 helper
# ════════════════════════════════════════════════════════════

def test_get_latest_hot_money_state_empty_twd():
    """空 twd_df → return None。"""
    import hot_money
    r = hot_money.get_latest_hot_money_state(
        pd.DataFrame(columns=['close']), token='')
    assert r is None
