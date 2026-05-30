# -*- coding: utf-8 -*-
"""hot_money.py — 熱錢監測：三角交叉（外資 × 匯率） + 背離偵測

整合自 user 上傳的 `a731802d-app.py`（單頁 Streamlit demo）；保留純函式 +
build_signals 邏輯，UI render 部分接 tab_macro.py 既有資料源（複用 yfinance
TWD=X DataFrame + 既有 finmind_get fetcher），避免重複呼叫 FinMind。

設計（與 CLAUDE.md §2 一致）：
- 純函式 `build_signals` / `_twd_df_to_series` 無 streamlit 依賴，可測
- `render_hot_money_section` 接收 caller 已有的 _twd_df + token，自取外資 series
- FinMind 失敗 / 空資料一律安全降級（顯示 warning + 停止繪圖）
"""
from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd
import streamlit as st

# 狀態白話解讀（供非專業讀者）
STATE_TEXT = {
    "同步流入": "外資資金正流入股市，並同步推升新台幣——資金動向乾淨、方向一致，偏多訊號。",
    "同步流出": "外資從股市撤出，新台幣同步走貶——資金流出訊號明確，偏空。",
    "背離｜熱錢停泊匯市": "台幣明顯升值，但外資並未同步買超股市。這常代表熱錢已匯入、停泊在匯市觀望，"
                          "尚未進場——往往是行情前奏，值得提高警覺。",
    "背離｜買盤遭拋匯掩蓋": "外資在買超股市，台幣卻在走貶。買盤可能被出口商拋匯或其他資金外流掩蓋，"
                            "匯率訊號被稀釋，需謹慎解讀。",
    "背離｜匯市先撤": "台幣明顯走貶，但股市還沒出現對等賣壓。資金可能正從匯市先行撤離，"
                      "留意股市是否落後反應。",
    "溫和流入": "外資小幅買超，匯率大致持平，資金溫和偏多但訊號不強。",
    "溫和流出": "外資小幅賣超，匯率大致持平，資金溫和偏空但訊號不強。",
    "中性／觀望": "外資買賣與匯率都無明顯方向，資金處於觀望，暫無清楚訊號。",
}
DIVERGENCE_STATES = {"背離｜熱錢停泊匯市", "背離｜買盤遭拋匯掩蓋", "背離｜匯市先撤"}


# ────────────────────────────────────────────────────────────────────────
# 純函式：信號計算（無 streamlit 依賴）
# ────────────────────────────────────────────────────────────────────────
def build_signals(flow_df: pd.DataFrame, fx_df: pd.DataFrame,
                   window: int, flow_thr: float, fx_thr: float) -> pd.DataFrame:
    """合併籌碼與匯率、計算滾動訊號並分類狀態（向量化）。

    Args:
        flow_df: columns=[date, foreign_net_yi]（外資買賣超 億元）
        fx_df:   columns=[date, usdtwd]（USD/TWD 即期匯率）
        window:  滾動窗格交易日數
        flow_thr: 外資累計買賣超門檻（億元）
        fx_thr:  台幣累計升貶門檻（%）

    Returns:
        DataFrame[date, foreign_net_yi, usdtwd, twd_apprec, roll_flow,
                  roll_apprec, flow_sig, fx_sig, state, is_divergence,
                  interpretation]
    """
    cols = ["date", "foreign_net_yi", "usdtwd", "twd_apprec", "roll_flow",
            "roll_apprec", "flow_sig", "fx_sig", "state", "is_divergence",
            "interpretation"]
    if flow_df.empty or fx_df.empty:
        return pd.DataFrame(columns=cols)

    df = pd.merge(flow_df, fx_df, on="date", how="inner").sort_values("date").reset_index(drop=True)
    if df.empty:
        return pd.DataFrame(columns=cols)

    # 台幣升貶 (%)：USD/TWD 下跌 = 台幣升值（取負號讓正值代表升值，直覺）
    df["twd_apprec"] = -df["usdtwd"].pct_change() * 100.0
    df["roll_flow"]   = df["foreign_net_yi"].rolling(window, min_periods=1).sum()
    df["roll_apprec"] = df["twd_apprec"].rolling(window, min_periods=1).sum()

    f = np.sign(np.where(df["roll_flow"].abs() >= flow_thr, df["roll_flow"], 0)).astype(int)
    x = np.sign(np.where(df["roll_apprec"].abs() >= fx_thr, df["roll_apprec"], 0)).astype(int)
    df["flow_sig"], df["fx_sig"] = f, x

    conds = [
        (f == 1) & (x == 1),
        (f == -1) & (x == -1),
        (x == 1) & (f <= 0),     # 停泊匯市：台幣升但外資沒買
        (f == 1) & (x == -1),    # 拋匯掩蓋：外資買但台幣貶
        (x == -1) & (f >= 0),    # 匯市先撤：台幣貶但股市無賣壓
        (f == 1) & (x == 0),
        (f == -1) & (x == 0),
    ]
    labels = ["同步流入", "同步流出", "背離｜熱錢停泊匯市", "背離｜買盤遭拋匯掩蓋",
              "背離｜匯市先撤", "溫和流入", "溫和流出"]
    df["state"] = np.select(conds, labels, default="中性／觀望")
    df["is_divergence"] = df["state"].isin(DIVERGENCE_STATES)
    df["interpretation"] = df["state"].map(STATE_TEXT)
    return df


