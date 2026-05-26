"""test_flow_engine.py — flow_engine 純計算單元測試。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flow_engine as fe


class TestPctReturn(unittest.TestCase):
    def test_basic(self):
        # 100 → 110，近 1 日 = +10%
        self.assertEqual(fe.pct_return([100, 110], 1), 10.0)

    def test_multi_day(self):
        self.assertEqual(fe.pct_return([100, 105, 120], 2), 20.0)

    def test_insufficient(self):
        self.assertIsNone(fe.pct_return([100], 1))
        self.assertIsNone(fe.pct_return([], 1))

    def test_zero_prev(self):
        self.assertIsNone(fe.pct_return([0, 100], 1))


class TestZScore(unittest.TestCase):
    def test_insufficient(self):
        self.assertIsNone(fe.zscore_latest([1, 2, 3], window=252))

    def test_flat_zero_std(self):
        self.assertEqual(fe.zscore_latest([5.0] * 40), 0.0)

    def test_clip(self):
        # 39 個 1.0 + 最後一個極大值 → Z 應被 clip 到 3.0
        series = [1.0] * 39 + [1000.0]
        self.assertEqual(fe.zscore_latest(series, clip=3.0), 3.0)

    def test_sign(self):
        # 最後一點高於平均 → 正 Z
        series = list(range(1, 41))  # 上升序列，最後一點最大
        z = fe.zscore_latest(series)
        self.assertIsNotNone(z)
        self.assertGreater(z, 0)


class TestRankRegionalFlow(unittest.TestCase):
    def test_ordering_and_filter(self):
        cm = {
            "A": [100, 110],   # +10%
            "B": [100, 105],   # +5%
            "C": [100, 90],    # -10%
            "D": [100],        # 不足 → 過濾
        }
        ranked = fe.rank_regional_flow(cm, days=1)
        self.assertEqual([n for n, _ in ranked], ["A", "B", "C"])
        self.assertEqual(ranked[0], ("A", 10.0))


class TestRiskScore(unittest.TestCase):
    def _trend(self, start, step, n=300):
        return [start + step * i for i in range(n)]

    def test_risk_on(self):
        # 股票漲、債跌、VIX 跌 → 應偏 risk-on（正分）
        cm = {
            "股票 SPY": self._trend(100, 0.5),
            "長天期美債 TLT": self._trend(150, -0.2),
            "VIX 波動率": self._trend(30, -0.05),
        }
        res = fe.compute_risk_score(cm)
        self.assertIsNotNone(res["score"])
        self.assertGreater(res["score"], 0)
        self.assertIn("Risk-on", res["label"])

    def test_risk_off(self):
        # 股票跌、債漲、VIX 漲 → 應偏 risk-off（負分）
        cm = {
            "股票 SPY": self._trend(250, -0.5),
            "長天期美債 TLT": self._trend(100, 0.2),
            "VIX 波動率": self._trend(15, 0.1),
        }
        res = fe.compute_risk_score(cm)
        self.assertIsNotNone(res["score"])
        self.assertLess(res["score"], 0)
        self.assertIn("Risk-off", res["label"])

    def test_insufficient(self):
        res = fe.compute_risk_score({"股票 SPY": [1, 2, 3]})
        self.assertIsNone(res["score"])
        self.assertEqual(res["components"], [])

    def test_score_bounds(self):
        cm = {
            "股票 SPY": [100.0] * 200 + [10000.0],
            "長天期美債 TLT": [100.0] * 200 + [0.01],
        }
        res = fe.compute_risk_score(cm)
        self.assertLessEqual(res["score"], 100)
        self.assertGreaterEqual(res["score"], -100)


if __name__ == "__main__":
    unittest.main()
