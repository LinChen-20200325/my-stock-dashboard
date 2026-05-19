"""tests/test_etf_holdings_overlap.py — 持股重疊度 3 純函式單元測試。

對應 etf_calc.py 新增的：
- calc_holdings_overlap_pct (權重 Overlap%)
- calc_jaccard_overlap (集合 Jaccard%)
- build_holdings_overlap_matrix (N×N 矩陣)
"""
import pandas as pd
import pytest

from etf_calc import (
    build_holdings_overlap_matrix,
    calc_holdings_overlap_pct,
    calc_jaccard_overlap,
)


class TestWeightOverlap:
    def test_identical(self):
        h = {'台積電': 30.0, '鴻海': 5.0, '聯發科': 4.0}
        assert calc_holdings_overlap_pct(h, h) == 39.0

    def test_disjoint(self):
        h1 = {'台積電': 30.0, '鴻海': 5.0}
        h2 = {'聯發科': 10.0, '富邦金': 8.0}
        assert calc_holdings_overlap_pct(h1, h2) == 0.0

    def test_partial_min_weight(self):
        h1 = {'台積電': 30.0, '鴻海': 5.0, '聯發科': 4.0}
        h2 = {'台積電': 50.0, '鴻海': 3.0, '中華電': 10.0}
        assert calc_holdings_overlap_pct(h1, h2) == 33.0

    def test_capped_at_100(self):
        h1 = {f'股{i}': 20.0 for i in range(10)}
        h2 = {f'股{i}': 30.0 for i in range(10)}
        assert calc_holdings_overlap_pct(h1, h2) == 100.0

    def test_none_inputs(self):
        assert calc_holdings_overlap_pct(None, {'台積電': 30}) == 0.0
        assert calc_holdings_overlap_pct({'台積電': 30}, None) == 0.0
        assert calc_holdings_overlap_pct(None, None) == 0.0

    def test_empty_dict(self):
        assert calc_holdings_overlap_pct({}, {'台積電': 30}) == 0.0

    def test_invalid_weight_skipped(self):
        h1 = {'台積電': 30.0, '鴻海': 'bad'}
        h2 = {'台積電': 20.0, '鴻海': 10.0}
        assert calc_holdings_overlap_pct(h1, h2) == 20.0

    def test_rounding(self):
        h1 = {'A': 1.234567}
        h2 = {'A': 1.234567}
        assert calc_holdings_overlap_pct(h1, h2) == 1.23


class TestJaccardOverlap:
    def test_identical(self):
        h = {'台積電': 30.0, '鴻海': 5.0, '聯發科': 4.0}
        assert calc_jaccard_overlap(h, h) == 100.0

    def test_disjoint(self):
        h1 = {'台積電': 30.0, '鴻海': 5.0}
        h2 = {'聯發科': 10.0, '富邦金': 8.0}
        assert calc_jaccard_overlap(h1, h2) == 0.0

    def test_half_overlap(self):
        h1 = {'A': 50, 'B': 50}
        h2 = {'B': 50, 'C': 50}
        assert calc_jaccard_overlap(h1, h2) == round(1 / 3 * 100, 2)

    def test_ignores_weights(self):
        h1 = {'A': 99.0, 'B': 0.5}
        h2 = {'A': 0.1, 'B': 50.0}
        assert calc_jaccard_overlap(h1, h2) == 100.0

    def test_accepts_iterables(self):
        assert calc_jaccard_overlap(['A', 'B'], ['B', 'C']) == round(1 / 3 * 100, 2)

    def test_none_inputs(self):
        assert calc_jaccard_overlap(None, {'A': 30}) == 0.0
        assert calc_jaccard_overlap({}, {}) == 0.0


class TestBuildMatrix:
    def test_shape_and_diagonal(self):
        d = {
            '0050': {'台積電': 50.0, '鴻海': 4.0},
            '0056': {'鴻海': 5.0, '聯發科': 6.0},
            '00878': {'富邦金': 8.0},
        }
        m = build_holdings_overlap_matrix(d)
        assert m.shape == (3, 3)
        assert list(m.index) == ['0050', '0056', '00878']
        # 對角線全 100
        for t in m.index:
            assert m.loc[t, t] == 100.0
        # 對稱
        assert m.loc['0050', '0056'] == m.loc['0056', '0050']
        # 0050-0056 共持鴻海 min(4,5)=4
        assert m.loc['0050', '0056'] == 4.0
        # 0050-00878 無交集
        assert m.loc['0050', '00878'] == 0.0

    def test_jaccard_method(self):
        d = {
            'A': {'X': 50, 'Y': 50},
            'B': {'Y': 30, 'Z': 70},
        }
        m = build_holdings_overlap_matrix(d, method='jaccard')
        # |A∩B|={Y}=1; |A∪B|={X,Y,Z}=3 → 33.33%
        assert m.loc['A', 'B'] == round(1 / 3 * 100, 2)

    def test_missing_holdings_become_nan(self):
        import math
        d = {
            'A': {'X': 50.0, 'Y': 50.0},
            'B': None,
            'C': {'X': 30.0, 'Z': 70.0},
        }
        m = build_holdings_overlap_matrix(d)
        # B 全 NaN（含 B-B 對角線，因為 None ETF 沒有「自我重疊 100%」的語意）
        assert math.isnan(m.loc['B', 'B'])
        assert math.isnan(m.loc['A', 'B'])
        assert math.isnan(m.loc['B', 'C'])
        # A-C 有資料：min(50, 30)=30
        assert m.loc['A', 'C'] == 30.0

    def test_returns_dataframe(self):
        m = build_holdings_overlap_matrix({'A': {'X': 100}})
        assert isinstance(m, pd.DataFrame)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