def _twd_df_to_series(twd_df: pd.DataFrame) -> pd.DataFrame:
    """yfinance TWD=X DataFrame → 標準 [date, usdtwd] 格式。

    支援多種 column 名（'close' / 'Close' / 'Adj Close'）與 datetime index。
    壞輸入 → 回空 DataFrame（caller 顯示 warning）。
    """
    if twd_df is None or twd_df.empty:
        return pd.DataFrame(columns=["date", "usdtwd"])
    df = twd_df.copy()
    # column 標準化
    close_col = None
    for c in ("close", "Close", "Adj Close", "adj_close"):
        if c in df.columns:
            close_col = c
            break
    if close_col is None:
        return pd.DataFrame(columns=["date", "usdtwd"])
    # index 是日期 → reset 出來
    if df.index.name in (None, "Date", "date") and not pd.api.types.is_integer_dtype(df.index):
        df = df.reset_index()
    # 找 date column
    date_col = None
    for c in ("date", "Date", "index"):
        if c in df.columns:
            date_col = c
            break
    if date_col is None:
        return pd.DataFrame(columns=["date", "usdtwd"])
    out = df[[date_col, close_col]].copy()
    out.columns = ["date", "usdtwd"]
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None)
    out["usdtwd"] = pd.to_numeric(out["usdtwd"], errors="coerce")
    out = out.dropna(subset=["usdtwd"])
    out = out[out["usdtwd"] > 0]   # 過濾假日 / -1 缺值
    return out.sort_values("date").reset_index(drop=True)


# ────────────────────────────────────────────────────────────────────────
# 資料取得：複用既有 finmind_get（leading_indicators.py）
# ────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_foreign_flow_series(days: int, token: str) -> tuple[pd.DataFrame, str]:
    """抓最近 N 天外資買賣超（複用 leading_indicators.finmind_get）。

    Returns:
        (df[date, foreign_net_yi 億元], error_msg or "")
    """
    try:
        from leading_indicators import finmind_get
        end_d = _dt.date.today()
        start_d = end_d - _dt.timedelta(days=days + 14)   # 多抓幾天買日曆 vs 交易日緩衝
        df = finmind_get("TaiwanStockTotalInstitutionalInvestors",
                          "", start_d.strftime("%Y%m%d"),
                          end_d.strftime("%Y%m%d"), token or "")
    except Exception as e:
        return pd.DataFrame(columns=["date", "foreign_net_yi"]), f"FinMind 抓取失敗：{e}"

    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "foreign_net_yi"]), "無資料回傳（可能為非交易日區間）"

    # 過濾「外資」類別（含 Foreign_Investor / 外資及陸資 等變體）
    name_col = next((c for c in ("name", "institutional_investors") if c in df.columns), None)
    if name_col is None:
        return pd.DataFrame(columns=["date", "foreign_net_yi"]), f"FinMind 缺類別欄（cols={list(df.columns)[:8]}）"
    mask = df[name_col].astype(str).str.contains("Foreign|外資", case=False, na=False, regex=True)
    fdf = df.loc[mask].copy()
    if fdf.empty:
        return pd.DataFrame(columns=["date", "foreign_net_yi"]), "FinMind 無 Foreign 類別資料"

    fdf["net"] = pd.to_numeric(fdf["buy"], errors="coerce") - pd.to_numeric(fdf["sell"], errors="coerce")
    out = (fdf.groupby("date", as_index=False)["net"].sum()
              .assign(foreign_net_yi=lambda d: d["net"] / 1e8)
              .loc[:, ["date", "foreign_net_yi"]])
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values("date").reset_index(drop=True), ""


