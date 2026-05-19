"""tests/test_etf_weakness.py — 主動 ETF 弱勢度純函式單元測試。

對應 etf_calc.py / etf_fetch.py 新增的：
- is_active_etf (主被動判別)
- calc_weakness_metrics (大跌弱勢率 / 反彈弱勢率 / 季報酬 / TE)
- _auto_bench_for_etf (benchmark 自動選擇)
"""
import numpy as np
import pandas as pd
import pytest

from etf_calc import calc_weakness_metrics, _auto_bench_for_etf
from etf_fetch import is_active_etf


class TestActivePassiveClassification:
    def test_whitelist_hit(self):
        assert is_active_etf('00980A')
        assert is_active_etf('00982A.TW')
        assert is_active_etf('00984A')

    def test_passive_pure_digit(self):
        assert not is_active_etf('0050')
        assert not is_active_etf('00878')
        assert not is_active_etf('00940')
        assert not is_active_etf('0050.TW')

    def test_bond_suffix_B_passive(self):
        # B 結尾 = 債券型 = 純被動追蹤
        assert not is_active_etf('00679B')
        assert not is_active_etf('00937B.TW')

    def test_other_letter_active(self):
        # D / T 結尾（不在白名單，但符合主動規則）
        assert is_active_etf('00980D')
        assert is_active_etf('00982T')

    def test_empty(self):
        assert not is_active_etf('')
        assert not is_active_etf(None)


class TestWeaknessMetrics:
    @staticmethod
    def _mk_series(values, start='2025-01-01'):
        idx = pd.bdate_range(start=start, periods=len(values))
        return pd.Series(values, index=idx)

    def test_insufficient_data(self):
        s = self._mk_series([0.01] * 5)
        r = calc_weakness_metrics(s, s)
        assert r.get('_err') == 'insufficient_data'
        assert r.get('sample') == 5

    def test_none_input(self):
        assert calc_weakness_metrics(None, pd.Series([0.01])).get('_err') == 'none_input'

    def test_etf_always_worse_on_down_days(self):
        # 大盤跌 0.01，ETF 跌 0.02（永遠跌更深）
        # 大盤漲 0.01，ETF 漲 0.005（永遠漲不夠）
        n = 60
        bench = [-0.01 if i % 2 == 0 else 0.01 for i in range(n)]
        etf = [-0.02 if i % 2 == 0 else 0.005 for i in range(n)]
        b = self._mk_series(bench)
        e = self._mk_series(etf)
        r = calc_weakness_metrics(e, b)
        assert r['down_ratio'] == 100.0
        assert r['up_ratio'] == 100.0
        assert r['down_days'] == 30
        assert r['up_days'] == 30

    def test_etf_outperforms_always(self):
        # 大盤跌時 ETF 跌更少，漲時 ETF 漲更多
        n = 60
        bench = [-0.02 if i % 2 == 0 else 0.01 for i in range(n)]
        etf = [-0.01 if i % 2 == 0 else 0.02 for i in range(n)]
        b = self._mk_series(bench)
        e = self._mk_series(etf)
        r = calc_weakness_metrics(e, b)
        assert r['down_ratio'] == 0.0
        assert r['up_ratio'] == 0.0

    def test_quarter_lose_streak(self):
        # 構造：4 季中，最後 2 季 ETF 季報酬 < bench
        # 用日報酬累積 → quarter
        n = 252  # ≈ 1 年
        np.random.seed(42)
        # bench: 每天 +0.001（穩漲）
        bench_vals = np.full(n, 0.001)
        # etf: 前半段 +0.002（贏），後半段 -0.0005（連續輸 2 季）
        etf_vals = np.concatenate([np.full(n // 2, 0.002),
                                   np.full(n - n // 2, -0.0005)])
        b = self._mk_series(bench_vals)
        e = self._mk_series(etf_vals)
        r = calc_weakness_metrics(e, b)
        # 後半年連續 2 個季都是負報酬 < 正的 bench
        assert r['quarter_lose_streak'] >= 2

    def test_quarter_streak_zero_when_recent_wins(self):
        n = 252
        # bench 穩漲、etf 前半段輸後半段贏
        bench_vals = np.full(n, 0.001)
        etf_vals = np.concatenate([np.full(n // 2, -0.0005),
                                   np.full(n - n // 2, 0.003)])
        b = self._mk_series(bench_vals)
        e = self._mk_series(etf_vals)
        r = calc_weakness_metrics(e, b)
        # 最近一季 ETF 贏 → streak = 0
        assert r['quarter_lose_streak'] == 0

    def test_tracking_error_zero_when_identical(self):
        n = 100
        vals = np.random.RandomState(1).normal(0, 0.01, n).tolist()
        s = self._mk_series(vals)
        r = calc_weakness_metrics(s, s)
        assert r['te_pct'] == 0.0

    def test_tracking_error_positive(self):
        n = 100
        rng = np.random.RandomState(2)
        bench_vals = rng.normal(0, 0.01, n)
        etf_vals = bench_vals + rng.normal(0, 0.005, n)
        b = self._mk_series(bench_vals)
        e = self._mk_series(etf_vals)
        r = calc_weakness_metrics(e, b)
        assert r['te_pct'] > 0

    def test_zero_down_days(self):
        # bench 永遠不跌（全 0 或正）→ down_days=0, ratio=0
        n = 60
        b = self._mk_series([0.001] * n)
        e = self._mk_series([0.0005] * n)
        r = calc_weakness_metrics(e, b)
        assert r['down_days'] == 0
        assert r['down_ratio'] == 0.0


class TestAutoBenchSelection:
    def test_tw_etf_uses_twii(self):
        assert _auto_bench_for_etf('0050.TW') == '^TWII'
        assert _auto_bench_for_etf('00980A.TW') == '^TWII'
        assert _auto_bench_for_etf('0050') == '^TWII'

    def test_us_etf_uses_gspc(self):
        assert _auto_bench_for_etf('SPY') == '^GSPC'
        assert _auto_bench_for_etf('QQQ') == '^GSPC'
        assert _auto_bench_for_etf('VTI') == '^GSPC'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
