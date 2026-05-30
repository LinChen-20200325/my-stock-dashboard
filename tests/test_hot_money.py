# -*- coding: utf-8 -*-
"""tests/test_hot_money.py — 熱錢監測核心邏輯單元測試

只測純函式（build_signals / _twd_df_to_series），不測 render UI（streamlit）
與 fetch FinMind（外部網路）。
"""
from __future__ import annotations

import pandas as pd
import pytest

from hot_money import (
    DIVERGENCE_STATES,
    STATE_TEXT,
    _twd_df_to_series,
    build_signals,
)


# ────────────────────────────────────────────────────────────────────────
# build_signals — 9 個狀態分類向量化驗證
# ────────────────────────────────────────────────────────────────────────
def _make_flow_fx(dates, flows, fx_rates):
    flow = pd.DataFrame({"date": pd.to_datetime(dates), "foreign_net_yi": flows})
    fx = pd.DataFrame({"date": pd.to_datetime(dates), "usdtwd": fx_rates})
    return flow, fx


def test_build_signals_empty_inputs_returns_empty_df_with_schema():
    sig = build_signals(pd.DataFrame(), pd.DataFrame(), 5, 50, 0.5)
    assert sig.empty
    assert "state" in sig.columns
    assert "is_divergence" in sig.columns


def test_build_signals_sync_inflow_state_when_buy_and_twd_up():
    """連 10 天 外資每天 +100 億 + 台幣升值（fx 從 31 跌到 30）→ 應分類「同步流入」。"""
    dates = pd.bdate_range("2026-01-01", periods=10)
    flows = [100.0] * 10
    fx_rates = [31.0 - 0.1 * i for i in range(10)]
    flow_df, fx_df = _make_flow_fx(dates, flows, fx_rates)
    sig = build_signals(flow_df, fx_df, window=5, flow_thr=50, fx_thr=0.5)
    # 末尾應該是同步流入
    assert sig.iloc[-1]["state"] == "同步流入"
    assert not bool(sig.iloc[-1]["is_divergence"])


def test_build_signals_sync_outflow_state_when_sell_and_twd_down():
    """連 10 天 外資每天 −100 億 + 台幣貶值（fx 從 31 漲到 32）→ 同步流出。"""
    dates = pd.bdate_range("2026-01-01", periods=10)
    flows = [-100.0] * 10
    fx_rates = [31.0 + 0.1 * i for i in range(10)]
    flow_df, fx_df = _make_flow_fx(dates, flows, fx_rates)
    sig = build_signals(flow_df, fx_df, window=5, flow_thr=50, fx_thr=0.5)
    assert sig.iloc[-1]["state"] == "同步流出"


def test_build_signals_hot_money_in_fx_divergence():
    """背離｜熱錢停泊匯市：台幣明顯升、外資沒買（甚至小賣）。"""
    dates = pd.bdate_range("2026-01-01", periods=10)
    flows = [-5.0] * 10           # 接近 0 / 微賣超
    fx_rates = [31.0 - 0.15 * i for i in range(10)]   # 強升值
    flow_df, fx_df = _make_flow_fx(dates, flows, fx_rates)
    sig = build_signals(flow_df, fx_df, window=5, flow_thr=50, fx_thr=0.5)
    assert sig.iloc[-1]["state"] == "背離｜熱錢停泊匯市"
    assert bool(sig.iloc[-1]["is_divergence"])


def test_build_signals_buy_masked_by_fx_divergence():
    """背離｜買盤遭拋匯掩蓋：外資買、台幣貶。"""
    dates = pd.bdate_range("2026-01-01", periods=10)
    flows = [100.0] * 10
    fx_rates = [31.0 + 0.15 * i for i in range(10)]   # 強貶值
    flow_df, fx_df = _make_flow_fx(dates, flows, fx_rates)
    sig = build_signals(flow_df, fx_df, window=5, flow_thr=50, fx_thr=0.5)
    assert sig.iloc[-1]["state"] == "背離｜買盤遭拋匯掩蓋"
    assert bool(sig.iloc[-1]["is_divergence"])


def test_build_signals_fx_first_exit_divergence():
    """背離｜匯市先撤：台幣貶、外資沒賣（甚至小買）。"""
    dates = pd.bdate_range("2026-01-01", periods=10)
    flows = [5.0] * 10            # 微買 / 中性
    fx_rates = [31.0 + 0.15 * i for i in range(10)]   # 強貶值
    flow_df, fx_df = _make_flow_fx(dates, flows, fx_rates)
    sig = build_signals(flow_df, fx_df, window=5, flow_thr=50, fx_thr=0.5)
    assert sig.iloc[-1]["state"] == "背離｜匯市先撤"
    assert bool(sig.iloc[-1]["is_divergence"])


def test_build_signals_neutral_state_when_both_below_thresholds():
    """外資與匯率都低於門檻 → 中性／觀望。"""
    dates = pd.bdate_range("2026-01-01", periods=10)
    flows = [1.0] * 10            # 累計 5 < 50 門檻
    fx_rates = [31.0, 31.001, 31.002, 31.003, 31.004, 31.005, 31.006, 31.007, 31.008, 31.009]
    flow_df, fx_df = _make_flow_fx(dates, flows, fx_rates)
    sig = build_signals(flow_df, fx_df, window=5, flow_thr=50, fx_thr=0.5)
    assert sig.iloc[-1]["state"] == "中性／觀望"
    assert not bool(sig.iloc[-1]["is_divergence"])