# ────────────────────────────────────────────────────────────────────────
# UI render：在 caller expander 內顯示完整三角交叉視圖
# ────────────────────────────────────────────────────────────────────────
def render_hot_money_section(twd_df: pd.DataFrame, token: str = "",
                                key_prefix: str = "hot_money") -> None:
    """渲染熱錢三角交叉深度視圖。

    Args:
        twd_df: caller 已抓的 yfinance TWD=X DataFrame（_tw2.get('新台幣匯率')）
        token:  FinMind token
        key_prefix: widget key 前綴避免衝突
    """
    fx_df = _twd_df_to_series(twd_df)
    if fx_df.empty:
        st.warning("⚠️ 無新台幣匯率資料（caller 應已抓 TWD=X）；無法計算熱錢訊號。")
        return

    # 控制 panel — 用 inline columns 不污染 sidebar
    cc1, cc2, cc3, cc4 = st.columns([1, 1, 1, 1])
    days = cc1.slider("回看天數", 60, 365, 180, step=30,
                       key=f"{key_prefix}_days",
                       help="抓最近 N 個日曆日的外資 + 匯率")
    window = cc2.slider("觀察窗格（交易日）", 3, 20, 5,
                          key=f"{key_prefix}_window",
                          help="近 N 日累計判斷方向")
    flow_thr = cc3.slider("外資累計門檻（億）", 10, 300, 50, step=10,
                            key=f"{key_prefix}_flow_thr")
    fx_thr = cc4.slider("台幣升貶門檻（%）", 0.1, 2.0, 0.5, step=0.1,
                          key=f"{key_prefix}_fx_thr")

    with st.spinner("📡 抓 FinMind 外資買賣超..."):
        flow_df, ferr = fetch_foreign_flow_series(days, token)
    if ferr:
        st.warning(ferr)
    if flow_df.empty:
        st.info("無法取得外資資料；請確認 FINMIND_TOKEN 與網路。")
        return

    sig = build_signals(flow_df, fx_df, window, flow_thr, fx_thr)
    if sig.empty:
        st.info("外資與匯率資料沒有重疊的交易日（區間太短？）。")
        return

    latest = sig.iloc[-1]

    # 最新判讀
    st.markdown(f"**📍 最新判讀（{pd.Timestamp(latest['date']).date()}）**")
    box = (st.warning if latest["is_divergence"]
           else (st.success if latest["state"] == "同步流入"
                 else st.error if latest["state"] == "同步流出"
                 else st.info))
    box(f"**{latest['state']}**　—　{latest['interpretation']}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("最新外資買賣超", f"{latest['foreign_net_yi']:.1f} 億",
                help="正＝買超(資金進股市)，負＝賣超。")
    m2.metric(f"近{window}日累計外資", f"{latest['roll_flow']:.0f} 億")
    m3.metric("最新美元/台幣", f"{latest['usdtwd']:.3f}",
                help="數字下降＝台幣升值。")
    m4.metric(f"近{window}日台幣升貶", f"{latest['roll_apprec']:+.2f} %")

    # 三角交叉象限圖
    st.markdown("**🧭 三角交叉象限圖**")
    st.caption("橫軸＝外資累計買賣超，縱軸＝台幣累計升貶。右上＝同步流入，左下＝同步流出，"
                "左上/右下對角區＝背離。黑色菱形＝最新位置。")
    plot = sig.dropna(subset=["roll_flow", "roll_apprec"]).copy()
    try:
        import altair as alt
        scale = alt.Scale(
            domain=["同步流入", "同步流出", "背離｜熱錢停泊匯市", "背離｜買盤遭拋匯掩蓋",
                    "背離｜匯市先撤", "溫和流入", "溫和流出", "中性／觀望"],
            range=["#16a34a", "#dc2626", "#f59e0b", "#f97316", "#eab308",
                   "#86efac", "#fca5a5", "#94a3b8"])
        pts = alt.Chart(plot).mark_circle(size=70, opacity=0.55).encode(
            x=alt.X("roll_flow:Q", title=f"近{window}日外資累計買賣超(億)"),
            y=alt.Y("roll_apprec:Q", title=f"近{window}日台幣升貶(%)"),
            color=alt.Color("state:N", scale=scale, title="狀態"),
            tooltip=[alt.Tooltip("date:T", title="日期"),
                     alt.Tooltip("roll_flow:Q", title="累計買賣超(億)", format=".0f"),
                     alt.Tooltip("roll_apprec:Q", title="累計升貶(%)", format=".2f"),
                     alt.Tooltip("state:N", title="狀態")])
        v = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(strokeDash=[4, 4], color="#888").encode(x="x:Q")
        h = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(strokeDash=[4, 4], color="#888").encode(y="y:Q")
        last = alt.Chart(plot.tail(1)).mark_point(
            size=320, shape="diamond", filled=True, color="black").encode(
                x="roll_flow:Q", y="roll_apprec:Q")
        st.altair_chart((pts + v + h + last).properties(height=360),
                          use_container_width=True)
    except Exception as _ce:
        # 預防性硬化（對齊 fund v18.240）：altair 失敗時不再 fallback
        # st.scatter_chart（底層仍 altair 會再炸），改純表格降級
        st.caption(f"⚠️ 象限圖渲染失敗（{type(_ce).__name__}），改顯示原始數據表：")
        _t = plot.tail(20)[["date", "roll_flow", "roll_apprec", "state"]].copy()
        _t["date"] = pd.to_datetime(_t["date"]).dt.date
        st.dataframe(
            _t.rename(columns={"date": "日期", "roll_flow": f"近{window}日外資(億)",
                                  "roll_apprec": f"近{window}日升貶(%)", "state": "狀態"}),
            use_container_width=True, hide_index=True, height=320)

    # 時序圖（雙保險：bar/line 底層也是 altair → 一併防呆）
    cc_a, cc_b = st.columns(2)
    with cc_a:
        st.markdown("**外資每日買賣超（億元）**")
        try:
            st.bar_chart(sig.set_index("date")["foreign_net_yi"], height=220)
        except Exception as _be:
            st.caption(f"⚠️ bar chart 失敗（{type(_be).__name__}），改顯示尾段數據：")
            st.dataframe(sig[["date", "foreign_net_yi"]].tail(10),
                          use_container_width=True, hide_index=True)
    with cc_b:
        st.markdown("**美元/台幣（下降＝台幣升值）**")
        try:
            st.line_chart(sig.set_index("date")["usdtwd"], height=220)
        except Exception as _le:
            st.caption(f"⚠️ line chart 失敗（{type(_le).__name__}），改顯示尾段數據：")
            st.dataframe(sig[["date", "usdtwd"]].tail(10),
                          use_container_width=True, hide_index=True)

    # 背離事件清單
    st.markdown("**⚠️ 近期背離事件**")
    div = sig[sig["is_divergence"]].copy()
    if div.empty:
        st.success("觀察區間內未偵測到明顯背離，資金訊號大致一致。")
    else:
        show = div.sort_values("date", ascending=False).head(15).copy()
        show["日期"] = show["date"].dt.date
        show = show.rename(columns={
            "state": "狀態",
            "roll_flow": f"近{window}日外資(億)",
            "roll_apprec": f"近{window}日升貶(%)",
            "interpretation": "解讀",
        })
        show[f"近{window}日外資(億)"] = show[f"近{window}日外資(億)"].round(0)
        show[f"近{window}日升貶(%)"] = show[f"近{window}日升貶(%)"].round(2)
        st.dataframe(
            show[["日期", "狀態", f"近{window}日外資(億)", f"近{window}日升貶(%)", "解讀"]],
            use_container_width=True, hide_index=True)
