"""技術指標計算 — 6 個純函式

從 app.py:590-707 抽出（PR P2-B Phase 1）。**零 Streamlit / 零 session state
依賴**，只用 pandas + numpy，可在 CLI / pytest 環境直接 import。

收錄函式
========
- calc_rsi(df, period=14)            — 相對強弱指標
- calc_ibs(df)                       — 內部強度 = (C-L)/(H-L)
- calc_volume_ratio(df, period=5)    — 量比 = 今日量 / N 日均量
- calc_kd(df, period=9)              — KD 隨機指標（EMA 平滑）
- calc_bollinger(df, window=20, mult=2) — 布林通道
- calc_vcp(df, n_swings=3)           — Volatility Contraction Pattern

輸入：pandas.DataFrame，columns 必須含 'close' / 'high' / 'low' / 'volume'
輸出：失敗一律回 None（不丟例外），呼叫端只需檢查 falsy
"""
from __future__ import annotations

import pandas as pd


def calc_rsi(df, period=14):
    try:
        if df is None or len(df) < period + 1:
            return None
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, 1e-9)
        rsi = 100 - (100 / (1 + rs))
        val = rsi.iloc[-1]
        return round(float(val), 1) if pd.notna(val) else None
    except Exception:
        return None


def calc_ibs(df):
    """IBS = (Close - Low) / (High - Low)  當日收盤在日震幅中的位置"""
    try:
        if df is None or df.empty:
            return None
        row = df.iloc[-1]
        h, l, c = float(row['high']), float(row['low']), float(row['close'])
        if h == l:
            return 0.5
        return round((c - l) / (h - l), 3)
    except Exception:
        return None


def calc_volume_ratio(df, period=5):
    """量比 = 今日成交量 / 近N日平均成交量"""
    try:
        if df is None or len(df) < period + 1:
            return None
        today_vol = float(df['volume'].iloc[-1])
        avg_vol = float(df['volume'].iloc[-(period+1):-1].mean())
        if avg_vol == 0:
            return None
        return round(today_vol / avg_vol, 2)
    except Exception:
        return None


def calc_kd(df, period=9):
    """計算最新一日的 K、D 值"""
    try:
        if df is None or len(df) < period:
            return None, None
        low_n = df['low'].rolling(period).min()
        high_n = df['high'].rolling(period).max()
        rsv = ((df['close'] - low_n) / (high_n - low_n).replace(0, 1)) * 100
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        k_val = k.iloc[-1]
        d_val = d.iloc[-1]
        if pd.isna(k_val) or pd.isna(d_val):
            return None, None
        return round(float(k_val), 1), round(float(d_val), 1)
    except Exception:
        return None, None


def calc_bollinger(df, window=20, mult=2):
    try:
        if df is None or len(df) < window:
            return None
        close = df['close']
        ma = close.rolling(window).mean()
        std = close.rolling(window).std()
        upper = ma + mult * std
        lower = ma - mult * std
        bw = (upper - lower) / ma * 100
        _u, _l, _m, _bw = upper.iloc[-1], lower.iloc[-1], ma.iloc[-1], bw.iloc[-1]
        if any(pd.isna(v) for v in [_u, _l, _m, _bw]):
            return None
        return {
            'upper': round(float(_u), 2),
            'lower': round(float(_l), 2),
            'ma':    round(float(_m), 2),
            'bw':    round(float(_bw), 2),
            'bw_mean': round(float(bw.mean()) if 'bw' in dir() else 0, 2),
            'price': round(float(df['close'].iloc[-1]), 2),
            'near_upper': float(df['close'].iloc[-1]) >= float(_u) * 0.97,
        }
    except Exception:
        return None


def calc_vcp(df, n_swings=3):
    if df is None or len(df) < 30:
        return None  # relaxed to 30 days
    highs, lows = df['high'].values, df['low'].values
    swings, w = [], 10
    for i in range(w, len(df) - w):
        if highs[i] == max(highs[max(0, i-w):i+w+1]):
            swings.append(('H', i, highs[i]))
        elif lows[i] == min(lows[max(0, i-w):i+w+1]):
            swings.append(('L', i, lows[i]))

    # P8修正: 只計算 H-L 或 L-H 交替的振幅（過濾連續同向swing）
    alt_swings = []
    for sw in swings:
        if not alt_swings or alt_swings[-1][0] != sw[0]:
            alt_swings.append(sw)
        else:
            # 同向取極值（HH取高，LL取低）
            if sw[0] == 'H' and sw[2] > alt_swings[-1][2]:
                alt_swings[-1] = sw
            elif sw[0] == 'L' and sw[2] < alt_swings[-1][2]:
                alt_swings[-1] = sw
    swings = alt_swings

    ranges = [abs(swings[k][2]-swings[k+1][2])/min(swings[k][2], swings[k+1][2])*100
              for k in range(len(swings)-1) if swings[k][0] != swings[k+1][0]]
    if len(ranges) < n_swings:
        return None
    last_n = ranges[-n_swings:]
    return {'swings': last_n,
            'contracting': all(last_n[i] > last_n[i+1] for i in range(len(last_n)-1)),
            'latest_range': last_n[-1]}