def test_build_signals_mild_inflow_with_only_flow_signal():
    """外資買達門檻但匯率沒動 → 溫和流入。"""
    dates = pd.bdate_range("2026-01-01", periods=10)
    flows = [50.0] * 10           # 累計 250 > 門檻
    fx_rates = [31.000] * 10      # 持平
    flow_df, fx_df = _make_flow_fx(dates, flows, fx_rates)
    sig = build_signals(flow_df, fx_df, window=5, flow_thr=50, fx_thr=0.5)
    assert sig.iloc[-1]["state"] == "溫和流入"


def test_build_signals_interpretation_text_matches_state_text():
    """每個 state 對應的 interpretation 應從 STATE_TEXT mapping 來。"""
    dates = pd.bdate_range("2026-01-01", periods=10)
    flows = [100.0] * 10
    fx_rates = [31.0 - 0.1 * i for i in range(10)]
    flow_df, fx_df = _make_flow_fx(dates, flows, fx_rates)
    sig = build_signals(flow_df, fx_df, window=5, flow_thr=50, fx_thr=0.5)
    for _, row in sig.iterrows():
        if row["state"] in STATE_TEXT:
            assert row["interpretation"] == STATE_TEXT[row["state"]]


def test_build_signals_divergence_states_set_matches_constant():
    """DIVERGENCE_STATES 常數應該完整對齊背離邏輯。"""
    assert DIVERGENCE_STATES == {
        "背離｜熱錢停泊匯市",
        "背離｜買盤遭拋匯掩蓋",
        "背離｜匯市先撤",
    }


def test_build_signals_no_overlap_dates_returns_empty():
    """flow 與 fx 完全不重疊的日期 → merge inner 空集 → 回空 df。"""
    flow_df = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        "foreign_net_yi": [10.0, 20.0],
    })
    fx_df = pd.DataFrame({
        "date": pd.to_datetime(["2027-01-01", "2027-01-02"]),
        "usdtwd": [30.0, 30.5],
    })
    sig = build_signals(flow_df, fx_df, window=5, flow_thr=50, fx_thr=0.5)
    assert sig.empty


# ────────────────────────────────────────────────────────────────────────
# _twd_df_to_series — yfinance DataFrame 解析
# ────────────────────────────────────────────────────────────────────────
def test_twd_df_to_series_none_or_empty_returns_empty():
    assert _twd_df_to_series(None).empty
    assert _twd_df_to_series(pd.DataFrame()).empty


def test_twd_df_to_series_lowercase_close_column():
    """daily_checklist 用小寫 'close'。"""
    df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=5),
        "close": [31.0, 31.1, 31.2, 31.05, 30.9],
    })
    out = _twd_df_to_series(df)
    assert len(out) == 5
    assert list(out.columns) == ["date", "usdtwd"]
    assert out.iloc[0]["usdtwd"] == 31.0


def test_twd_df_to_series_uppercase_close_via_index():
    """yfinance 預設 'Close' + datetime index。"""
    idx = pd.date_range("2026-01-01", periods=5)
    df = pd.DataFrame({"Close": [31.0, 31.1, 31.2, 31.05, 30.9]}, index=idx)
    df.index.name = "Date"
    out = _twd_df_to_series(df)
    assert len(out) == 5
    assert out.iloc[-1]["usdtwd"] == 30.9


def test_twd_df_to_series_drops_zero_and_negative_values():
    """yfinance 假日有時回 0 或 -1，應過濾掉。"""
    df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=5),
        "close": [31.0, 0.0, 31.1, -1.0, 31.2],
    })
    out = _twd_df_to_series(df)
    assert len(out) == 3
    assert (out["usdtwd"] > 0).all()


def test_twd_df_to_series_no_close_column_returns_empty():
    """完全沒有 close-like 欄 → 空 df，不拋例外。"""
    df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=3),
        "volume": [100, 200, 300],
    })
    out = _twd_df_to_series(df)
    assert out.empty


# ────────────────────────────────────────────────────────────────────────
# Regression smoke：altair / typing_extensions chain import 不能炸
# （fund v18.240 同等預防性測試）
# ────────────────────────────────────────────────────────────────────────
def test_hot_money_module_imports_cleanly():
    """整個 hot_money + render 函式 import 不應炸（TypedDict closed= 等）。"""
    import importlib
    import hot_money as _hm
    importlib.reload(_hm)
    assert callable(_hm.render_hot_money_section)
    assert callable(_hm.build_signals)


def test_altair_import_chain_does_not_raise():
    """altair / narwhals 全鏈 import 不可拋 TypeError
    （搶在 altair 5.5+ TypedDict closed= bug 重現前先測）。"""
    try:
        import altair  # noqa: F401
    except TypeError as e:
        if "closed" in str(e):
            raise AssertionError(
                "altair import 踩到 TypedDict closed= bug "
                "(typing_extensions 太舊 / altair 版本不對？)"
            ) from e
        raise
