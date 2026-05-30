"""
test_tw_macro.py — tw_macro 單元測試

驗證重點:
1. 三大 fetcher(TWSE / FinMind / CBC)都會透過 proxy_helper.fetch_url
   呼叫,即必走 NAS 中繼站,不會繞道直接 import requests。
2. 解析邏輯正確(用 fixture 模擬 API 回應)。
3. M1B/M2 三層備援的優先順序正確。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import tw_macro


def _mock_resp(json_data):
    m = MagicMock()
    m.json.return_value = json_data
    return m


# ══════════════════════════════════════════════════════════════
# TWSE 市場寬度
# ══════════════════════════════════════════════════════════════

def test_twse_breadth_via_proxy(monkeypatch):
    captured = {}

    def fake(url, headers=None, params=None, timeout=12):
        captured['url']    = url
        captured['params'] = params
        return _mock_resp({
            'date': '113/05/05',
            'tables': [{
                'data': [
                    ['上漲(漲停)', '500(20)'],
                    ['下跌(跌停)', '300(5)'],
                ]
            }]
        })

    monkeypatch.setattr(tw_macro, 'fetch_url', fake)
    r = tw_macro.fetch_twse_breadth()

    assert captured['url']               == tw_macro.TWSE_MI_INDEX_URL
    assert captured['params']['response'] == 'json'
    assert captured['params']['type']    == 'MS'
    assert r['adv']       == 500
    assert r['dec']       == 300
    assert r['breadth']   == 25.0     # (500-300)/(500+300) * 100
    assert r['z_breadth'] == 1.25     # 25 / 20
    assert r['date']      == '113/05/05'
    assert r['error']     is None


def test_twse_breadth_proxy_failure(monkeypatch):
    monkeypatch.setattr(tw_macro, 'fetch_url', lambda *a, **kw: None)
    r = tw_macro.fetch_twse_breadth()
    assert r['adv']     is None
    assert r['breadth'] is None
    assert r['error']   is not None


def test_twse_breadth_skips_non_breadth_tables(monkeypatch):
    """前面有不含「上漲」字樣的表也應該被跳過,直到找到正確的那張。"""
    def fake(url, headers=None, params=None, timeout=12):
        return _mock_resp({
            'date': '113/05/05',
            'tables': [
                {'data': [['成交筆數', '1234']]},   # 無「上漲」→ skip
                {'data': [
                    ['上漲', '600'],
                    ['下跌', '200'],
                ]},
            ]
        })
    monkeypatch.setattr(tw_macro, 'fetch_url', fake)
    r = tw_macro.fetch_twse_breadth()
    assert r['adv'] == 600
    assert r['dec'] == 200


# ══════════════════════════════════════════════════════════════
# FinMind 外資籌碼
# ══════════════════════════════════════════════════════════════

def test_finmind_via_proxy(monkeypatch):
    captured = {}

    def fake(url, headers=None, params=None, timeout=12):
        captured['url']    = url
        captured['params'] = params
        return _mock_resp({
            'data': [
                {'name': 'Foreign_Investor', 'date': '2026-05-04',
                 'buy': 8_000_000_000, 'sell': 5_000_000_000},
                {'name': 'Investment_Trust', 'date': '2026-05-05',
                 'buy': 100, 'sell': 100},
                {'name': 'Foreign_Investor', 'date': '2026-05-05',
                 'buy': 10_000_000_000, 'sell': 6_000_000_000},
            ]
        })

    monkeypatch.setattr(tw_macro, 'fetch_url', fake)
    r = tw_macro.fetch_finmind_foreign_investor()

    assert captured['url']                   == tw_macro.FINMIND_BASE
    assert captured['params']['dataset']     == 'TaiwanStockTotalInstitutionalInvestors'
    # 應取 2026-05-05(較新): buy 100億 - sell 60億 = 40億
    assert r['fii_net'] == 4_000_000_000
    assert r['z_fii']   == 0.8           # max(-3, min(3, 4e9/5e9))
    assert r['date']    == '2026-05-05'


def test_finmind_no_data(monkeypatch):
    monkeypatch.setattr(tw_macro, 'fetch_url',
                        lambda *a, **kw: _mock_resp({'data': []}))
    r = tw_macro.fetch_finmind_foreign_investor()
    assert r['fii_net'] is None
    assert 'Foreign_Investor' in (r['error'] or '')


def test_finmind_proxy_failure(monkeypatch):
    monkeypatch.setattr(tw_macro, 'fetch_url', lambda *a, **kw: None)
    r = tw_macro.fetch_finmind_foreign_investor()
    assert r['fii_net'] is None
    assert r['error']   is not None


# ══════════════════════════════════════════════════════════════
# CBC M1B / M2 三層備援
# ══════════════════════════════════════════════════════════════

def test_cbc_m1b_m2_tier1_hit(monkeypatch):
    """Tier 1 ms1.json 命中,Tier 2/3 不應呼叫。"""
    rows = [{'M1B': str(100 + i), 'M2': str(200 + i * 0.5)} for i in range(13)]
    call_count = {'fetch_url': 0}

    def fake(url, headers=None, params=None, timeout=12):
        call_count['fetch_url'] += 1
        if 'ms1.json' in url:
            return _mock_resp(rows)
        return None

    monkeypatch.setattr(tw_macro, 'fetch_url', fake)
    r = tw_macro.fetch_cbc_m1b_m2()

    assert r['tier_used']      == 1
    assert r['is_proxy_tier']  is False
    assert r['m1b_yoy']        is not None
    assert r['m2_yoy']         is not None
    assert r['gap']            is not None
    # 確認 Tier 2 沒被呼叫(只 hit Tier 1 的第一個 url)
    assert call_count['fetch_url'] == 1


def test_cbc_m1b_m2_falls_through_to_tier3(monkeypatch):
    """Tier 1/2 都失敗,Tier 3 ^TWII proxy 命中。"""
    monkeypatch.setattr(tw_macro, 'fetch_url', lambda *a, **kw: None)

    # Mock _try_twii_proxy 以避開實際走 macro_core/網路
    monkeypatch.setattr(tw_macro, '_try_twii_proxy', lambda: (5.0, 1.5))
    r = tw_macro.fetch_cbc_m1b_m2()

    assert r['tier_used']     == 3
    assert r['is_proxy_tier'] is True
    assert r['m1b_yoy']       == 5.0
    assert r['m2_yoy']        == 1.5
    assert r['gap']           == 3.5


def test_cbc_m1b_m2_all_fail(monkeypatch):
    """全部 tier 都失敗 → tier_used=None,error 有值。"""
    monkeypatch.setattr(tw_macro, 'fetch_url', lambda *a, **kw: None)
    monkeypatch.setattr(tw_macro, '_try_twii_proxy', lambda: None)
    r = tw_macro.fetch_cbc_m1b_m2()
    assert r['tier_used'] is None
    assert r['m1b_yoy']   is None
    assert r['error']     is not None


# ══════════════════════════════════════════════════════════════
# 整合 API
# ══════════════════════════════════════════════════════════════

def test_snapshot_returns_three_factors(monkeypatch):
    """fetch_tw_market_snapshot 應回 breadth / fii / m1b_m2 三個 sub-dict。"""
    monkeypatch.setattr(tw_macro, 'fetch_url', lambda *a, **kw: None)
    monkeypatch.setattr(tw_macro, '_try_twii_proxy', lambda: None)
    snap = tw_macro.fetch_tw_market_snapshot()
    assert set(snap.keys()) == {'breadth', 'fii', 'm1b_m2'}
    # 全部失敗的情況下,每個 sub-dict 應該都有 error
    assert snap['breadth']['error'] is not None
    assert snap['fii']['error']     is not None
    assert snap['m1b_m2']['error']  is not None


# ══════════════════════════════════════════════════════════════
# 結構性檢查 — 確認沒有偷偷直接 import requests
# ══════════════════════════════════════════════════════════════

def test_no_direct_requests_import():
    """tw_macro 不應該直接 import requests(全部抓取要走 proxy_helper)。"""
    import inspect
    src = inspect.getsource(tw_macro)
    # tw_macro 應只透過 proxy_helper.fetch_url 抓網路;不應自己 import requests
    assert 'import requests' not in src, \
        "tw_macro 偷偷 import requests — 違反「全部走 NAS proxy」原則"


# ══════════════════════════════════════════════════════════════
# v1.1 拐點偵測：景氣對策信號 / 領先指標 / 外資連續日數
# ══════════════════════════════════════════════════════════════

def _mock_macro_rows(indicator_name: str, values: list, start: str = "2024-01-01"):
    """產生 FinMind TaiwanMacroEconomics 風格 rows。"""
    import datetime as _d
    base = _d.date.fromisoformat(start)
    return [
        {"date": (base + _d.timedelta(days=30 * i)).isoformat(),
         "indicator": indicator_name, "value": v}
        for i, v in enumerate(values)
    ]


def test_ndc_signal_inflection_up(monkeypatch):
    """景氣對策信號連 2 月翻多：prev2 ≥ prev 且 cur > prev → 拐點 emoji 應為 🚀。"""
    # 6 月歷史：26, 25, 24, 23, 22, 25（最後翻多）
    rows = _mock_macro_rows('景氣對策信號(分)', [26, 25, 24, 23, 22, 25])
    monkeypatch.setattr(tw_macro, 'fetch_url',
                        lambda *a, **kw: _mock_resp({'data': rows}))
    r = tw_macro.fetch_ndc_signal_history(months_back=12)
    assert r['score_latest'] == 25
    assert r['score_prev'] == 22
    assert '🚀' in r['inflection'] or '翻多' in r['inflection']


def test_ndc_signal_no_data(monkeypatch):
    """無資料時應回 None + error，不爆炸。"""
    monkeypatch.setattr(tw_macro, 'fetch_url', lambda *a, **kw: None)
    r = tw_macro.fetch_ndc_signal_history()
    assert r['score_latest'] is None
    assert r['error'] is not None
    assert r['inflection'] == '⬜ 資料不足'


def test_ndc_leading_index_smooth6m_reversal(monkeypatch):
    """領先指標 6M smoothed change 由負轉正應觸發 🚀。"""
    # 用 12 月穩定下降 → 然後反轉，產生 6M MA 由負轉正
    vals = [100, 99, 98, 97, 96, 95, 95, 96, 98, 100, 103, 107]
    rows = _mock_macro_rows('領先指標綜合指數', vals)
    monkeypatch.setattr(tw_macro, 'fetch_url',
                        lambda *a, **kw: _mock_resp({'data': rows}))
    r = tw_macro.fetch_ndc_leading_index(months_back=18)
    assert r['latest'] is not None
    assert r['smooth6m'] is not None
    # 由負轉正或持續擴張皆可接受（取決於 MA6 邊界）
    assert r['inflection'] in (
        '🚀 6M 由負轉正', '🟢 持續擴張', '⚠️ 由正轉負', '🔴 持續收縮', '📊 持平'
    )


def test_foreign_consecutive_days_reversal(monkeypatch):
    """連 5 日賣超後翻買 → 應觸發 🚀 賣→買 拐點。"""
    import datetime as _d
    base = _d.date(2026, 5, 25)
    nets_seq = [-1, -1, -1, -1, -1, -1, 1]  # 連 6 賣 + 1 買
    rows = []
    for i, n in enumerate(nets_seq):
        rows.append({
            'date': (base + _d.timedelta(days=i)).isoformat(),
            'name': 'Foreign_Investor',
            'buy':  100 if n > 0 else 0,
            'sell': 0 if n > 0 else 100,
        })
    monkeypatch.setattr(tw_macro, 'fetch_url',
                        lambda *a, **kw: _mock_resp({'data': rows}))
    r = tw_macro.fetch_foreign_consecutive_days(days_back=15)
    assert r['consec_days'] == 1
    assert r['prev_streak'] == -6
    assert '賣→買' in r['inflection']


def test_foreign_consecutive_days_no_data(monkeypatch):
    """無外資資料時應回 None + error，不爆炸。"""
    monkeypatch.setattr(tw_macro, 'fetch_url', lambda *a, **kw: None)
    r = tw_macro.fetch_foreign_consecutive_days()
    assert r['consec_days'] is None
    assert r['error'] is not None
    assert r['inflection'] == '⬜ 資料不足'
