"""tab_helpers.py 純函式 unit test — Phase 7A。"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from tab_helpers import (
    format_condition_emoji,
    parse_cash_flow_ratio,
    safe_get,
    safe_ma,
)


class TestParseCashFlowRatio:
    def test_strict_above(self):
        assert parse_cash_flow_ratio('123.4%', 100, strict=True) is True

    def test_strict_equal_returns_false(self):
        # 嚴格 > 100：剛好等於 100 → False
        assert parse_cash_flow_ratio('100%', 100, strict=True) is False

    def test_non_strict_equal_returns_true(self):
        assert parse_cash_flow_ratio('100%', 100, strict=False) is True

    def test_negative_below_threshold(self):
        assert parse_cash_flow_ratio('-5%', 0, strict=True) is False

    def test_negative_above_threshold(self):
        assert parse_cash_flow_ratio('-5%', -10, strict=True) is True

    def test_decimal(self):
        assert parse_cash_flow_ratio('12.5%', 10, strict=True) is True

    def test_with_surrounding_text(self):
        assert parse_cash_flow_ratio('近一年 123.4% 表現佳', 100, strict=True) is True

    def test_na_returns_none(self):
        assert parse_cash_flow_ratio('N/A', 100, strict=True) is None

    def test_contains_na_returns_none(self):
        assert parse_cash_flow_ratio('資料 N/A 取得失敗', 100, strict=True) is None

    def test_none_value_returns_none(self):
        assert parse_cash_flow_ratio(None, 100, strict=True) is None

    def test_empty_string_returns_none(self):
        assert parse_cash_flow_ratio('', 100, strict=True) is None

    def test_no_percent_sign_returns_none(self):
        assert parse_cash_flow_ratio('123', 100, strict=True) is None

    def test_pure_text_returns_none(self):
        assert parse_cash_flow_ratio('abc', 100, strict=True) is None


class TestFormatConditionEmoji:
    def test_true(self):
        assert format_condition_emoji(True) == '✅'

    def test_false(self):
        assert format_condition_emoji(False) == '❌'

    def test_none(self):
        assert format_condition_emoji(None) == '⚪'

    def test_non_bool_falls_to_none_branch(self):
        # 任何非 True / 非 False 一律走 ⚪（含 0 / '' / 0.0）
        assert format_condition_emoji(0) == '⚪'
        assert format_condition_emoji('') == '⚪'


class TestSafeGet:
    def test_int(self):
        assert safe_get(42) == 42

    def test_zero_preserved(self):
        # 0 不是 None / NaN，要保留
        assert safe_get(0) == 0

    def test_string(self):
        assert safe_get('foo') == 'foo'

    def test_none(self):
        assert safe_get(None) is None

    def test_nan(self):
        assert safe_get(math.nan) is None

    def test_pandas_na(self):
        assert safe_get(pd.NA) is None


class TestSafeMa:
    def test_ma_column_present(self):
        df = pd.DataFrame({
            'close': [10, 20, 30, 40, 50],
            'MA5': [None, None, None, None, 30.0],
        })
        assert safe_ma(df, 5) == 30.0

    def test_ma_column_missing_enough_data(self):
        df = pd.DataFrame({'close': [10, 20, 30, 40, 50]})
        assert safe_ma(df, 5) == 30.0

    def test_ma_column_missing_insufficient_data(self):
        # 只有 2 筆，要求 MA5 → 退回全資料平均
        df = pd.DataFrame({'close': [10, 20]})
        assert safe_ma(df, 5) == 15.0

    def test_ma20_rolling(self):
        df = pd.DataFrame({'close': list(range(1, 21))})  # 1..20
        # tail(20).mean() = sum(1..20)/20 = 10.5
        assert safe_ma(df, 20) == pytest.approx(10.5)
