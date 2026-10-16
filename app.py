"""
Nifty F&O Unified Cloud Dashboard
===================================
All-in-one Streamlit Cloud app — 100% Supabase backend, no Google Sheets needed.

Secrets required in Streamlit Cloud Settings → Secrets:
  supabase_url    = "https://xxxx.supabase.co"
  supabase_key    = "your-anon-key"

  angel_api_key   = "YOUR_API_KEY"      (optional)
  angel_client_id = "YOUR_CLIENT_ID"    (optional)
  angel_mpin      = "YOUR_MPIN"         (optional)
  angel_totp_key  = "YOUR_TOTP_SECRET"  (optional)
"""

# ── Standard imports ──────────────────────────────────────────────────────────
import json
import pandas as pd
import numpy as np
import requests
from datetime import datetime, date, timedelta
from io import BytesIO
from xml.etree import ElementTree as ET

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pytz
from streamlit_autorefresh import st_autorefresh

from angel_sync import (
    render_angel_sync_panel, is_angel_configured,
    get_live_positions, get_live_margins
)
from goal_engine import (
    load_goal_cloud, save_goal_cloud,
    calculate_compounding_schedule, evaluate_goal_progress
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Nifty F&O Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═════════════════════════════════════════════════════════════════════════════
TRADE_COLUMNS = [
    "Trade #", "Date", "Time", "Symbol", "Option Type", "Strike", "Expiry",
    "Entry Price", "Exit Price", "Lots", "Lot Size", "Capital Used",
    "Gross P&L", "Brokerage", "STT", "Other Charges", "Net P&L", "Result",
    "Hold Time", "Entry RSI", "Entry ADX", "Supertrend", "Dashboard Said",
    "Lessons Learned", "Notes",
]
DEFAULT_BROKERAGE = 40.0
DEFAULT_STT_PCT   = 0.05
DEFAULT_OTHER     = 15.0

NSE_SYMBOLS = {
    "NIFTY50":    "^NSEI",
    "BANKNIFTY":  "^NSEBANK",
    "FINNIFTY":   "NIFTY_FIN_SERVICE.NS",
    "RELIANCE":   "RELIANCE.NS",
    "TCS":        "TCS.NS",
    "INFY":       "INFY.NS",
    "HDFCBANK":   "HDFCBANK.NS",
    "ICICIBANK":  "ICICIBANK.NS",
    "SBIN":       "SBIN.NS",
    "AXISBANK":   "AXISBANK.NS",
    "BAJFINANCE": "BAJFINANCE.NS",
    "TATAMOTORS": "TATAMOTORS.NS",
    "WIPRO":      "WIPRO.NS",
    "ADANIENT":   "ADANIENT.NS",
    "MARUTI":     "MARUTI.NS",
}

IST = pytz.timezone("Asia/Kolkata")

NSE_HOLIDAYS_2026 = {
    "2026-01-26": "Republic Day",
    "2026-02-18": "Mahashivratri",
    "2026-03-02": "Holi",
    "2026-03-31": "Id-Ul-Fitr (Ramadan Eid)",
    "2026-04-02": "Ram Navami",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-04-30": "Buddha Purnima",
    "2026-05-01": "Maharashtra Day",
    "2026-06-05": "Eid ul-Adha (Bakri Eid)",
    "2026-07-06": "Moharram",
    "2026-08-15": "Independence Day",
    "2026-08-24": "Ganesh Chaturthi",
    "2026-09-08": "Dahi Handi",
    "2026-10-02": "Gandhi Jayanti",
    "2026-10-19": "Dussehra",
    "2026-10-28": "Diwali (Lakshmi Pujan)",
    "2026-10-29": "Diwali (Balipratipada)",
    "2026-11-04": "Gurunanak Jayanti",
    "2026-12-25": "Christmas",
}

SCHEDULED_EVENTS = {
    "2026-10-05": ("RBI MPC Meeting Result", "EXTREME"),
    "2026-10-06": ("RBI MPC Meeting Result (Day 2)", "EXTREME"),
    "2026-12-05": ("RBI MPC Meeting Result", "EXTREME"),
    "2026-02-01": ("Union Budget", "EXTREME"),
    "2026-11-04": ("US Fed FOMC Meeting", "HIGH"),
    "2026-12-15": ("US Fed FOMC Meeting", "HIGH"),
}

WEEKDAY_NOTES = {
    0: ("Monday",    "Gap-up/down risk from weekend news. Wait until 9:45 AM.",          "medium"),
    1: ("Tuesday",   "Most reliable trend day. Best day to trade.",                       "good"),
    2: ("Wednesday", "Most reliable trend day. Best day to trade.",                       "good"),
    3: ("Thursday",  "Weekly Nifty expiry day. Volatile after 1 PM. Exit by 1 PM.",       "medium"),
    4: ("Friday",    "Pre-weekend squaring. Avoid holding positions into weekend.",        "medium"),
    5: ("Saturday",  "Market CLOSED — Weekend.",                                          "closed"),
    6: ("Sunday",    "Market CLOSED — Weekend.",                                          "closed"),
}


# ═════════════════════════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION
# ═════════════════════════════════════════════════════════════════════════════
st.sidebar.image("https://img.icons8.com/color/96/combo-chart.png", width=56)
st.sidebar.title("Nifty F&O Dashboard")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "📂 Navigate",
    [
        "📈 Signal Dashboard",
        "🤝 AI Trading Partner",
        "🎯 Goal & Compounding Engine",
        "🕹️ Angel One Live Cockpit",
        "📰 Market News & Verdict",
        "📊 My Records Dashboard",
        "💰 My Capital",
        "📓 Log Trade",
        "🔄 Angel One Sync",
        "📋 All Trades",
        "📅 Monthly Report",
        "📈 Performance",
        "💸 Expenses",
        "⬇️ Export",
        "🤖 AI Trading Coach",
    ],
    index=0,
)
st.sidebar.markdown("---")

# ── Signal dashboard controls (shown for signal pages only) ──────────────────
if page in ("📈 Signal Dashboard", "🕹️ Angel One Live Cockpit", "📰 Market News & Verdict"):
    symbol   = st.sidebar.selectbox("Symbol", list(NSE_SYMBOLS.keys()), index=0)
    interval = st.sidebar.selectbox("Timeframe", ["1d", "1h", "15m", "5m"], index=0)
    period_map = {"1d": ["6mo","1y","2y","5y"], "1h": ["1mo","3mo","6mo"],
                  "15m": ["5d","1mo","2mo"], "5m": ["5d","1mo"]}
    period = st.sidebar.selectbox("Period", period_map[interval], index=1)
    show_supertrend = st.sidebar.checkbox("Show Supertrend",      value=True)
    show_bb         = st.sidebar.checkbox("Show Bollinger Bands", value=True)
    show_adx        = st.sidebar.checkbox("Show ADX Panel",       value=True)
    show_ai_signal  = st.sidebar.checkbox("Show AI Signal",       value=False)
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Watchlist**")
    watchlist = st.sidebar.multiselect(
        "Monitor symbols", list(NSE_SYMBOLS.keys()),
        default=["NIFTY50", "BANKNIFTY", "RELIANCE", "HDFCBANK"],
    )
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Capital & Risk Settings**")
    total_capital  = st.sidebar.number_input("Total Capital (Rs)", min_value=5000, value=50000, step=5000)
    risk_per_trade = st.sidebar.slider("Max Risk Per Trade (%)", 1, 5, 2)
    lot_size       = st.sidebar.number_input("Lot Size", min_value=1, value=75, step=1,
                                             help="NIFTY=75, BANKNIFTY=30")
    st.sidebar.markdown("---")
    manual_event = st.sidebar.text_input("⚡ Manual Event Override",
                                         placeholder="e.g. RBI rate decision",
                                         help="Forces NO TRADE warning if filled")
    refresh = st.sidebar.button("🔄 Refresh Data")
elif page == "🎯 Goal & Compounding Engine":
    symbol = "NIFTY50"; interval = "1d"; period = "1y"
    total_capital = 50000; risk_per_trade = 2; lot_size = 75
    watchlist = []; manual_event = ""; refresh = False
    st.sidebar.markdown("---")
    st.sidebar.markdown("**🎯 Goal Engine**")
    st.sidebar.info("Set your capital target, start & end dates, and risk guardrails below in the main panel.")
    st.sidebar.markdown("**Quick tip:** Scroll down on the main screen to find the ⚙️ settings form.")
else:
    symbol = "NIFTY50"; interval = "1d"; period = "1y"
    total_capital = 50000; risk_per_trade = 2; lot_size = 75
    watchlist = []; manual_event = ""; refresh = False

# ── Smart Auto-Refresh ───────────────────────────────────────────────────────
# Only auto-refresh on trading pages and only during NSE market hours (9:15–15:30 IST)
_ist_now = datetime.now(pytz.timezone("Asia/Kolkata"))
_market_open  = _ist_now.replace(hour=9,  minute=15, second=0, microsecond=0)
_market_close = _ist_now.replace(hour=15, minute=30, second=0, microsecond=0)
_is_trading_page = page in ("📈 Signal Dashboard", "🕹️ Angel One Live Cockpit", "📰 Market News & Verdict")
_is_market_hours = (_market_open <= _ist_now <= _market_close) and (_ist_now.weekday() < 5)

if _is_trading_page:
    st.sidebar.markdown("---")
    st.sidebar.markdown("**⚡ Live Auto-Refresh**")
    if _is_market_hours:
        _refresh_interval = st.sidebar.select_slider(
            "Refresh every",
            options=[30, 60, 120, 300],
            value=30,
            format_func=lambda x: f"{x}s",
        )
        _refresh_count = st_autorefresh(interval=_refresh_interval * 1000, key="live_autorefresh")
        st.sidebar.success(f"🟢 Market OPEN — refreshing every **{_refresh_interval}s**")
        st.sidebar.caption(f"Refresh #{_refresh_count} | IST: {_ist_now.strftime('%H:%M:%S')}")
    else:
        st_autorefresh(interval=999999999, key="live_autorefresh")   # effectively OFF
        st.sidebar.warning("🔴 Market CLOSED — auto-refresh paused")
        st.sidebar.caption(f"Market opens Mon–Fri 9:15 AM IST")

# Cloud connection status in sidebar
st.sidebar.markdown("---")
try:
    _supa_ok = "supabase_url" in st.secrets and "supabase_key" in st.secrets
except Exception:
    _supa_ok = False

if _supa_ok:
    st.sidebar.success("☁️ Storage: **Supabase Cloud (Live)**")
else:
    st.sidebar.warning("⚠️ Supabase not connected")

angel_ok = is_angel_configured()
if angel_ok:
    st.sidebar.success("✅ Angel One **Configured**")
else:
    st.sidebar.info("ℹ️ Angel One not configured")


# ═════════════════════════════════════════════════════════════════════════════
# SUPABASE HELPERS
# ═════════════════════════════════════════════════════════════════════════════
COL_TO_DB = {
    "Trade #": "trade_num", "Date": "date", "Time": "time",
    "Symbol": "symbol", "Option Type": "option_type", "Strike": "strike",
    "Expiry": "expiry", "Entry Price": "entry_price", "Exit Price": "exit_price",
    "Lots": "lots", "Lot Size": "lot_size", "Capital Used": "capital_used",
    "Gross P&L": "gross_pnl", "Brokerage": "brokerage", "STT": "stt",
    "Other Charges": "other_charges", "Net P&L": "net_pnl", "Result": "result",
    "Hold Time": "hold_time", "Entry RSI": "entry_rsi", "Entry ADX": "entry_adx",
    "Supertrend": "supertrend", "Dashboard Said": "dashboard_said",
    "Lessons Learned": "lessons_learned", "Notes": "notes",
}
DB_TO_COL = {v: k for k, v in COL_TO_DB.items()}


def _supa_client():
    from supabase import create_client
    return create_client(st.secrets["supabase_url"], st.secrets["supabase_key"])


def _is_supa() -> bool:
    try:
        return "supabase_url" in st.secrets and "supabase_key" in st.secrets
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def load_trades() -> pd.DataFrame:
    if not _is_supa():
        return st.session_state.get("trades_df", pd.DataFrame(columns=TRADE_COLUMNS))
    try:
        data = _supa_client().table("trades").select("*").order("trade_num").execute().data
        if not data:
            return pd.DataFrame(columns=TRADE_COLUMNS)
        df = pd.DataFrame(data).rename(columns=DB_TO_COL)
        for col in TRADE_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df[TRADE_COLUMNS]
    except Exception as e:
        st.warning("Could not load trades: {}".format(e))
        return pd.DataFrame(columns=TRADE_COLUMNS)


@st.cache_data(ttl=300, show_spinner=False)
def load_capital() -> dict:
    if not _is_supa():
        return st.session_state.get("cap_data", {
            "initial_capital": 40000.0, "current_capital": 40000.0,
            "start_date": "2025-01-01", "notes": "",
            "history": [{"date": "2025-01-01", "balance": 40000.0, "note": "Initial capital"}],
        })
    try:
        rows = _supa_client().table("capital").select("*").order("date").execute().data
        if not rows:
            return {"initial_capital": 40000.0, "current_capital": 40000.0,
                    "start_date": "2025-01-01", "notes": "",
                    "history": [{"date": "2025-01-01", "balance": 40000.0, "note": "Initial capital"}]}
        history = [{"date": r.get("date",""), "balance": float(r.get("balance", 0)),
                    "note": r.get("note","")} for r in rows]
        latest  = float(rows[-1].get("balance", 40000.0))
        first   = float(rows[0].get("balance",  40000.0))
        return {
            "initial_capital": first,
            "current_capital": latest,
            "start_date":      rows[0].get("date", "2025-01-01"),
            "notes":           rows[-1].get("note", ""),
            "history":         history,
        }
    except Exception as e:
        st.warning("Could not load capital: {}".format(e))
        return {"initial_capital": 40000.0, "current_capital": 40000.0,
                "start_date": "2025-01-01", "notes": "",
                "history": [{"date": "2025-01-01", "balance": 40000.0, "note": "Initial capital"}]}


def save_trades(df: pd.DataFrame):
    load_trades.clear()
    st.session_state.pop("_save_error", None)
    if not _is_supa():
        st.session_state["trades_df"] = df.copy()
        return
    try:
        client = _supa_client()
        client.table("trades").delete().gte("trade_num", 0).execute()
        if df.empty:
            return
        rows = df.copy().rename(columns=COL_TO_DB)
        db_cols = list(COL_TO_DB.values())
        rows = rows[[c for c in db_cols if c in rows.columns]]
        for col in ["trade_num","strike","entry_price","exit_price","lots","lot_size",
                    "capital_used","gross_pnl","brokerage","stt","other_charges","net_pnl","entry_rsi","entry_adx"]:
            if col in rows.columns:
                rows[col] = pd.to_numeric(rows[col], errors="coerce")
        rows = rows.replace([float("inf"), float("-inf")], pd.NA)
        rows = rows.astype(object).where(pd.notnull(rows), None)
        for record in rows.to_dict("records"):
            client.table("trades").insert(record).execute()
        st.cache_data.clear()
    except Exception as e:
        st.session_state["_save_error"] = str(e)
        st.error("Could not save trades: {}".format(e))


def save_capital(data: dict):
    load_capital.clear()
    if not _is_supa():
        st.session_state["cap_data"] = data.copy()
        return
    try:
        client = _supa_client()
        history = data.get("history", [])
        if history:
            client.table("capital").delete().neq("date", "1900-01-01").execute()
            rows = [{"date": h.get("date",""), "balance": float(h.get("balance", 0)),
                     "note": h.get("note","")} for h in history]
            client.table("capital").insert(rows).execute()
        st.cache_data.clear()
    except Exception as e:
        st.error("Could not save capital: {}".format(e))


# ═════════════════════════════════════════════════════════════════════════════
# TRADE STATS HELPERS
# ═════════════════════════════════════════════════════════════════════════════
def get_stats(df: pd.DataFrame) -> dict:
    closed = df[df["Result"].isin(["WIN", "LOSS"])].copy()
    if closed.empty:
        return {k: 0 for k in ["total_trades","wins","losses","win_rate","total_pnl",
                                "best_trade","worst_trade","avg_win","avg_loss",
                                "reward_risk","max_drawdown","total_invested",
                                "total_brokerage","total_charges"]}
    pnl   = pd.to_numeric(closed["Net P&L"],      errors="coerce").fillna(0)
    brok  = pd.to_numeric(closed["Brokerage"],     errors="coerce").fillna(0)
    stt   = pd.to_numeric(closed["STT"],           errors="coerce").fillna(0)
    other = pd.to_numeric(closed["Other Charges"], errors="coerce").fillna(0)
    cap   = pd.to_numeric(closed["Capital Used"],  errors="coerce").fillna(0)
    wins  = closed[closed["Result"] == "WIN"]
    losses= closed[closed["Result"] == "LOSS"]
    equity= pnl.cumsum()
    peak  = equity.cummax()
    dd    = (equity - peak).min()
    avg_win  = pd.to_numeric(wins["Net P&L"],   errors="coerce").mean() if not wins.empty   else 0.0
    avg_loss = pd.to_numeric(losses["Net P&L"], errors="coerce").mean() if not losses.empty else 0.0
    rr = round(avg_win / abs(avg_loss), 2) if avg_loss and avg_loss != 0 else 0.0
    return {
        "total_trades":    len(closed),
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        round(len(wins) / len(closed) * 100, 1),
        "total_pnl":       round(pnl.sum(), 2),
        "best_trade":      round(pnl.max(), 2),
        "worst_trade":     round(pnl.min(), 2),
        "avg_win":         round(avg_win,  2),
        "avg_loss":        round(avg_loss, 2),
        "reward_risk":     rr,
        "max_drawdown":    round(dd, 2),
        "total_invested":  round(cap.sum(), 2),
        "total_brokerage": round(brok.sum(), 2),
        "total_charges":   round((brok + stt + other).sum(), 2),
    }


def get_capital_stats(data: dict) -> dict:
    initial = data.get("initial_capital", 40000.0)
    current = data.get("current_capital", 40000.0)
    pnl     = round(current - initial, 2)
    pct     = round((pnl / initial) * 100, 2) if initial else 0.0
    try:
        start = datetime.strptime(data.get("start_date", "2025-01-01"), "%Y-%m-%d")
        days  = (datetime.now() - start).days
    except Exception:
        days = 0
    return {"initial": initial, "current": current, "pnl": pnl, "pnl_pct": pct,
            "days": days, "history": data.get("history", [])}


def pnl_delta(val):
    return (("▲ Rs {:,.0f}".format(val) if val >= 0 else "▼ Rs {:,.0f}".format(abs(val))),
            ("normal" if val >= 0 else "inverse"))


def _next_trade_num(df):
    if df.empty or df["Trade #"].isna().all():
        return 1
    return int(pd.to_numeric(df["Trade #"], errors="coerce").max()) + 1


# ═════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS (self-contained — no local file imports needed)
# ═════════════════════════════════════════════════════════════════════════════
def _supertrend(df, period=10, multiplier=3.0):
    import ta as _ta
    hl2 = (df["High"] + df["Low"]) / 2
    atr = _ta.volatility.AverageTrueRange(df["High"], df["Low"], df["Close"], window=period).average_true_range()
    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)
    supertrend = pd.Series(index=df.index, dtype=float)
    direction  = pd.Series(index=df.index, dtype=float)
    for i in range(1, len(df)):
        if upper_band.iloc[i] < upper_band.iloc[i - 1] or df["Close"].iloc[i - 1] > upper_band.iloc[i - 1]:
            pass
        else:
            upper_band.iloc[i] = upper_band.iloc[i - 1]
        if lower_band.iloc[i] > lower_band.iloc[i - 1] or df["Close"].iloc[i - 1] < lower_band.iloc[i - 1]:
            pass
        else:
            lower_band.iloc[i] = lower_band.iloc[i - 1]
        if df["Close"].iloc[i] > upper_band.iloc[i - 1]:
            direction.iloc[i] = 1.0;  supertrend.iloc[i] = lower_band.iloc[i]
        elif df["Close"].iloc[i] < lower_band.iloc[i - 1]:
            direction.iloc[i] = -1.0; supertrend.iloc[i] = upper_band.iloc[i]
        else:
            direction.iloc[i] = direction.iloc[i - 1]
            supertrend.iloc[i] = supertrend.iloc[i - 1]
    df["ST_trend"] = direction
    df["ST_value"] = supertrend
    return df


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    import ta as _ta
    df = df.copy()
    close, high, low = df["Close"], df["High"], df["Low"]

    # yfinance 1.x returns Volume=0 for all intraday NSE bars.
    # Replace zeros with NaN so volume-based indicators (VWAP, CMF) use only
    # real volume; fall back to a price-based proxy when all bars are zero.
    raw_vol = df["Volume"].copy().astype(float)
    raw_vol = raw_vol.where(raw_vol > 0, other=np.nan)
    vol_all_nan = raw_vol.isna().all()
    vol = raw_vol if not vol_all_nan else df["Volume"].astype(float)

    df["EMA_9"]   = _ta.trend.EMAIndicator(close, 9).ema_indicator().fillna(close)
    df["EMA_21"]  = _ta.trend.EMAIndicator(close, 21).ema_indicator().fillna(df["EMA_9"])
    df["EMA_50"]  = _ta.trend.EMAIndicator(close, 50).ema_indicator().fillna(df["EMA_21"])
    ema200_raw    = _ta.trend.EMAIndicator(close, 200).ema_indicator()
    df["EMA_200"] = ema200_raw.fillna(df["EMA_50"])

    macd = _ta.trend.MACD(close, 26, 12, 9)
    df["MACD"] = macd.macd().fillna(0.0)
    df["MACD_signal"] = macd.macd_signal().fillna(0.0)
    df["MACD_hist"] = macd.macd_diff().fillna(0.0)

    try:
        adx = _ta.trend.ADXIndicator(high, low, close, 14)
        df["ADX"] = adx.adx().fillna(20.0)
        df["ADX_pos"] = adx.adx_pos().fillna(0.0)
        df["ADX_neg"] = adx.adx_neg().fillna(0.0)
    except Exception:
        df["ADX"] = pd.Series(20.0, index=df.index)
        df["ADX_pos"] = pd.Series(0.0, index=df.index)
        df["ADX_neg"] = pd.Series(0.0, index=df.index)

    df = _supertrend(df)
    if "ST_trend" in df.columns:
        df["ST_trend"] = df["ST_trend"].bfill().fillna(1.0)
        df["ST_value"] = df["ST_value"].bfill().fillna(close)

    try:
        df["RSI"] = _ta.momentum.RSIIndicator(close, 14).rsi().fillna(50.0)
    except Exception:
        df["RSI"] = pd.Series(50.0, index=df.index)

    try:
        bb = _ta.volatility.BollingerBands(close, 20, 2)
        df["BB_upper"] = bb.bollinger_hband().fillna(close * 1.02)
        df["BB_lower"] = bb.bollinger_lband().fillna(close * 0.98)
        df["BB_pct"]   = bb.bollinger_pband().fillna(0.5)
    except Exception:
        df["BB_upper"] = close * 1.02
        df["BB_lower"] = close * 0.98
        df["BB_pct"] = pd.Series(0.5, index=df.index)

    try:
        df["ATR"] = _ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range().bfill().fillna(0.0)
    except Exception:
        df["ATR"] = pd.Series(0.0, index=df.index)

    if vol_all_nan:
        df["VWAP"] = close.rolling(14, min_periods=1).mean().fillna(close)
        df["CMF"]  = pd.Series(0.0, index=df.index)
    else:
        try:
            df["VWAP"] = _ta.volume.VolumeWeightedAveragePrice(high, low, close, vol).volume_weighted_average_price().bfill().fillna(close)
            df["CMF"]  = _ta.volume.ChaikinMoneyFlowIndicator(high, low, close, vol, 20).chaikin_money_flow().fillna(0.0)
        except Exception:
            df["VWAP"] = close
            df["CMF"] = pd.Series(0.0, index=df.index)

    df["EMA_cross"]  = np.where(df["EMA_9"] > df["EMA_21"], 1, -1)
    df["MACD_cross"] = np.where(df["MACD"]  > df["MACD_signal"], 1, -1)
    df["RSI_zone"]   = pd.cut(df["RSI"], bins=[-1, 30, 50, 70, 101],
                               labels=["Oversold", "Bearish", "Bullish", "Overbought"])
    df.dropna(subset=["Close"], inplace=True)
    return df


def get_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        raise ValueError("Empty dataframe passed to get_summary")
    last = df.iloc[-1]
    return {
        "close":       round(float(last["Close"]),       2),
        "rsi":         round(float(last.get("RSI", 50.0)),         2),
        "macd":        round(float(last.get("MACD", 0.0)),        2),
        "macd_signal": round(float(last.get("MACD_signal", 0.0)), 2),
        "adx":         round(float(last.get("ADX", 20.0)),         2),
        "atr":         round(float(last.get("ATR", 0.0)),         2),
        "bb_pct":      round(float(last.get("BB_pct", 0.5)),      2),
        "supertrend":  "BULLISH" if last.get("ST_trend", 1) == 1 else "BEARISH",
        "ema_cross":   "BULLISH" if last.get("EMA_cross", 1) == 1 else "BEARISH",
        "rsi_zone":    str(last.get("RSI_zone", "Bullish")),
        "vwap":        round(float(last.get("VWAP", last["Close"])),  2),
        "cmf":         round(float(last.get("CMF", 0.0)),   4),
    }


@st.cache_data(ttl=30)
def load_chart_data(sym, ivl, per):
    import yfinance as yf
    ticker = NSE_SYMBOLS.get(sym, sym)
    # Do NOT pass a custom session — yfinance 0.2.x+ requires curl_cffi internally.
    df = yf.download(ticker, period=per, interval=ivl, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError("No data for {}".format(sym))
    # yfinance 1.x returns a MultiIndex (price_type, ticker) — flatten to single level.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    df.sort_index(inplace=True)
    df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
    return add_all_indicators(df)


# ═════════════════════════════════════════════════════════════════════════════
# TRADE DECISION ENGINE
# ═════════════════════════════════════════════════════════════════════════════
def compute_decision(s: dict) -> dict:
    bull_score, bear_score = 0, 0
    reasons_bull, reasons_bear, warnings = [], [], []
    rsi = s["rsi"]

    if rsi > 65:
        warnings.append("RSI {:.1f} — OVERBOUGHT: bounce risk HIGH. Avoid new CALL entries.".format(rsi))
        bear_score += 1
    elif rsi < 35:
        warnings.append("RSI {:.1f} — OVERSOLD: short-squeeze risk HIGH. Avoid new PUT entries.".format(rsi))
        bull_score += 1
    elif rsi > 55:
        bull_score += 1; reasons_bull.append("RSI {:.1f} in Bullish zone".format(rsi))
    elif rsi < 45:
        bear_score += 1; reasons_bear.append("RSI {:.1f} in Bearish zone".format(rsi))
    else:
        warnings.append("RSI {:.1f} — Neutral. No clear momentum edge.".format(rsi))

    if s["macd"] - s["macd_signal"] > 0:
        bull_score += 1; reasons_bull.append("MACD above Signal (bullish crossover)")
    else:
        bear_score += 1; reasons_bear.append("MACD below Signal (bearish crossover)")

    if s["supertrend"] == "BULLISH":
        bull_score += 1; reasons_bull.append("Supertrend BULLISH")
    else:
        bear_score += 1; reasons_bear.append("Supertrend BEARISH")

    if s["ema_cross"] == "BULLISH":
        bull_score += 1; reasons_bull.append("EMA Cross BULLISH (fast > slow)")
    else:
        bear_score += 1; reasons_bear.append("EMA Cross BEARISH (fast < slow)")

    if s["adx"] > 25:
        if bear_score > bull_score:
            bear_score += 1; reasons_bear.append("ADX {:.1f} — Strong trend confirms BEAR".format(s["adx"]))
        elif bull_score > bear_score:
            bull_score += 1; reasons_bull.append("ADX {:.1f} — Strong trend confirms BULL".format(s["adx"]))
    else:
        warnings.append("ADX {:.1f} — Weak trend. Market may be ranging.".format(s["adx"]))

    if s["close"] > s["vwap"]:
        bull_score += 1; reasons_bull.append("Price above VWAP (institutional support)")
    else:
        bear_score += 1; reasons_bear.append("Price below VWAP (institutional selling)")

    if s["cmf"] > 0.05:
        bull_score += 1; reasons_bull.append("CMF {:.2f} — Money flowing IN".format(s["cmf"]))
    elif s["cmf"] < -0.05:
        bear_score += 1; reasons_bear.append("CMF {:.2f} — Money flowing OUT".format(s["cmf"]))

    total = bull_score + bear_score
    if total == 0:
        confidence, direction = 0.0, "WAIT"
    elif bear_score > bull_score:
        confidence = bear_score / total
        direction  = "PUT" if confidence >= 0.6 and rsi > 35 else "WAIT"
    elif bull_score > bear_score:
        confidence = bull_score / total
        direction  = "CALL" if confidence >= 0.6 and rsi < 65 else "WAIT"
    else:
        confidence, direction = 0.5, "WAIT"

    return {"direction": direction, "confidence": confidence,
            "bull_score": bull_score, "bear_score": bear_score,
            "reasons_bull": reasons_bull, "reasons_bear": reasons_bear,
            "warnings": warnings}


def compute_strike_advice(ltp, atr, capital, risk_pct, l_size, premium=100.0):
    atm          = round(ltp / 50) * 50
    max_loss_rs  = capital * (risk_pct / 100)
    sl_premium   = premium * 0.30
    max_lots     = max(1, int(max_loss_rs / (sl_premium * l_size)))
    target1      = round(ltp - (atr * 1.5) / 50) * 50
    target2      = round(ltp - (atr * 3.0) / 50) * 50
    return {"atm": atm, "otm_1": atm - 100, "max_lots": max_lots,
            "max_loss": round(max_loss_rs, 0), "sl_premium": round(sl_premium, 1),
            "target1": target1, "target2": target2}


# ═════════════════════════════════════════════════════════════════════════════
# DAY VERDICT ENGINE
# ═════════════════════════════════════════════════════════════════════════════
def get_time_window(now_ist: datetime) -> dict:
    total = now_ist.hour * 60 + now_ist.minute
    windows = [
        (0,         9*60+15,  "Pre-Market",          "❌ Market not open yet.", "closed"),
        (9*60+15,   9*60+45,  "Opening 9:15–9:44",   "🚫 Watch only. No trades.", "avoid"),
        (9*60+45,   10*60+30, "Early 9:45–10:29",    "⚠️ Wait for clear direction.", "caution"),
        (10*60+30,  13*60,    "Prime 10:30–12:59",   "✅ BEST window. All signals reliable.", "best"),
        (13*60,     14*60+30, "Mid 1:00–2:29 PM",    "✅ Still valid. Watch for slowdown.", "ok"),
        (14*60+30,  15*60+15, "Late 2:30–3:14 PM",   "⚠️ Risky. Exit profitable trades.", "caution"),
        (15*60+15,  15*60+30, "Close 3:15–3:30 PM",  "🚫 CLOSE ONLY. No new positions.", "avoid"),
        (15*60+30,  24*60,    "After-Market",         "❌ Market closed.", "closed"),
    ]
    for s, e, label, note, status in windows:
        if s <= total < e:
            return {"label": label, "note": note, "status": status}
    return {"label": "Unknown", "note": "Check manually.", "status": "closed"}


@st.cache_data(ttl=30)
def fetch_nifty_gap() -> dict:
    try:
        import yfinance as yf
        # Do NOT pass a custom session — yfinance 0.2.x+ requires curl_cffi internally.
        hist = yf.Ticker("^NSEI").history(period="5d", interval="1d")
        if len(hist) >= 2:
            prev = float(hist["Close"].iloc[-2])
            last = float(hist["Close"].iloc[-1])
            gap  = round(last - prev, 2)
            pct  = round((gap / prev) * 100, 2)
            return {"ok": True, "gap_pts": gap, "gap_pct": pct,
                    "direction": "UP" if gap >= 0 else "DOWN", "prev": prev, "last": last}
    except Exception:
        pass
    return {"ok": False}


def build_day_verdict(manual_ev: str) -> dict:
    now_ist   = datetime.now(IST)
    today_str = now_ist.strftime("%Y-%m-%d")
    weekday   = now_ist.weekday()
    day_name, day_note, day_status = WEEKDAY_NOTES[weekday]
    holiday_name = NSE_HOLIDAYS_2026.get(today_str)
    is_weekend   = weekday >= 5

    market_status = "HOLIDAY" if holiday_name else ("WEEKEND" if is_weekend else "OPEN_DAY")
    event_info    = SCHEDULED_EVENTS.get(today_str)
    has_extreme   = False; has_high = False; event_name = ""

    if manual_ev.strip():
        has_extreme = True; event_name = manual_ev.strip()
    elif event_info:
        event_name = event_info[0]
        if event_info[1] == "EXTREME": has_extreme = True
        else: has_high = True

    tw       = get_time_window(now_ist)
    gap_data = fetch_nifty_gap()
    checks   = []

    if market_status in ("HOLIDAY", "WEEKEND"):
        reason = holiday_name if market_status == "HOLIDAY" else "Weekend"
        checks.append(("❌", "NSE Status", "CLOSED — {}".format(reason), False))
    else:
        if day_status == "good":
            checks.append(("✅", "Day of Week", "{} — Best trading day.".format(day_name), True))
        elif day_status == "medium":
            checks.append(("⚠️", "Day of Week", "{} — {}".format(day_name, day_note), None))
        else:
            checks.append(("❌", "Day of Week", day_name, False))

        if has_extreme:
            checks.append(("❌", "Scheduled Event", "EXTREME: {} — DO NOT TRADE.".format(event_name), False))
        elif has_high:
            checks.append(("⚠️", "Scheduled Event", "HIGH IMPACT: {} — Extreme caution.".format(event_name), None))
        else:
            checks.append(("✅", "Scheduled Event", "No high-impact event today.", True))

        if tw["status"] in ("best", "ok"):
            checks.append(("✅", "Time Window", "{} — {}".format(tw["label"], tw["note"]), True))
        elif tw["status"] == "caution":
            checks.append(("⚠️", "Time Window", "{} — {}".format(tw["label"], tw["note"]), None))
        else:
            checks.append(("❌", "Time Window", "{} — {}".format(tw["label"], tw["note"]), False))

        if gap_data["ok"]:
            gabs = abs(gap_data["gap_pts"])
            icon = "✅" if gabs <= 150 else "⚠️"
            txt  = "{} {:.0f} pts ({:.2f}%) — {}".format(
                "▲" if gap_data["direction"]=="UP" else "▼", gabs, abs(gap_data["gap_pct"]),
                "Normal." if gabs <= 150 else "LARGE GAP — wait for gap-fill first.")
            checks.append((icon, "Nifty Gap", txt, True if gabs <= 150 else None))
        else:
            checks.append(("ℹ️", "Nifty Gap", "Gap data unavailable — check manually.", None))

        if weekday == 3:
            checks.append(("⚠️", "Weekly Expiry", "Thursday expiry — volatile after 1 PM. Exit by 1 PM if in profit.", None))
        else:
            checks.append(("✅", "Weekly Expiry", "Expiry in {} day(s). No pressure today.".format((3 - weekday) % 7), True))

    fail  = sum(1 for _,_,_,p in checks if p is False)
    warn  = sum(1 for _,_,_,p in checks if p is None)
    passn = sum(1 for _,_,_,p in checks if p is True)

    if market_status in ("HOLIDAY","WEEKEND"):
        v,vi,vbg,vbd,vc = "NSE CLOSED TODAY","🚫","#450a0a","#dc2626","#fca5a5"
        vd = "Market closed. Come back on next trading day."
    elif has_extreme:
        v,vi,vbg,vbd,vc = "NO TRADE — EXTREME EVENT","🚫","#450a0a","#dc2626","#fca5a5"
        vd = "High-impact event today. Signals unreliable. Sit out."
    elif tw["status"] in ("closed","avoid"):
        v,vi,vbg,vbd,vc = "NOT YET / MARKET CLOSED","⏳","#422006","#d97706","#fcd34d"
        vd = tw["note"]
    elif fail == 0 and warn <= 1:
        v,vi,vbg,vbd,vc = "GREEN LIGHT — OK TO TRADE","🟢","#14532d","#16a34a","#86efac"
        vd = "All checks passed. Use 9-Gate entry checklist before any trade."
    elif fail == 0 and warn >= 2:
        v,vi,vbg,vbd,vc = "CAUTION — TRADE CAREFULLY","🟡","#422006","#d97706","#fcd34d"
        vd = "Multiple caution flags. Trade half lot size. Strict 9 Gates."
    else:
        v,vi,vbg,vbd,vc = "NO TRADE TODAY","🔴","#450a0a","#dc2626","#fca5a5"
        vd = "Hard stops triggered. Risk > reward today. Sit out."

    return dict(verdict=v, verdict_icon=vi, verdict_bg=vbg, verdict_border=vbd,
                verdict_color=vc, verdict_detail=vd, checks=checks,
                market_status=market_status, has_extreme_event=has_extreme, tw=tw,
                holiday_name=holiday_name, now_ist=now_ist, day_name=day_name,
                day_status=day_status, day_note=day_note, gap_data=gap_data,
                event_name=event_name, pass_count=passn, warn_count=warn, fail_count=fail)


# ═════════════════════════════════════════════════════════════════════════════
# NEWS FETCHER
# ═════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=1800)
def fetch_market_news() -> list:
    feeds = [
        ("https://news.google.com/rss/search?q=nifty+RBI+sensex+india+market&hl=en-IN&gl=IN&ceid=IN:en", "Google News"),
        ("https://feeds.feedburner.com/ndtvprofit-latest-news", "NDTV Profit"),
    ]
    HIGH_KW = ["rbi","rate","repo","fed","fomc","budget","gdp","cpi","inflation",
               "election","war","crude","rupee","circuit","crash","rally","fii",
               "ban","sebi","tax","stt","f&o","expiry","result","earnings"]
    articles = []
    for url, src in feeds:
        try:
            resp = requests.get(url, timeout=8, headers={"User-Agent":"Mozilla/5.0"})
            if resp.status_code != 200: continue
            root = ET.fromstring(resp.content)
            ch   = root.find("channel")
            if ch is None: continue
            for item in ch.findall("item")[:15]:
                title = (item.findtext("title") or "").strip()
                link  = (item.findtext("link")  or "").strip()
                pub   = (item.findtext("pubDate") or "").strip()
                if not title: continue
                tl    = title.lower()
                match = [k for k in HIGH_KW if k in tl]
                if match:
                    impact = "🔴 HIGH" if any(k in tl for k in ["rbi","rate","repo","fed","fomc","budget","circuit","crash","election","war","ban"]) else "🟡 MEDIUM"
                else:
                    impact = "⚪ LOW"
                articles.append({"title":title,"link":link,"published":pub[:25],"source":src,
                                  "impact":impact,"keywords":", ".join(match[:4]) or "—"})
        except Exception:
            continue
    order = {"🔴 HIGH":0,"🟡 MEDIUM":1,"⚪ LOW":2}
    articles.sort(key=lambda x: order.get(x["impact"],3))
    return articles


# ═════════════════════════════════════════════════════════════════════════════
# SHARED VERDICT BADGE (compact — used on signal page header)
# ═════════════════════════════════════════════════════════════════════════════
def render_verdict_badge(vdict: dict):
    st.markdown(
        "<div style='background:{bg};border:1.5px solid {bd};border-radius:8px;"
        "padding:10px 18px;display:flex;align-items:center;justify-content:space-between;"
        "margin-bottom:14px;flex-wrap:wrap;gap:8px'>"
        "<span style='font-size:16px;font-weight:800;color:{col}'>{icon} {v}</span>"
        "<span style='font-size:12px;color:#6b7280'>"
        "✅{p} ⚠️{w} ❌{f} | {t} | "
        "<a href='#' style='color:{col};text-decoration:none'>→ See full report in 📰 News tab</a>"
        "</span></div>".format(
            bg=vdict["verdict_bg"], bd=vdict["verdict_border"], col=vdict["verdict_color"],
            icon=vdict["verdict_icon"], v=vdict["verdict"],
            p=vdict["pass_count"], w=vdict["warn_count"], f=vdict["fail_count"],
            t=vdict["now_ist"].strftime("%I:%M %p IST"),
        ), unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
# CANDLESTICK PATTERN DETECTOR
# ═════════════════════════════════════════════════════════════════════════════
def detect_candle_patterns(df: pd.DataFrame) -> list:
    if len(df) < 3:
        return []
    c0 = df.iloc[-1]; c1 = df.iloc[-2]; c2 = df.iloc[-3]
    o0,h0,lo0,cl0 = float(c0["Open"]),float(c0["High"]),float(c0["Low"]),float(c0["Close"])
    o1,h1,lo1,cl1 = float(c1["Open"]),float(c1["High"]),float(c1["Low"]),float(c1["Close"])
    o2,h2,lo2,cl2 = float(c2["Open"]),float(c2["High"]),float(c2["Low"]),float(c2["Close"])
    body0  = abs(cl0-o0); body1 = abs(cl1-o1)
    range0 = h0-lo0 if h0>lo0 else 0.0001
    range1 = h1-lo1 if h1>lo1 else 0.0001
    patterns = []
    if cl1<o1 and cl0>o0 and o0<=cl1 and cl0>=o1 and body0>body1*0.9:
        patterns.append({"name":"Bullish Engulfing","signal":"CALL","strength":"STRONG",
            "desc":"Current candle fully engulfs the prior bearish candle — buyers have taken control."})
    if cl1>o1 and cl0<o0 and o0>=cl1 and cl0<=o1 and body0>body1*0.9:
        patterns.append({"name":"Bearish Engulfing","signal":"PUT","strength":"STRONG",
            "desc":"Current candle fully engulfs the prior bullish candle — sellers have taken control."})
    lw0 = min(o0,cl0)-lo0; uw0 = h0-max(o0,cl0)
    if lw0>=2*body0 and uw0<=body0*0.5 and cl0>o0 and cl1<o1:
        patterns.append({"name":"Hammer","signal":"CALL","strength":"MEDIUM",
            "desc":"Long lower wick after a down candle — bulls rejected lower prices."})
    uw0 = h0-max(o0,cl0); lw0 = min(o0,cl0)-lo0
    if uw0>=2*body0 and lw0<=body0*0.5 and cl0<o0 and cl1>o1:
        patterns.append({"name":"Shooting Star","signal":"PUT","strength":"MEDIUM",
            "desc":"Long upper wick after an up candle — bears rejected higher prices."})
    if body0<=range0*0.08:
        patterns.append({"name":"Doji","signal":"WAIT","strength":"WEAK",
            "desc":"Open ~= Close. Market indecision. Wait for next candle."})
    if cl0>o0 and body0>=range0*0.85 and cl0>=h0*0.998:
        patterns.append({"name":"Bullish Marubozu","signal":"CALL","strength":"STRONG",
            "desc":"Large bull candle with almost no wicks — strong buying momentum."})
    if cl0<o0 and body0>=range0*0.85 and o0>=h0*0.998:
        patterns.append({"name":"Bearish Marubozu","signal":"PUT","strength":"STRONG",
            "desc":"Large bear candle with almost no wicks — strong selling momentum."})
    if cl2<o2 and body1<=range1*0.3 and cl0>o0 and cl0>(o2+cl2)/2:
        patterns.append({"name":"Morning Star","signal":"CALL","strength":"STRONG",
            "desc":"3-candle reversal: big bear, small body, big bull. Reversal to upside likely."})
    if cl2>o2 and body1<=range1*0.3 and cl0<o0 and cl0<(o2+cl2)/2:
        patterns.append({"name":"Evening Star","signal":"PUT","strength":"STRONG",
            "desc":"3-candle reversal: big bull, small body, big bear. Reversal to downside likely."})
    if h0<h1 and lo0>lo1:
        patterns.append({"name":"Inside Bar","signal":"WAIT","strength":"WEAK",
            "desc":"Current candle inside prior range. Breakout pending — wait for next candle."})
    return patterns


# ═════════════════════════════════════════════════════════════════════════════
# PRECISION ENTRY SIGNAL ENGINE
# ═════════════════════════════════════════════════════════════════════════════
def compute_precision_signal(df: pd.DataFrame, summary: dict, decision: dict, vdict: dict) -> dict:
    now_ist   = datetime.now(IST)
    tw        = vdict["tw"]
    reasons   = []; warnings = []; score = 0; max_score = 0; direction = "WAIT"

    if tw["status"] not in ("best","ok","caution"):
        return {"action":"NO TRADE","direction":"WAIT","entry_time":now_ist.strftime("%H:%M"),
                "exit_5m":"—","exit_10m":"—","exit_15m":"—","signal_score":0,"max_score":1,
                "pattern_name":"N/A","pattern_desc":tw["note"],"patterns":[],"reasons":[],
                "tw_status":tw["status"],"warnings":["Market window: {} — {}".format(tw["label"],tw["note"])],
                "bull_votes":0,"bear_votes":0}
    if vdict.get("has_extreme_event"):
        return {"action":"NO TRADE","direction":"WAIT","entry_time":now_ist.strftime("%H:%M"),
                "exit_5m":"—","exit_10m":"—","exit_15m":"—","signal_score":0,"max_score":1,
                "pattern_name":"N/A","pattern_desc":"Extreme event today — no trades.","patterns":[],
                "reasons":[],"tw_status":tw["status"],
                "warnings":["Extreme event: {}".format(vdict.get("event_name",""))],"bull_votes":0,"bear_votes":0}

    patterns   = detect_candle_patterns(df)
    top_pat    = next((p for p in patterns if p["signal"]!="WAIT"), None)
    pat_name   = top_pat["name"]     if top_pat else "No clear pattern"
    pat_desc   = top_pat["desc"]     if top_pat else "No dominant candlestick pattern on current candle."
    pat_signal = top_pat["signal"]   if top_pat else "WAIT"
    pat_strength = top_pat["strength"] if top_pat else "WEAK"

    max_score += 2
    if pat_signal != "WAIT":
        pat_pts = {"STRONG":2,"MEDIUM":1,"WEAK":0}[pat_strength]
        score  += pat_pts
        if pat_pts > 0:
            reasons.append("Candle: {} ({}) -> {}".format(pat_name,pat_strength,pat_signal))

    max_score += 2
    macd_bull = summary["macd"] > summary["macd_signal"]
    macd_hist_rising = False
    if len(df) >= 2:
        h_now  = float(df["MACD_hist"].iloc[-1]); h_prev = float(df["MACD_hist"].iloc[-2])
        macd_hist_rising = h_now > h_prev
    if macd_bull and macd_hist_rising:
        score += 2; reasons.append("MACD above signal AND histogram rising (strong bull)")
    elif macd_bull:
        score += 1; reasons.append("MACD above signal (mild bull)")
    elif not macd_bull and not macd_hist_rising:
        score += 2; reasons.append("MACD below signal AND histogram falling (strong bear)")
    elif not macd_bull:
        score += 1; reasons.append("MACD below signal (mild bear)")

    max_score += 1; rsi = summary["rsi"]
    if 40 <= rsi <= 60:
        warnings.append("RSI {:.1f} neutral — no decisive momentum.".format(rsi))
    elif 55 < rsi <= 65:
        score += 1; reasons.append("RSI {:.1f} bullish zone".format(rsi))
    elif rsi > 65:
        warnings.append("RSI {:.1f} OVERBOUGHT — CALL risky.".format(rsi)); score += 1
    elif 35 <= rsi < 45:
        score += 1; reasons.append("RSI {:.1f} bearish zone".format(rsi))
    elif rsi < 35:
        warnings.append("RSI {:.1f} OVERSOLD — PUT risky.".format(rsi)); score += 1

    max_score += 1
    if summary["supertrend"] != "WAIT":
        score += 1; reasons.append("Supertrend: {}".format(summary["supertrend"]))

    max_score += 1; above_vwap = summary["close"] > summary["vwap"]
    score += 1
    reasons.append("Price {} VWAP".format("above" if above_vwap else "below"))

    max_score += 1
    if summary["adx"] > 25:
        score += 1; reasons.append("ADX {:.1f} strong trend".format(summary["adx"]))
    else:
        warnings.append("ADX {:.1f} weak — choppy, reduce size.".format(summary["adx"]))

    max_score += 1; ema_bull = summary["ema_cross"] == "BULLISH"; score += 1
    reasons.append("EMA Cross: {}".format(summary["ema_cross"]))

    bull_votes = 0; bear_votes = 0
    if pat_signal=="CALL": bull_votes += 2 if pat_strength=="STRONG" else 1
    if pat_signal=="PUT":  bear_votes += 2 if pat_strength=="STRONG" else 1
    if macd_bull:          bull_votes += 2 if macd_hist_rising else 1
    else:                  bear_votes += 2 if not macd_hist_rising else 1
    if above_vwap:         bull_votes += 1
    else:                  bear_votes += 1
    if ema_bull:           bull_votes += 1
    else:                  bear_votes += 1
    if summary["supertrend"]=="BULLISH": bull_votes += 1
    else:                                bear_votes += 1
    if 55 < rsi <= 65: bull_votes += 1
    if 35 <= rsi < 45: bear_votes += 1
    if rsi > 65:       bear_votes += 1
    if rsi < 35:       bull_votes += 1

    total_votes = bull_votes + bear_votes
    if total_votes == 0:
        direction = "WAIT"
    elif bull_votes > bear_votes:
        direction = "CALL" if (bull_votes/total_votes) >= 0.55 else "WAIT"
    else:
        direction = "PUT"  if (bear_votes/total_votes) >= 0.55 else "WAIT"

    min_score = max(4, int(max_score * 0.55))
    if score < min_score:
        direction = "WAIT"
        warnings.append("Score {}/{} below threshold {} — no entry.".format(score,max_score,min_score))

    action = {"CALL":"🟢 BUY CALL NOW","PUT":"🔴 BUY PUT NOW"}.get(direction,"🟡 WAIT — No Entry")
    entry_dt = now_ist
    return {
        "action":action,"direction":direction,"entry_time":entry_dt.strftime("%H:%M"),
        "exit_5m":(entry_dt+timedelta(minutes=5)).strftime("%H:%M"),
        "exit_10m":(entry_dt+timedelta(minutes=10)).strftime("%H:%M"),
        "exit_15m":(entry_dt+timedelta(minutes=15)).strftime("%H:%M"),
        "signal_score":score,"max_score":max_score,"pattern_name":pat_name,
        "pattern_desc":pat_desc,"patterns":patterns,"reasons":reasons,
        "warnings":warnings,"bull_votes":bull_votes,"bear_votes":bear_votes,"tw_status":tw["status"],
    }


def render_precision_entry_panel(df: pd.DataFrame, ps: dict, interval: str):
    direction = ps.get("direction","WAIT"); score = ps["signal_score"]; max_sc = ps["max_score"]
    score_pct = int(score/max_sc*100) if max_sc>0 else 0
    action    = ps["action"]
    if direction=="CALL":   bg,border,col = "#0f2e1a","#10b981","#10b981"
    elif direction=="PUT":  bg,border,col = "#2e0f0f","#ef4444","#ef4444"
    else:                   bg,border,col = "#1e1e2e","#f59e0b","#f59e0b"

    st.markdown(
        "<div style='background:{bg};border:2px solid {bd};border-radius:10px;padding:16px 20px;margin-bottom:6px'>"
        "<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px'>"
        "<div><span style='font-size:22px;font-weight:900;color:{col}'>{action}</span><br>"
        "<span style='font-size:12px;color:#94a3b8'>Based on last candle ({ivl}) + RSI, MACD, Supertrend, VWAP, EMA</span></div>"
        "<div style='text-align:right'><span style='font-size:13px;color:#cbd5e1'>Signal Score</span><br>"
        "<span style='font-size:20px;font-weight:800;color:{col}'>{sc}/{mx} ({pct}%)</span></div></div>"
        "<div style='display:flex;gap:16px;margin-top:14px;flex-wrap:wrap'>"
        "<div style='background:#0f172a;border-radius:8px;padding:10px 14px;min-width:110px;text-align:center'>"
        "<div style='font-size:11px;color:#64748b'>ENTER AT</div>"
        "<div style='font-size:20px;font-weight:800;color:{col}'>{etime}</div></div>"
        "<div style='background:#0f172a;border-radius:8px;padding:10px 14px;min-width:110px;text-align:center'>"
        "<div style='font-size:11px;color:#64748b'>EXIT BY (5 min)</div>"
        "<div style='font-size:18px;font-weight:700;color:#fbbf24'>{e5}</div></div>"
        "<div style='background:#0f172a;border-radius:8px;padding:10px 14px;min-width:110px;text-align:center'>"
        "<div style='font-size:11px;color:#64748b'>EXIT BY (10 min)</div>"
        "<div style='font-size:18px;font-weight:700;color:#fbbf24'>{e10}</div></div>"
        "<div style='background:#0f172a;border-radius:8px;padding:10px 14px;min-width:110px;text-align:center'>"
        "<div style='font-size:11px;color:#64748b'>EXIT BY (15 min)</div>"
        "<div style='font-size:18px;font-weight:700;color:#fbbf24'>{e15}</div></div>"
        "</div></div>".format(
            bg=bg,bd=border,col=col,action=action,ivl=interval,
            sc=score,mx=max_sc,pct=score_pct,
            etime=ps["entry_time"],e5=ps["exit_5m"],e10=ps["exit_10m"],e15=ps["exit_15m"],
        ), unsafe_allow_html=True)

    if ps["pattern_name"] not in ("No clear pattern","N/A"):
        st.markdown(
            "<div style='background:#1e293b;border:1px solid #334155;border-radius:6px;"
            "padding:8px 14px;margin:6px 0;font-size:13px'>"
            "Candle Pattern: <span style='color:#fbbf24'>{}</span> — {}</div>".format(
                ps["pattern_name"], ps["pattern_desc"]), unsafe_allow_html=True)

    if ps.get("patterns"):
        all_pats = [p for p in ps["patterns"] if p["signal"]!="WAIT"]
        if all_pats:
            with st.expander("All detected candle patterns ({})".format(len(all_pats)), expanded=False):
                for p in all_pats:
                    sig_col = "#10b981" if p["signal"]=="CALL" else "#ef4444"
                    st.markdown(
                        "<span style='color:{col};font-weight:700'>[{sig}]</span> <b>{name}</b> — {desc}"
                        " <span style='font-size:11px;color:#64748b'>({strength})</span>".format(
                            col=sig_col,sig=p["signal"],name=p["name"],desc=p["desc"],strength=p["strength"]),
                        unsafe_allow_html=True)

    rc1,rc2 = st.columns(2)
    with rc1:
        if ps["reasons"]:
            st.markdown("**Signal Reasons**")
            for r in ps["reasons"]: st.markdown("- " + r)
    with rc2:
        for w in ps.get("warnings",[]): st.warning("⚠️ " + w)

    if len(df) >= 5:
        look_back = min(30,len(df)); df_mini = df.tail(look_back).copy()
        fig_mini = make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=0.04,
                                  row_heights=[0.75,0.25],
                                  subplot_titles=("Last {} Candles — Signal Point".format(look_back),"Volume"))
        fig_mini.add_trace(go.Candlestick(x=df_mini.index,open=df_mini["Open"],high=df_mini["High"],
            low=df_mini["Low"],close=df_mini["Close"],name="Price",
            increasing_line_color="#26a69a",decreasing_line_color="#ef5350"),row=1,col=1)
        fig_mini.add_trace(go.Scatter(x=df_mini.index,y=df_mini["EMA_9"],name="EMA9",
            line=dict(color="#f39c12",width=1),opacity=0.8),row=1,col=1)
        fig_mini.add_trace(go.Scatter(x=df_mini.index,y=df_mini["EMA_21"],name="EMA21",
            line=dict(color="#3498db",width=1),opacity=0.8),row=1,col=1)
        fig_mini.add_trace(go.Scatter(x=df_mini.index,y=df_mini["VWAP"],name="VWAP",
            line=dict(color="#ffffff",width=1,dash="dot"),opacity=0.5),row=1,col=1)
        last_ts = df_mini.index[-1]
        last_hi = float(df_mini["High"].iloc[-1]); last_lo = float(df_mini["Low"].iloc[-1])
        if direction=="CALL":   arrow_y,arrow_ay,arrow_color,arrow_text = last_lo*0.998,-40,"#10b981","BUY CALL"
        elif direction=="PUT":  arrow_y,arrow_ay,arrow_color,arrow_text = last_hi*1.002, 40,"#ef4444","BUY PUT"
        else:                   arrow_y = None
        if arrow_y is not None:
            fig_mini.add_annotation(x=last_ts,y=arrow_y,
                text="<b>{}</b><br>{} IST".format(arrow_text,ps["entry_time"]),
                showarrow=True,arrowhead=2,arrowsize=1.5,arrowcolor=arrow_color,ax=0,ay=arrow_ay,
                font=dict(color=arrow_color,size=12),bgcolor="#0f172a",bordercolor=arrow_color,borderwidth=1)
        vol_c = ["#26a69a" if df_mini["Close"].iloc[i]>=df_mini["Open"].iloc[i] else "#ef5350" for i in range(len(df_mini))]
        fig_mini.add_trace(go.Bar(x=df_mini.index,y=df_mini["Volume"],name="Vol",marker_color=vol_c,opacity=0.7),row=2,col=1)
        fig_mini.update_layout(height=400,template="plotly_dark",xaxis_rangeslider_visible=False,
            showlegend=True,legend=dict(orientation="h",yanchor="bottom",y=1.02,x=1,font=dict(size=10)),
            margin=dict(l=0,r=0,t=30,b=0))
        fig_mini.update_yaxes(title_text="Price",row=1,col=1)
        fig_mini.update_yaxes(title_text="Vol",row=2,col=1)
        st.plotly_chart(fig_mini,use_container_width=True)

    st.caption("This is a signal — NOT a guarantee. Always set a SL. Educational use only.")


# ═════════════════════════════════════════════════════════════════════════════
# LOAD SHARED DATA (trades + capital for records pages)
# ═════════════════════════════════════════════════════════════════════════════
_RECORDS_PAGES = {
    "📊 My Records Dashboard", "💰 My Capital", "📓 Log Trade",
    "🔄 Angel One Sync", "📋 All Trades", "📅 Monthly Report",
    "📈 Performance", "💸 Expenses", "⬇️ Export", "🤖 AI Trading Coach",
}
if page in _RECORDS_PAGES:
    with st.spinner("Loading your data…"):
        trades_df = load_trades()
        cap_data  = load_capital()
else:
    trades_df = load_trades()
    cap_data  = load_capital()

stats      = get_stats(trades_df)
cap_stats  = get_capital_stats(cap_data)
closed_df  = trades_df[trades_df["Result"].isin(["WIN","LOSS"])].copy() if not trades_df.empty else pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📈 SIGNAL DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if page == "📈 Signal Dashboard":
    if refresh:
        st.cache_data.clear()

    try:
        df_chart = load_chart_data(symbol, interval, period)
    except Exception as e:
        st.error("Failed to load data: {}".format(e))
        st.stop()

    summary  = get_summary(df_chart)
    decision = compute_decision(summary)
    advice   = compute_strike_advice(summary["close"], summary["atr"],
                                     total_capital, risk_per_trade, lot_size)
    vdict    = build_day_verdict(manual_event)

    render_verdict_badge(vdict)

    st.title("📈 {} — {} Signal Dashboard".format(symbol, interval))
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    pc = df_chart["Close"].iloc[-1] - df_chart["Close"].iloc[-2]
    pp = (pc / df_chart["Close"].iloc[-2]) * 100
    c1.metric("LTP",        "Rs {:.2f}".format(summary["close"]),  "{} {:.2f}%".format("▲" if pc>=0 else "▼", abs(pp)), delta_color="normal" if pc>=0 else "inverse")
    c2.metric("RSI (14)",   "{:.1f}".format(summary["rsi"]),        summary["rsi_zone"])
    c3.metric("ADX",        "{:.1f}".format(summary["adx"]),        "Strong" if summary["adx"]>25 else "Weak/Ranging")
    c4.metric("ATR",        "Rs {:.1f}".format(summary["atr"]),     "Volatility")
    c5.metric("Supertrend", summary["supertrend"])
    c6.metric("EMA Cross",  summary["ema_cross"])
    st.markdown("---")

    # ── MARKET TURNING ALERT ──────────────────────────────────────────────────
    if len(df_chart) >= 5:
        _neg_signals = []
        _pos_signals = []
        _r5  = df_chart.iloc[-5:]
        _prv = df_chart.iloc[-4:-1]
        _lb  = df_chart.iloc[-1]
        _hv  = list(_r5["MACD_hist"])
        if _hv[-1] < _hv[-2] < _hv[-3] and _hv[-1] > 0:
            _neg_signals.append("MACD histogram shrinking — bullish momentum fading")
        if _hv[-1] > _hv[-2] > _hv[-3] and _hv[-1] < 0:
            _pos_signals.append("MACD histogram expanding upward — bearish momentum fading")
        _rv = list(_r5["RSI"])
        if _rv[-1] < _rv[-2] and _rv[-2] > 60:
            _neg_signals.append("RSI rolling over from overbought ({:.1f}→{:.1f})".format(_rv[-2],_rv[-1]))
        if _rv[-1] > _rv[-2] and _rv[-2] < 40:
            _pos_signals.append("RSI bouncing from oversold ({:.1f}→{:.1f})".format(_rv[-2],_rv[-1]))
        if float(_prv["Close"].iloc[-1]) > float(_prv["EMA_9"].iloc[-1]) and float(_lb["Close"]) < float(_lb["EMA_9"]):
            _neg_signals.append("Price just crossed BELOW EMA-9 — short-term trend broken")
        if float(_prv["Close"].iloc[-1]) < float(_prv["EMA_9"].iloc[-1]) and float(_lb["Close"]) > float(_lb["EMA_9"]):
            _pos_signals.append("Price just crossed ABOVE EMA-9 — short-term trend recovering")
        if float(_prv["ST_trend"].iloc[-1]) == 1.0 and float(_lb["ST_trend"]) == -1.0:
            _neg_signals.append("⚡ Supertrend just FLIPPED to BEARISH — strong reversal!")
        if float(_prv["ST_trend"].iloc[-1]) == -1.0 and float(_lb["ST_trend"]) == 1.0:
            _pos_signals.append("⚡ Supertrend just FLIPPED to BULLISH — strong recovery!")
        if float(_prv["Close"].iloc[-1]) > float(_prv["VWAP"].iloc[-1]) and float(_lb["Close"]) < float(_lb["VWAP"]):
            _neg_signals.append("Price dropped BELOW VWAP — institutions turning sellers")
        if float(_prv["Close"].iloc[-1]) < float(_prv["VWAP"].iloc[-1]) and float(_lb["Close"]) > float(_lb["VWAP"]):
            _pos_signals.append("Price recovered ABOVE VWAP — institutions turning buyers")

        if len(_neg_signals) >= 2:
            st.markdown(
                "<div style='background:#450a0a;border:2px solid #dc2626;border-radius:10px;"
                "padding:14px 20px;margin-bottom:14px'>"
                "<div style='font-size:18px;font-weight:900;color:#fca5a5'>🚨 MARKET TURNING NEGATIVE RIGHT NOW</div>"
                "<div style='font-size:13px;color:#fecaca;margin-top:6px;line-height:1.7'>"
                + "<br>".join("• " + r for r in _neg_signals) +
                "</div><div style='font-size:12px;color:#f87171;margin-top:8px'>"
                "⚡ If you are holding a CALL — tighten stop-loss immediately or exit now.</div></div>",
                unsafe_allow_html=True,
            )
        elif len(_pos_signals) >= 2:
            st.markdown(
                "<div style='background:#052e16;border:2px solid #16a34a;border-radius:10px;"
                "padding:14px 20px;margin-bottom:14px'>"
                "<div style='font-size:18px;font-weight:900;color:#86efac'>💚 MARKET RECOVERING BULLISH RIGHT NOW</div>"
                "<div style='font-size:13px;color:#bbf7d0;margin-top:6px;line-height:1.7'>"
                + "<br>".join("• " + r for r in _pos_signals) +
                "</div><div style='font-size:12px;color:#4ade80;margin-top:8px'>"
                "⚡ If you are holding a PUT — tighten stop-loss immediately or exit now.</div></div>",
                unsafe_allow_html=True,
            )

    # ── BIG ACTION BANNER ─────────────────────────────────────────────────────
    _ps_quick  = compute_precision_signal(df_chart, summary, decision, vdict)
    _qdirn     = _ps_quick.get("direction", "WAIT")
    _qconf     = int(_ps_quick.get("signal_score", 0) / max(_ps_quick.get("max_score", 1), 1) * 100)
    _atr_q     = summary["atr"] if summary["atr"] > 0 else summary["close"] * 0.005

    if _qdirn == "CALL":
        _bg, _bd, _fc = "#052e16", "#16a34a", "#4ade80"
        _action_text  = "BUY CALL"
        _action_sub   = "Market moving UP — Buy a CALL option now"
        _sl_q  = round(summary["close"] - _atr_q, 2)
        _t1_q  = round(summary["close"] + _atr_q * 1.5, 2)
        _sl_txt = "SL below Rs {:.0f}".format(_sl_q)
        _t1_txt = "Target Rs {:.0f}".format(_t1_q)
    elif _qdirn == "PUT":
        _bg, _bd, _fc = "#2e0505", "#dc2626", "#f87171"
        _action_text  = "BUY PUT"
        _action_sub   = "Market moving DOWN — Buy a PUT option now"
        _sl_q  = round(summary["close"] + _atr_q, 2)
        _t1_q  = round(summary["close"] - _atr_q * 1.5, 2)
        _sl_txt = "SL above Rs {:.0f}".format(_sl_q)
        _t1_txt = "Target Rs {:.0f}".format(_t1_q)
    else:
        _bg, _bd, _fc = "#1c1c0a", "#ca8a04", "#fde047"
        _action_text  = "WAIT — DO NOT ENTER"
        _action_sub   = "No clear signal yet. Watch and wait for next candle."
        _sl_txt = "—"; _t1_txt = "—"

    st.markdown(
        "<div style='background:{bg};border:3px solid {bd};border-radius:14px;"
        "padding:22px 28px;margin-bottom:18px;text-align:center'>"
        "<div style='font-size:42px;font-weight:900;color:{fc};letter-spacing:2px'>{act}</div>"
        "<div style='font-size:16px;color:{fc};opacity:0.85;margin-top:4px'>{sub}</div>"
        "<div style='display:flex;justify-content:center;gap:32px;margin-top:16px;flex-wrap:wrap'>"
        "<div><span style='font-size:12px;color:#94a3b8'>🛑 STOP LOSS</span><br>"
        "<span style='font-size:20px;font-weight:800;color:#f87171'>{sl}</span></div>"
        "<div><span style='font-size:12px;color:#94a3b8'>✅ TARGET 1</span><br>"
        "<span style='font-size:20px;font-weight:800;color:#4ade80'>{t1}</span></div>"
        "<div><span style='font-size:12px;color:#94a3b8'>⚡ SIGNAL SCORE</span><br>"
        "<span style='font-size:20px;font-weight:800;color:{fc}'>{sc}%</span></div>"
        "<div><span style='font-size:12px;color:#94a3b8'>⏰ ENTER AT</span><br>"
        "<span style='font-size:20px;font-weight:800;color:{fc}'>{etime}</span></div>"
        "</div></div>".format(
            bg=_bg, bd=_bd, fc=_fc,
            act=_action_text, sub=_action_sub,
            sl=_sl_txt, t1=_t1_txt, sc=_qconf,
            etime=_ps_quick["entry_time"],
        ), unsafe_allow_html=True)
    st.markdown("---")

    # Trade Decision Panel
    st.subheader("🎯 Trade Decision Panel")
    for w in decision["warnings"]:
        st.warning("⚠️  " + w)
    dc1,dc2,dc3 = st.columns([1,2,2])
    with dc1:
        dir_icon = {"PUT":"🔴","CALL":"🟢","WAIT":"🟡"}[decision["direction"]]
        conf_pct = int(decision["confidence"] * 100)
        st.markdown("### {} **{}**".format(dir_icon, decision["direction"]))
        st.markdown("**Confidence: {}%**".format(conf_pct))
        st.progress(conf_pct)
        st.caption("Bull: {} | Bear: {}".format(decision["bull_score"], decision["bear_score"]))
    with dc2:
        if decision["reasons_bear"]:
            st.markdown("**🔴 Bearish Signals**")
            for r in decision["reasons_bear"]: st.markdown("- " + r)
    with dc3:
        if decision["reasons_bull"]:
            st.markdown("**🟢 Bullish Signals**")
            for r in decision["reasons_bull"]: st.markdown("- " + r)
    st.markdown("---")

    # ── Precision Entry Signal Panel ──────────────────────────────────────────
    st.subheader("⚡ Precision Entry Signal — BUY NOW with Exit Times")
    st.caption("Reads the current candle + live indicators. Enter at exact time, exit within 5 / 10 / 15 min.")
    precision_signal = _ps_quick  # already computed above
    render_precision_entry_panel(df_chart, precision_signal, interval)
    st.markdown("---")

    # ── Entry / Exit / Stop-Loss Price Panel ──────────────────────────────────
    st.subheader("💰 Entry Price · Exit Targets · Stop Loss")
    ltp   = summary["close"]
    dirn  = precision_signal.get("direction", decision["direction"])

    # summary["atr"] is already calculated on the selected timeframe candles
    # (yfinance downloads at the selected interval, so ATR reflects that candle size).
    # Typical values: 5m ~15–25 pts, 15m ~25–45 pts, 1h ~60–90 pts, 1d ~180–250 pts.
    # We cap it: for intraday (5m/15m/1h) never wider than 0.4% of LTP as SL.
    raw_atr = summary["atr"] if summary["atr"] > 0 else ltp * 0.003
    if interval in ("5m", "15m"):
        atr_use = min(raw_atr, round(ltp * 0.004, 1))   # cap at 0.4% = ~90 pts on 23000
        atr_use = max(atr_use, round(ltp * 0.001, 1))   # floor at 0.1% = ~23 pts
    elif interval == "1h":
        atr_use = min(raw_atr, round(ltp * 0.007, 1))   # cap at 0.7% = ~160 pts
        atr_use = max(atr_use, round(ltp * 0.002, 1))
    else:  # 1d — use raw ATR as-is
        atr_use = raw_atr

    # Realistic intraday SL/Target multipliers:
    # SL = 1x ATR (tight), T1 = 1.5x (easy first target), T2 = 2.5x (runner)
    if dirn == "CALL":
        entry_price  = round(ltp, 2)
        sl_price     = round(ltp - atr_use, 2)
        target1      = round(ltp + atr_use * 1.5, 2)
        target2      = round(ltp + atr_use * 2.5, 2)
        max_loss_pts = round(atr_use, 1)
        sl_label     = "Stop Loss (below entry)"
        t1_label     = "Target 1 (+1.5x ATR)"
        t2_label     = "Target 2 (+2.5x ATR)"
        sl_col       = "#ef4444"; t_col = "#10b981"
        dirn_badge   = "<span style='background:#052e16;color:#4ade80;border:2px solid #16a34a;border-radius:8px;padding:6px 20px;font-size:22px;font-weight:900;letter-spacing:1px'>🟢 THIS IS A CALL TRADE</span>"
        dirn_note    = "You are buying a <b>CALL option</b>. Profit when market goes UP."
        prem_action  = "BUY CALL OPTION PREMIUM AT"
    elif dirn == "PUT":
        entry_price  = round(ltp, 2)
        sl_price     = round(ltp + atr_use, 2)
        target1      = round(ltp - atr_use * 1.5, 2)
        target2      = round(ltp - atr_use * 2.5, 2)
        max_loss_pts = round(atr_use, 1)
        sl_label     = "Stop Loss (above entry)"
        t1_label     = "Target 1 (-1.5x ATR)"
        t2_label     = "Target 2 (-2.5x ATR)"
        sl_col       = "#ef4444"; t_col = "#10b981"
        dirn_badge   = "<span style='background:#2e0505;color:#f87171;border:2px solid #dc2626;border-radius:8px;padding:6px 20px;font-size:22px;font-weight:900;letter-spacing:1px'>🔴 THIS IS A PUT TRADE</span>"
        dirn_note    = "You are buying a <b>PUT option</b>. Profit when market goes DOWN."
        prem_action  = "BUY PUT OPTION PREMIUM AT"
    else:
        entry_price = ltp; sl_price = 0; target1 = 0; target2 = 0
        max_loss_pts = 0; sl_label = "Stop Loss"; t1_label = "Target 1"; t2_label = "Target 2"
        sl_col = "#94a3b8"; t_col = "#94a3b8"; atr_use = raw_atr
        dirn_badge = "<span style='background:#1c1c0a;color:#fde047;border:2px solid #ca8a04;border-radius:8px;padding:6px 20px;font-size:22px;font-weight:900'>🟡 WAIT — NO TRADE YET</span>"
        dirn_note  = "No clear direction. Do not enter. Watch for next candle."
        prem_action = "OPTION PREMIUM"

    # CALL / PUT badge
    st.markdown(
        "<div style='text-align:center;margin-bottom:14px'>{badge}<br>"
        "<span style='font-size:13px;color:#94a3b8;margin-top:6px;display:block'>{note}</span>"
        "</div>".format(badge=dirn_badge, note=dirn_note),
        unsafe_allow_html=True)

    # Option premium levels — use scaled ATR for realistic premium moves
    prem_entry = round(atr_use * 0.8, 1)
    prem_sl    = round(prem_entry * 0.70, 1)
    prem_t1    = round(prem_entry * 1.50, 1)
    prem_t2    = round(prem_entry * 2.20, 1)

    # Spot price levels card
    st.markdown(
        "<div style='background:#0f172a;border:2px solid #334155;border-radius:10px;"
        "padding:18px 22px;margin-bottom:10px'>"
        "<div style='font-size:13px;color:#94a3b8;margin-bottom:12px'>"
        "Timeframe: <b style='color:#fbbf24'>{ivl}</b> — "
        "ATR (this candle size) = <b style='color:#fbbf24'>{atr_s:.0f} pts</b>. "
        "SL = 1x ATR, Target 1 = 1.5x, Target 2 = 2.5x. "
        "Verify live premium in broker before entering."
        "</div>"
        "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px'>"

        "<div style='background:#1e293b;border-radius:8px;padding:12px 16px;border-left:4px solid #3b82f6'>"
        "<div style='font-size:11px;color:#64748b'>🎯 ENTRY PRICE (Spot)</div>"
        "<div style='font-size:24px;font-weight:900;color:#3b82f6'>Rs {entry:.2f}</div>"
        "<div style='font-size:11px;color:#64748b'>Current LTP — enter at market</div></div>"

        "<div style='background:#1e293b;border-radius:8px;padding:12px 16px;border-left:4px solid {sl_col}'>"
        "<div style='font-size:11px;color:#64748b'>🛑 {sl_label}</div>"
        "<div style='font-size:24px;font-weight:900;color:{sl_col}'>Rs {sl:.2f}</div>"
        "<div style='font-size:11px;color:#64748b'>Max loss: {loss:.0f} pts — EXIT immediately if hit</div></div>"

        "<div style='background:#1e293b;border-radius:8px;padding:12px 16px;border-left:4px solid {t_col}'>"
        "<div style='font-size:11px;color:#64748b'>✅ {t1_label}</div>"
        "<div style='font-size:24px;font-weight:900;color:{t_col}'>Rs {t1:.2f}</div>"
        "<div style='font-size:11px;color:#64748b'>Book 50–60% qty here</div></div>"

        "<div style='background:#1e293b;border-radius:8px;padding:12px 16px;border-left:4px solid {t_col}'>"
        "<div style='font-size:11px;color:#64748b'>🚀 {t2_label}</div>"
        "<div style='font-size:24px;font-weight:900;color:{t_col}'>Rs {t2:.2f}</div>"
        "<div style='font-size:11px;color:#64748b'>Trail SL for remaining qty</div></div>"
        "</div></div>".format(
            atr_s=atr_use, ivl=interval,
            entry=entry_price, sl=sl_price, loss=max_loss_pts,
            t1=target1, t2=target2,
            sl_col=sl_col, t_col=t_col,
            sl_label=sl_label, t1_label=t1_label, t2_label=t2_label,
        ), unsafe_allow_html=True)

    # Option premium levels row
    st.markdown(
        "<div style='background:#0f172a;border:1.5px solid #334155;border-radius:10px;"
        "padding:14px 22px;margin-bottom:4px'>"
        "<div style='font-size:13px;font-weight:700;color:#cbd5e1;margin-bottom:10px'>"
        "📋 Option Premium Levels (ATM estimate — verify in broker)</div>"
        "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px'>"

        "<div style='background:#1e293b;border-radius:6px;padding:10px 14px;text-align:center'>"
        "<div style='font-size:11px;color:#64748b'>{pact}</div>"
        "<div style='font-size:20px;font-weight:800;color:#3b82f6'>Rs {pe:.1f}</div>"
        "<div style='font-size:11px;color:#64748b'>Your entry premium cost</div></div>"

        "<div style='background:#2e1a1a;border-radius:6px;padding:10px 14px;text-align:center'>"
        "<div style='font-size:11px;color:#ef4444;font-weight:700'>🛑 EXIT IF PREMIUM DROPS TO</div>"
        "<div style='font-size:20px;font-weight:800;color:#ef4444'>Rs {psl:.1f}</div>"
        "<div style='font-size:11px;color:#94a3b8'>SL on premium (–30%) — get out NOW</div></div>"

        "<div style='background:#1a2e1a;border-radius:6px;padding:10px 14px;text-align:center'>"
        "<div style='font-size:11px;color:#10b981;font-weight:700'>✅ TARGET 1 PREMIUM</div>"
        "<div style='font-size:20px;font-weight:800;color:#10b981'>Rs {pt1:.1f}</div>"
        "<div style='font-size:11px;color:#94a3b8'>+50% gain — sell 50% here</div></div>"

        "<div style='background:#1a2e1a;border-radius:6px;padding:10px 14px;text-align:center'>"
        "<div style='font-size:11px;color:#10b981;font-weight:700'>🚀 TARGET 2 PREMIUM</div>"
        "<div style='font-size:20px;font-weight:800;color:#10b981'>Rs {pt2:.1f}</div>"
        "<div style='font-size:11px;color:#94a3b8'>+120% gain — exit remaining</div></div>"
        "</div></div>".format(
            pact=prem_action, pe=prem_entry, psl=prem_sl, pt1=prem_t1, pt2=prem_t2),
        unsafe_allow_html=True)

    if dirn == "WAIT":
        st.info("⏳ Signal is WAIT — no entry levels shown. Wait for a clear BUY CALL or BUY PUT signal.")

    st.markdown("---")

    # Strike Advisor
    st.subheader("📌 Options Strike Advisor")
    oa1,oa2,oa3,oa4,oa5,oa6 = st.columns(6)
    oa1.metric("ATM Strike",     "{} PE/CE".format(advice["atm"]))
    oa2.metric("OTM Strike",     "{} PE/CE".format(advice["otm_1"]), "1 step OTM")
    oa3.metric("Max Lots",       str(advice["max_lots"]), "{}% risk = Rs {:.0f}".format(risk_per_trade, advice["max_loss"]))
    oa4.metric("SL on Premium",  "Rs {:.1f}".format(advice["sl_premium"]), "30% of entry — exit here")
    oa5.metric("Target 1",       "{:.0f}".format(advice["target1"]), "1.5x ATR")
    oa6.metric("Target 2",       "{:.0f}".format(advice["target2"]), "3x ATR")
    st.info("Entry Rule: Buy ATM {} strike. Set SL at Rs {:.1f} on premium. Max {} lot(s) with Rs {:,.0f} capital at {}% risk.".format(
        advice["atm"], advice["sl_premium"], advice["max_lots"], total_capital, risk_per_trade))
    st.markdown("---")

    # Pre-trade checklist
    with st.expander("✅ Pre-Trade 9-Gate Checklist — Complete Before Every Entry", expanded=False):
        st.markdown("""
| # | Gate | Status |
|---|------|--------|
| 1 | RSI between 35–65 (not extreme) | {} |
| 2 | MACD crossover is fresh | {} |
| 3 | ADX > 25 (strong trend) | {} |
| 4 | Price on correct side of VWAP | {} |
| 5 | Supertrend confirms direction | {} |
| 6 | SL order placed in broker app BEFORE buying | ☐ Manual |
| 7 | Trading ATM strike (not OTM) | ☐ Manual |
| 8 | Expiry is 3+ days away | ☐ Manual |
| 9 | No major news/event in next 1 hour | ☐ Manual |
        """.format(
            "✅" if 35 <= summary["rsi"] <= 65 else "❌ EXTREME",
            "✅" if abs(summary["macd"] - summary["macd_signal"]) < summary["atr"] * 0.1 else "⚠️ Check",
            "✅" if summary["adx"] > 25 else "❌ Weak Trend",
            "✅" if ((summary["close"] > summary["vwap"] and decision["direction"] == "CALL") or
                     (summary["close"] < summary["vwap"] and decision["direction"] == "PUT") or
                     decision["direction"] == "WAIT") else "❌ Against VWAP",
            "✅" if ((summary["supertrend"] == "BULLISH" and decision["direction"] == "CALL") or
                     (summary["supertrend"] == "BEARISH" and decision["direction"] == "PUT") or
                     decision["direction"] == "WAIT") else "❌ Against Supertrend",
        ))
    st.markdown("---")

    # Main chart
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.50, 0.17, 0.17, 0.16],
                        subplot_titles=("Price + Indicators","RSI","MACD","Volume"))
    fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart["Open"], high=df_chart["High"],
                                  low=df_chart["Low"], close=df_chart["Close"], name="Price",
                                  increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), row=1,col=1)
    for ema, color in [("EMA_9","#f39c12"),("EMA_21","#3498db"),("EMA_50","#9b59b6"),("EMA_200","#e74c3c")]:
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart[ema], name=ema,
                                 line=dict(color=color,width=1), opacity=0.8), row=1,col=1)
    fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["VWAP"], name="VWAP",
                             line=dict(color="#ffffff",width=1.2,dash="dot"),opacity=0.6), row=1,col=1)
    if show_bb:
        fig.add_trace(go.Scatter(x=df_chart.index,y=df_chart["BB_upper"],name="BB Upper",
                                 line=dict(color="rgba(150,150,150,0.5)",width=1,dash="dot")),row=1,col=1)
        fig.add_trace(go.Scatter(x=df_chart.index,y=df_chart["BB_lower"],name="BB Lower",
                                 line=dict(color="rgba(150,150,150,0.5)",width=1,dash="dot"),
                                 fill="tonexty",fillcolor="rgba(150,150,150,0.05)"),row=1,col=1)
    if show_supertrend:
        bull_st = df_chart[df_chart["ST_trend"]==1]
        bear_st = df_chart[df_chart["ST_trend"]==-1]
        fig.add_trace(go.Scatter(x=bull_st.index,y=bull_st["ST_value"],mode="markers",
                                 marker=dict(color="#26a69a",size=4,symbol="triangle-up"),name="ST Bull"),row=1,col=1)
        fig.add_trace(go.Scatter(x=bear_st.index,y=bear_st["ST_value"],mode="markers",
                                 marker=dict(color="#ef5350",size=4,symbol="triangle-down"),name="ST Bear"),row=1,col=1)
    fig.add_trace(go.Scatter(x=df_chart.index,y=df_chart["RSI"],name="RSI",
                             line=dict(color="#3498db",width=1.5)),row=2,col=1)
    fig.add_hrect(y0=65,y1=100,fillcolor="rgba(239,83,80,0.08)",line_width=0,row=2,col=1)
    fig.add_hrect(y0=0,y1=35, fillcolor="rgba(38,166,154,0.08)",line_width=0,row=2,col=1)
    fig.add_hline(y=70,line_dash="dash",line_color="red",opacity=0.4,row=2,col=1)
    fig.add_hline(y=30,line_dash="dash",line_color="green",opacity=0.4,row=2,col=1)
    colors_hist = ["#26a69a" if v >= 0 else "#ef5350" for v in df_chart["MACD_hist"]]
    fig.add_trace(go.Bar(x=df_chart.index,y=df_chart["MACD_hist"],name="Histogram",
                         marker_color=colors_hist,opacity=0.7),row=3,col=1)
    fig.add_trace(go.Scatter(x=df_chart.index,y=df_chart["MACD"],name="MACD",
                             line=dict(color="#3498db",width=1.2)),row=3,col=1)
    fig.add_trace(go.Scatter(x=df_chart.index,y=df_chart["MACD_signal"],name="Signal",
                             line=dict(color="#f39c12",width=1.2)),row=3,col=1)
    vol_colors = ["#26a69a" if df_chart["Close"].iloc[i]>=df_chart["Open"].iloc[i] else "#ef5350"
                  for i in range(len(df_chart))]
    fig.add_trace(go.Bar(x=df_chart.index,y=df_chart["Volume"],name="Volume",
                         marker_color=vol_colors,opacity=0.7),row=4,col=1)
    fig.update_layout(height=780,template="plotly_dark",xaxis_rangeslider_visible=False,
                      showlegend=True,legend=dict(orientation="h",yanchor="bottom",y=1.02,x=1),
                      margin=dict(l=0,r=0,t=30,b=0))
    fig.update_yaxes(title_text="Price (Rs)",row=1,col=1)
    fig.update_yaxes(title_text="RSI",row=2,col=1,range=[0,100])
    fig.update_yaxes(title_text="MACD",row=3,col=1)
    fig.update_yaxes(title_text="Volume",row=4,col=1)
    st.plotly_chart(fig, use_container_width=True)
    st.markdown("---")

    # Watchlist
    if watchlist:
        st.subheader("📋 Watchlist Overview")
        rows = []
        for sym in watchlist:
            try:
                wdf = load_chart_data(sym, "1d", "1y")
                s   = get_summary(wdf)
                dec = compute_decision(s)
                chg = wdf["Close"].iloc[-1] - wdf["Close"].iloc[-2] if len(wdf) >= 2 else 0.0
                pct = (chg / wdf["Close"].iloc[-2]) * 100 if len(wdf) >= 2 and wdf["Close"].iloc[-2] != 0 else 0.0
                rsi_tag = ("🔴 {:.1f} OB".format(s["rsi"]) if s["rsi"]>65 else
                            ("🟢 {:.1f} OS".format(s["rsi"]) if s["rsi"]<35 else
                             ("🟢 {:.1f}".format(s["rsi"]) if s["rsi"]>55 else
                              ("🔴 {:.1f}".format(s["rsi"]) if s["rsi"]<45 else "🟡 {:.1f}".format(s["rsi"])))))
                rows.append({
                    "Symbol":    sym,
                    "LTP (Rs)":  "Rs {:.2f}".format(s["close"]),
                    "Change %":  "{} {:.2f}%".format("▲" if chg>=0 else "▼", abs(pct)),
                    "RSI":       rsi_tag,
                    "ADX":       "{:.1f} {}".format(s["adx"],"Strong" if s["adx"]>25 else "Weak"),
                    "Supertrend":s["supertrend"],
                    "MACD":      "Bullish" if s["macd"]>s["macd_signal"] else "Bearish",
                    "Signal":    {"PUT":"🔴 PUT","CALL":"🟢 CALL","WAIT":"🟡 WAIT"}.get(dec.get("direction", "WAIT"), "🟡 WAIT"),
                    "Confidence":"{:.0f}%".format(dec.get("confidence", 0.5)*100),
                })
            except Exception as _e:
                rows.append({"Symbol":sym,"LTP (Rs)":"Error","Change %":"-","RSI":"-",
                             "ADX":"-","Supertrend":"-","MACD":"-","Signal":"-","Confidence":"-"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.markdown("---")

    st.caption("Data via yfinance. Educational use only. NOT financial advice.")


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 🎯 GOAL & COMPOUNDING ENGINE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🎯 Goal & Compounding Engine":
    st.title("🎯 Goal Setting & Compounding Engine")
    st.caption("Set your capital target · Choose start & end dates · See your required daily run-rate · Risk guardrails")
    st.markdown("---")

    goal = load_goal_cloud(cap_data)
    current_cap = float(cap_data.get("current_capital", goal.get("initial_capital", 50000.0)))

    # ── GOAL SETUP FORM (shown at TOP so it's always the first thing you see) ──
    st.markdown(
        "<div style='background:#1e3a5f;border:2px solid #3b82f6;border-radius:10px;"
        "padding:14px 20px;margin-bottom:18px'>"
        "<span style='font-size:18px;font-weight:800;color:#93c5fd'>⚙️ Step 1 — Enter Your Goal Below</span><br>"
        "<span style='font-size:13px;color:#cbd5e1'>Fill in all fields and click the blue 🚀 button to save.</span>"
        "</div>",
        unsafe_allow_html=True
    )

    with st.form("cloud_goal_form"):
        c_name = st.text_input("Goal Title / Description", value=goal.get("goal_name", "Roadmap to ₹10 Lakh"),
                               placeholder="e.g. Roadmap to ₹10 Lakh")

        f1, f2 = st.columns(2)
        c_init = f1.number_input(
            "Starting Capital (₹)", min_value=1000.0,
            value=float(goal.get("initial_capital", 50000.0)), step=5000.0,
            help="The initial amount you are trading with (e.g. 50000 for ₹50k)"
        )
        c_target = f2.number_input(
            "Target Goal Capital (₹)", min_value=5000.0,
            value=float(goal.get("target_capital", 1000000.0)), step=50000.0,
            help="Final target (e.g. 1000000 = ₹10 Lakh)"
        )

        # Date pickers
        try:
            def_start = datetime.strptime(goal.get("start_date", datetime.today().strftime("%Y-%m-%d")), "%Y-%m-%d").date()
        except Exception:
            def_start = datetime.today().date()
        try:
            def_end = datetime.strptime(goal.get("target_date", (datetime.today() + timedelta(days=180)).strftime("%Y-%m-%d")), "%Y-%m-%d").date()
        except Exception:
            def_end = (datetime.today() + timedelta(days=180)).date()

        d_col1, d_col2, d_col3 = st.columns(3)
        c_start_date  = d_col1.date_input("📅 Start Date", value=def_start,
                                           help="Day your challenge starts (today or a past date)")
        c_target_date = d_col2.date_input("🏁 Target Completion Date", value=def_end,
                                           help="Day you want to reach the target capital")
        calc_days   = max(1, (c_target_date - c_start_date).days)
        calc_months = round(calc_days / 30.4, 1)
        d_col3.metric("📆 Calculated Duration", f"{calc_months} Months", f"{calc_days} calendar days")

        st.markdown("**🛡️ Risk Guardrails**")
        r1, r2, r3 = st.columns(3)
        c_risk = r1.slider("Max Risk Per Trade (%)", min_value=0.5, max_value=5.0,
                           value=float(goal.get("risk_per_trade_pct", 1.5)), step=0.1,
                           help="Max loss per single trade (1.5% recommended)")
        c_rr   = r2.slider("Target Risk:Reward (1:X)", min_value=1.0, max_value=5.0,
                           value=float(goal.get("risk_reward_ratio", 2.0)), step=0.5,
                           help="1:2 = risk ₹1 to make ₹2")
        c_loss = r3.slider("Max Daily Drawdown Stop (%)", min_value=1.0, max_value=10.0,
                           value=float(goal.get("max_daily_loss_pct", 3.0)), step=0.5,
                           help="Hard daily stop if your loss reaches this %")

        submitted = st.form_submit_button("🚀 Save & Activate This Target Roadmap",
                                          type="primary", use_container_width=True)
        if submitted:
            new_goal = {
                "goal_name":             c_name,
                "initial_capital":       c_init,
                "target_capital":        c_target,
                "start_date":            c_start_date.strftime("%Y-%m-%d"),
                "target_date":           c_target_date.strftime("%Y-%m-%d"),
                "target_months":         calc_months,
                "trading_days_per_month":20,
                "risk_per_trade_pct":    c_risk,
                "risk_reward_ratio":     c_rr,
                "max_daily_loss_pct":    c_loss,
                "active":    True,
                "completed": False,
                "history":   goal.get("history", [])
            }
            save_goal_cloud(new_goal, save_capital, cap_data)
            st.success(f"🎉 Goal '{c_name}' activated! Target: ₹{c_target:,.0f} by {c_target_date.strftime('%d %b %Y')} ({calc_months} months).")
            st.rerun()

    st.markdown("---")

    # Re-evaluate after potential form submit (uses session_state which is already updated)
    goal = load_goal_cloud(cap_data)
    eval_res = evaluate_goal_progress(goal, current_cap)

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("🎯 Target Capital",    f"₹{eval_res['target_capital']:,.0f}",  f"Initial: ₹{eval_res['initial_capital']:,.0f}")
    g2.metric("💰 Current Capital",   f"₹{eval_res['current_capital']:,.0f}", f"{eval_res['progress_pct']}% Achieved")
    g3.metric("⏳ Trading Days Left", f"{eval_res['trading_days_remaining']} Days", f"{eval_res['trading_days_elapsed']} elapsed")
    g4.metric("📈 Required Daily Run",f"+{eval_res['daily_rate_pct']}% / day", f"~{eval_res['monthly_rate_pct']}% / mo")

    # ── Status Banner ─────────────────────────────────────────────────────────
    st.markdown(
        f"""
        <div style='background:#1e293b;border:2px solid {eval_res['pace_color']};border-radius:10px;padding:16px 20px;margin-bottom:20px'>
            <div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px'>
                <span style='font-size:20px;font-weight:800;color:{eval_res['pace_color']}'>{eval_res['pace']}</span>
                <span style='font-size:14px;font-weight:700;color:#94a3b8'>Current Stage: <b style='color:#f8fafc'>{eval_res['current_level']}</b></span>
            </div>
            <p style='margin-top:8px;font-size:14px;color:#cbd5e1;line-height:1.6'>{eval_res['pace_advice']}</p>
            <div style='display:flex;gap:20px;font-size:13px;color:#94a3b8;margin-top:10px;flex-wrap:wrap'>
                <span>🎯 Expected Capital Today: <b style='color:#f8fafc'>₹{eval_res['expected_capital_today']:,.0f}</b></span>
                <span>⚖️ Ahead/Behind: <b style='color:{"#10b981" if eval_res["diff_amount"]>=0 else "#ef4444"}'>₹{eval_res["diff_amount"]:+,.0f}</b></span>
                <span>🛡️ Feasibility: <b style='color:{eval_res["feasibility_color"]}'>{eval_res["feasibility"]}</b></span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # ── Today's Limits ────────────────────────────────────────────────────────
    st.subheader("🛡️ Today's Goal-Aligned Trade Limits")
    d1, d2, d3 = st.columns(3)
    d1.info(f"**🎯 Today's Compounding Target**\n### +₹{eval_res['today_target_pnl']:,.0f}\n*Once hit — lock profits & stop trading!*")
    d2.warning(f"**🛡️ Max Risk Per Trade ({goal.get('risk_per_trade_pct', 1.5)}%)**\n### ₹{eval_res['today_max_risk']:,.0f}\n*Hard stop-loss limit per single order*")
    d3.error(f"**🛑 Daily Max Drawdown Stop ({goal.get('max_daily_loss_pct', 3.0)}%)**\n### -₹{eval_res['today_max_daily_loss']:,.0f}\n*If day hits this loss, stop trading immediately!*")

    st.markdown("---")

    # ── Trajectory Chart + Milestones ─────────────────────────────────────────
    col_l, col_r = st.columns([2, 1])
    with col_l:
        st.subheader("📈 Compounding Trajectory Curve")
        sch_df = eval_res["schedule_df"]
        if not sch_df.empty:
            fig_g = go.Figure()
            fig_g.add_trace(go.Scatter(
                x=sch_df["Day"], y=sch_df["Target_Capital"],
                mode="lines", name="Compounding Roadmap",
                line=dict(color="#3b82f6", width=3)
            ))
            fig_g.add_trace(go.Scatter(
                x=[eval_res["trading_days_elapsed"]], y=[eval_res["current_capital"]],
                mode="markers+text", name="Your Capital Now",
                marker=dict(color="#10b981" if eval_res["diff_amount"]>=0 else "#ef4444", size=14, symbol="star"),
                text=[f"₹{eval_res['current_capital']:,.0f}"],
                textposition="top center"
            ))
            fig_g.update_layout(
                template="plotly_dark", height=340,
                margin=dict(l=20, r=20, t=30, b=20),
                xaxis_title="Trading Days", yaxis_title="Capital (₹)"
            )
            st.plotly_chart(fig_g, use_container_width=True)

    with col_r:
        st.subheader("🏆 Milestone Levels")
        for m in eval_res["milestones"]:
            is_done = current_cap >= m["target_amount"]
            icon = "✅" if is_done else "🔒"
            st.markdown(
                f"""<div style='background:{"#064e3b" if is_done else "#1e293b"};border:1px solid {"#10b981" if is_done else "#475569"};border-radius:6px;padding:8px 12px;margin-bottom:8px;font-size:13px'>
                    <b>{icon} {m['level']} ({m['percentage']}% mark)</b><br>
                    <span>Target: <b>₹{m['target_amount']:,.0f}</b> &nbsp;|&nbsp; Day: {m['target_day']}</span>
                </div>""",
                unsafe_allow_html=True
            )


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 🕹️ ANGEL ONE LIVE COCKPIT
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🕹️ Angel One Live Cockpit":
    st.title("🕹️ Angel One Live Cockpit")
    st.caption("Live open positions · Margin radar · Smart AI reversal warnings · Dynamic stop-loss")
    st.markdown("---")

    if not is_angel_configured():
        st.warning("⚠️ Angel One credentials not configured in secrets.")
        st.info("Add `angel_api_key`, `angel_client_id`, `angel_mpin`, and `angel_totp_key` in Streamlit Cloud Secrets.")
    else:
        margins, m_err = get_live_margins()
        pos_df, tot_unreal, tot_real, p_err = get_live_positions()

        # Top radar metrics
        st.subheader("💼 Live Portfolio & Account Radar")
        k1, k2, k3, k4 = st.columns(4)
        avail_cash = margins.get("available_cash", 0.0) if margins else 0.0
        net_marg = margins.get("net_margin", 0.0) if margins else 0.0
        k1.metric("Available Margin", f"₹{avail_cash:,.2f}")
        k2.metric("Total Net Margin", f"₹{net_marg:,.2f}")
        k3.metric("Live Unrealized MTM", f"₹{tot_unreal:+,.2f}", delta_color="normal" if tot_unreal>=0 else "inverse")
        k4.metric("Realized P&L Today", f"₹{tot_real:+,.2f}", delta_color="normal" if tot_real>=0 else "inverse")

        st.markdown("---")

        # Open positions radar
        st.subheader("📡 Active Open Positions & AI Reversal Guard")
        if not pos_df.empty:
            open_pos = pos_df[pos_df["Status"] == "OPEN"]
            if not open_pos.empty:
                for _, r in open_pos.iterrows():
                    st.markdown(
                        f"""
                        <div style='background:#1e293b;border:1.5px solid #3b82f6;border-radius:8px;padding:12px 16px;margin-bottom:10px'>
                            <div style='display:flex;justify-content:space-between;align-items:center'>
                                <span style='font-size:16px;font-weight:700'>{r['Symbol']} ({r['Type']})</span>
                                <span style='font-size:16px;font-weight:800;color:{"#10b981" if r["Unrealized P&L"]>=0 else "#ef4444"}'>MTM: ₹{r['Unrealized P&L']:+,.2f}</span>
                            </div>
                            <div style='display:flex;gap:18px;font-size:12px;color:#94a3b8;margin-top:6px'>
                                <span>Qty: <b>{r['Net Qty']}</b></span>
                                <span>Buy Avg: <b>₹{r['Buy Avg']}</b></span>
                                <span>LTP: <b>₹{r['LTP']}</b></span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
            else:
                st.success("✅ No open positions currently active. Capital is safely parked.")

            with st.expander("📋 View All Today's Angel One Positions (Open & Closed)", expanded=False):
                st.dataframe(pos_df, use_container_width=True, hide_index=True)
        else:
            st.info("No positions recorded on Angel One today.")


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📰 MARKET NEWS & VERDICT
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📰 Market News & Verdict":
    vdict = build_day_verdict(manual_event)
    now_ist = vdict["now_ist"]; gap_data = vdict["gap_data"]; tw = vdict["tw"]; checks = vdict["checks"]
    vbg,vbd,vc,vi,v,vd = vdict["verdict_bg"],vdict["verdict_border"],vdict["verdict_color"],vdict["verdict_icon"],vdict["verdict"],vdict["verdict_detail"]
    p,w,f = vdict["pass_count"],vdict["warn_count"],vdict["fail_count"]

    st.title("📰 Market News & Trade Verdict")
    st.caption("Live headlines · Event calendar · Should I trade today?")
    st.markdown("<div style='background:{bg};border:2.5px solid {bd};border-radius:12px;"
                "padding:22px 28px;text-align:center;margin-bottom:20px'>"
                "<div style='font-size:44px;margin-bottom:6px'>{icon}</div>"
                "<div style='font-size:24px;font-weight:900;color:{col};margin-bottom:8px'>{v}</div>"
                "<div style='font-size:14px;color:#e5e7eb;line-height:1.8;max-width:560px;margin:0 auto'>{vd}</div>"
                "<div style='margin-top:14px;font-size:13px;color:#9ca3af'>"
                "✅ {p} passed | ⚠️ {w} cautions | ❌ {f} failed | {ts}"
                "</div></div>".format(bg=vbg,bd=vbd,col=vc,icon=vi,v=v,vd=vd,p=p,w=w,f=f,
                                      ts=now_ist.strftime("%d %b %Y  %I:%M %p IST")),
                unsafe_allow_html=True)

    dc1,dc2,dc3,dc4 = st.columns(4)
    dc1.metric("📅 Date", now_ist.strftime("%d %b %Y"))
    dc2.metric("🗓️ Day",  vdict["day_name"])
    dc3.metric("🕐 IST",  now_ist.strftime("%I:%M %p"))
    dc4.metric("🏦 NSE",  "CLOSED" if vdict["market_status"]!="OPEN_DAY" else "OPEN",
               vdict["holiday_name"] or vdict["day_name"])
    st.markdown("---")

    left, right = st.columns(2)
    with left:
        st.subheader("🔍 Today's Checks")
        for icon, label, text, passed in checks:
            bg = "#14532d" if passed is True else ("#450a0a" if passed is False else "#422006")
            bd = "#16a34a" if passed is True else ("#dc2626" if passed is False else "#d97706")
            lc = "#86efac" if passed is True else ("#fca5a5" if passed is False else "#fcd34d")
            st.markdown("<div style='background:{bg};border:1px solid {bd};border-radius:7px;"
                        "padding:9px 13px;margin-bottom:8px;font-size:13px'>"
                        "<b style='color:{lc}'>{icon} {label}</b><br><span style='color:#e5e7eb'>{text}</span></div>".format(
                            bg=bg,bd=bd,lc=lc,icon=icon,label=label,text=text), unsafe_allow_html=True)
    with right:
        st.subheader("⏱️ Time Window")
        tw_colors = {
            "best":    ("#14532d", "#16a34a", "#86efac"),
            "ok":      ("#1e3a5f", "#2563eb", "#93c5fd"),
            "caution": ("#422006", "#d97706", "#fcd34d"),
            "avoid":   ("#1f2937", "#374151", "#9ca3af"),
            "closed":  ("#1f2937", "#374151", "#9ca3af"),
        }
        html = "<div style='display:flex;gap:4px;flex-wrap:wrap;margin-bottom:12px'>"
        for trange, tlabel, tstatus in [("9:15–9:44","Opening","avoid"),("9:45–10:29","Early","caution"),
                                          ("10:30–12:59","Prime ✅","best"),("1:00–2:29","Mid ✅","ok"),
                                          ("2:30–3:14","Late ⚠️","caution"),("3:15–3:30","Close","avoid")]:
            is_cur = any(x in tw["label"] for x in [trange.split("–")[0], tlabel.replace(" ✅","").replace(" ⚠️","")])
            tile_bg, tile_bd, tile_tc = tw_colors.get(tstatus, ("#1f2937","#374151","#9ca3af"))
            bdr = "2px solid #60a5fa" if is_cur else "1px solid {}".format(tile_bd)
            html += "<div style='background:{bg};border:{bdr};border-radius:6px;padding:6px 9px;font-size:11px;font-weight:{fw};text-align:center;color:{tc}'>{r}<br>{l}</div>".format(
                bg=tile_bg,bdr=bdr,fw="700" if is_cur else "500",tc=tile_tc,r=trange,l=tlabel)
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)
        st.caption("Current: **{}** — {}".format(tw["label"], tw["note"]))
        st.markdown("---")
        st.markdown("**📊 Nifty Gap vs previous close**")
        if gap_data["ok"]:
            gp = gap_data["gap_pts"]; gpct = gap_data["gap_pct"]
            col_g = "#059669" if gap_data["direction"]=="UP" else "#dc2626"
            st.markdown("<div style='font-size:26px;font-weight:800;color:{c}'>"
                        "{a} {pts:+.0f} pts ({pct:+.2f}%)</div>"
                        "<div style='font-size:12px;color:#57606a;margin-top:4px'>"
                        "Prev: Rs {prev:,.2f} → Last: Rs {last:,.2f}</div>".format(
                            c=col_g, a="▲" if gap_data["direction"]=="UP" else "▼",
                            pts=gp, pct=gpct, prev=gap_data["prev"], last=gap_data["last"]),
                        unsafe_allow_html=True)
            if abs(gp) > 150:
                st.warning("⚠️ Large gap ({:.0f} pts). Wait for gap-fill.".format(abs(gp)))
            else:
                st.success("Gap within normal range.")
        else:
            st.info("Gap data unavailable. Check manually.")
    st.markdown("---")

    # Upcoming events
    st.subheader("📅 Upcoming High-Impact Events & Holidays")
    today_d = now_ist.date(); upcoming = []
    for ds, hn in NSE_HOLIDAYS_2026.items():
        d = date.fromisoformat(ds)
        if d >= today_d:
            upcoming.append({"Date":d.strftime("%d %b %Y (%A)"),"Event":hn,"Type":"🏖️ Holiday",
                              "Days Away":(d-today_d).days,"Impact":"🔴 CLOSED"})
    for ds,(en,imp) in SCHEDULED_EVENTS.items():
        d = date.fromisoformat(ds)
        if d >= today_d:
            upcoming.append({"Date":d.strftime("%d %b %Y (%A)"),"Event":en,"Type":"📌 Event",
                              "Days Away":(d-today_d).days,"Impact":"🚫 EXTREME" if imp=="EXTREME" else "⚠️ HIGH"})
    if upcoming:
        upcoming.sort(key=lambda x: x["Days Away"])
        st.dataframe(pd.DataFrame(upcoming[:12])[["Date","Event","Type","Impact","Days Away"]],
                     use_container_width=True, hide_index=True)
    for e in [x for x in upcoming if x["Days Away"] <= 2]:
        st.warning("⚠️ **{}** is {} day(s) away — {}".format(e["Event"],e["Days Away"],e["Impact"]))
    st.markdown("---")

    # Live news
    st.subheader("📡 Live Market Headlines")
    if st.button("🔄 Refresh News"):
        st.cache_data.clear()
    with st.spinner("Fetching headlines..."):
        articles = fetch_market_news()
    if not articles:
        st.info("Could not fetch news. Check [MoneyControl](https://www.moneycontrol.com/news/business/markets/) or [NSE](https://www.nseindia.com/) manually.")
    else:
        imp_filter = st.radio("Filter", ["All","🔴 HIGH only","🟡 MEDIUM+"], horizontal=True)
        filtered = articles if imp_filter == "All" else (
            [a for a in articles if a["impact"]=="🔴 HIGH"] if imp_filter=="🔴 HIGH only" else
            [a for a in articles if a["impact"] in ("🔴 HIGH","🟡 MEDIUM")])
        for art in filtered[:20]:
            imp = art["impact"]
            bg  = "#fef2f2" if imp=="🔴 HIGH" else ("#fffbeb" if imp=="🟡 MEDIUM" else "#f9fafb")
            bd  = "#fca5a5" if imp=="🔴 HIGH" else ("#fcd34d" if imp=="🟡 MEDIUM" else "#e5e7eb")
            kws = " · ".join(["<code style='font-size:10px;background:#f3f4f6;padding:1px 4px;border-radius:3px'>{}</code>".format(k)
                              for k in art["keywords"].split(", ") if k and k!="—"])
            st.markdown("<div style='background:{bg};border:1px solid {bd};border-radius:8px;padding:10px 14px;margin-bottom:8px'>"
                        "<div style='display:flex;justify-content:space-between;align-items:flex-start;gap:8px'>"
                        "<a href='{link}' target='_blank' style='font-size:13px;font-weight:600;color:#1d4ed8;text-decoration:none;flex:1'>{title}</a>"
                        "<span style='font-size:11px;white-space:nowrap;font-weight:700'>{imp}</span></div>"
                        "<div style='font-size:11px;color:#6b7280;margin-top:5px'>{src} | {pub}{kw}</div></div>".format(
                            bg=bg,bd=bd,link=art["link"],title=art["title"],imp=imp,
                            src=art["source"],pub=art["published"],kw=(" | "+kws) if kws else ""),
                        unsafe_allow_html=True)
        hc = sum(1 for a in articles if a["impact"]=="🔴 HIGH")
        if hc >= 3:
            st.error("🚨 {} HIGH-impact headlines — treat like event day. Trade with extreme caution or sit out.".format(hc))
        elif hc >= 1:
            st.warning("⚠️ {} HIGH-impact headline(s). Read carefully before trading.".format(hc))
        else:
            st.success("✅ No high-impact headlines. Market news appears routine today.")
    st.caption("News via Google News RSS. Educational only. Not financial advice.")


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📊 MY RECORDS DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📊 My Records Dashboard":
    st.title("📊 My Trading Dashboard")
    st.caption("Personal performance overview — updated live from Supabase Cloud.")
    st.markdown("---")
    remaining_pct = (cap_stats["current"]/cap_stats["initial"]*100) if cap_stats["initial"] else 0
    cap_d, cap_dc = pnl_delta(cap_stats["pnl"])
    cc1,cc2,cc3,cc4,cc5 = st.columns(5)
    cc1.metric("💰 Initial Capital", "Rs {:,.0f}".format(cap_stats["initial"]))
    cc2.metric("💵 Current Balance", "Rs {:,.0f}".format(cap_stats["current"]), cap_d, delta_color=cap_dc)
    cc3.metric("📉 Total P&L",       "Rs {:,.0f}".format(abs(cap_stats["pnl"])),
               "{:.1f}%".format(cap_stats["pnl_pct"]), delta_color="normal" if cap_stats["pnl"]>=0 else "inverse")
    cc4.metric("📅 Days Trading",    "{} days".format(cap_stats["days"]))
    cc5.metric("🏦 Capital Left",    "{:.1f}%".format(remaining_pct),
               delta_color="normal" if remaining_pct>=80 else "inverse")
    prog_c = "🟢" if remaining_pct>=80 else ("🟡" if remaining_pct>=60 else "🔴")
    st.progress(min(int(remaining_pct),100),
                text="{} Rs {:,.0f} remaining of Rs {:,.0f} ({:.1f}%)".format(
                    prog_c, cap_stats["current"], cap_stats["initial"], remaining_pct))
    st.markdown("---")
    k1,k2,k3,k4 = st.columns(4)
    k1.metric("Total Trades", stats["total_trades"])
    k2.metric("Win Rate",     "{:.1f}%".format(stats["win_rate"]))
    d,dc = pnl_delta(stats["total_pnl"])
    k3.metric("Net P&L", "Rs {:,.0f}".format(stats["total_pnl"]), d, delta_color=dc)
    k4.metric("Reward:Risk", "{:.2f}".format(stats["reward_risk"]),
              "Good ✅" if stats["reward_risk"]>=1.5 else "Needs improvement")
    k5,k6,k7,k8 = st.columns(4)
    k5.metric("Wins",        stats["wins"])
    k6.metric("Losses",      stats["losses"], delta_color="inverse")
    k7.metric("Best Trade",  "Rs {:,.0f}".format(stats["best_trade"]))
    k8.metric("Worst Trade", "Rs {:,.0f}".format(stats["worst_trade"]))
    st.markdown("---")
    if not closed_df.empty:
        pnl_s = pd.to_numeric(closed_df["Net P&L"], errors="coerce").fillna(0)
        cl, cr = st.columns([3,2])
        with cl:
            equity = pnl_s.cumsum().reset_index(drop=True)
            trade_nums = list(range(1, len(equity)+1))
            colors = ["#26a69a" if v>=0 else "#ef5350" for v in pnl_s]
            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(x=trade_nums,y=equity,mode="lines+markers",
                                        line=dict(color="#3498db",width=2.5),marker=dict(color=colors,size=9),
                                        hovertemplate="Trade %{x}<br>Cumulative P&L: Rs %{y:,.0f}<extra></extra>"))
            fig_eq.add_hline(y=0,line_dash="dash",line_color="rgba(255,255,255,0.3)")
            fig_eq.update_layout(template="plotly_dark",height=320,title="📈 Equity Curve",
                                  xaxis_title="Trade #",yaxis_title="Cumulative P&L (Rs)",margin=dict(l=0,r=0,t=40,b=0))
            st.plotly_chart(fig_eq, use_container_width=True)
        with cr:
            pie = go.Figure(go.Pie(labels=["Wins","Losses"],values=[stats["wins"],stats["losses"]],
                                   marker=dict(colors=["#26a69a","#ef5350"]),hole=0.5,textinfo="label+percent"))
            pie.update_layout(template="plotly_dark",height=320,title="🏆 Win/Loss Ratio",
                               margin=dict(l=0,r=0,t=40,b=0),showlegend=False)
            st.plotly_chart(pie, use_container_width=True)
        if "Date" in closed_df.columns:
            closed_df["Month"] = pd.to_datetime(closed_df["Date"],errors="coerce").dt.strftime("%b %Y")
            monthly = closed_df.groupby("Month")["Net P&L"].apply(
                lambda x: pd.to_numeric(x,errors="coerce").sum()).reset_index()
            bar_colors = ["#26a69a" if v>=0 else "#ef5350" for v in monthly["Net P&L"]]
            bar_fig = go.Figure(go.Bar(x=monthly["Month"],y=monthly["Net P&L"],marker_color=bar_colors,
                                       text=["Rs {:,.0f}".format(v) for v in monthly["Net P&L"]],textposition="outside"))
            bar_fig.update_layout(template="plotly_dark",height=300,title="📅 Monthly Net P&L",
                                   margin=dict(l=0,r=0,t=40,b=0))
            st.plotly_chart(bar_fig, use_container_width=True)
        st.markdown("#### 🕐 Last 5 Trades")
        rc = ["Trade #","Date","Symbol","Option Type","Strike","Entry Price","Exit Price","Net P&L","Result"]
        st.dataframe(trades_df[rc].tail(5).sort_index(ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("No closed trades yet. Go to **📓 Log Trade** to record your first trade!")


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 💰 MY CAPITAL
# ══════════════════════════════════════════════════════════════════════════════
elif page == "💰 My Capital":
    st.title("💰 My Capital Tracker")
    st.markdown("---")
    remaining_pct = (cap_stats["current"]/cap_stats["initial"]*100) if cap_stats["initial"] else 0
    cap_d, cap_dc = pnl_delta(cap_stats["pnl"])
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("💰 Initial",  "Rs {:,.0f}".format(cap_stats["initial"]))
    c2.metric("💵 Balance",  "Rs {:,.0f}".format(cap_stats["current"]), cap_d, delta_color=cap_dc)
    c3.metric("📊 P&L",     "Rs {:,.0f}".format(cap_stats["pnl"]),
              "{:.2f}%".format(cap_stats["pnl_pct"]), delta_color="normal" if cap_stats["pnl"]>=0 else "inverse")
    c4.metric("📅 Days",    "{} days".format(cap_stats["days"]))
    c5.metric("🏦 Left",    "{:.1f}%".format(remaining_pct),
              delta_color="normal" if remaining_pct>=80 else "inverse")
    prog_c = "🟢" if remaining_pct>=80 else ("🟡" if remaining_pct>=60 else "🔴")
    st.progress(min(int(remaining_pct),100),
                text="{} Rs {:,.0f} of Rs {:,.0f} ({:.1f}%)".format(
                    prog_c, cap_stats["current"], cap_stats["initial"], remaining_pct))
    st.markdown("---")

    # ── 3 action tabs ─────────────────────────────────────────────────────────
    _cur = float(cap_data.get("current_capital", 40000))
    _ini = float(cap_data.get("initial_capital", 40000))
    tab_dep, tab_wdraw, tab_reset = st.tabs([
        "➕ Deposit Capital",
        "➖ Withdraw Capital",
        "🔧 Set / Fix Initial Capital",
    ])

    with tab_dep:
        st.caption("Added more money to your trading account? Enter **how much you deposited** — "
                   "it will be added on top of your current balance of **Rs {:,.0f}**.".format(_cur))
        with st.form("cap_deposit_form_nca"):
            d1, d2 = st.columns(2)
            dep_amt  = d1.number_input("Amount Deposited (Rs)", value=0.0, min_value=0.0, step=1000.0, format="%.0f")
            dep_note = d2.text_input("Note", placeholder="e.g. Added funds from bank")
            st.info("New balance after deposit: **Rs {:,.0f}**".format(_cur + dep_amt))
            if st.form_submit_button("➕ Add Deposit", type="primary"):
                if dep_amt <= 0:
                    st.error("Enter an amount greater than 0.")
                else:
                    new_b = round(_cur + dep_amt, 2)
                    cap_data["current_capital"] = new_b
                    cap_data.setdefault("history", []).append({
                        "date":    datetime.now().strftime("%Y-%m-%d"),
                        "balance": new_b,
                        "note":    dep_note or "[DEPOSIT] Rs {:,.0f}".format(dep_amt),
                    })
                    save_capital(cap_data)
                    st.success("✅ Rs {:,.0f} deposited — New balance: Rs {:,.0f}".format(dep_amt, new_b))
                    st.rerun()

    with tab_wdraw:
        st.caption("Withdrew money from your trading account? Enter **how much you took out** — "
                   "it will be subtracted from your current balance of **Rs {:,.0f}**.".format(_cur))
        with st.form("cap_withdraw_form_nca"):
            w1, w2 = st.columns(2)
            wdraw_amt  = w1.number_input("Amount Withdrawn (Rs)", value=0.0, min_value=0.0, step=1000.0, format="%.0f")
            wdraw_note = w2.text_input("Note", placeholder="e.g. Withdrew for expenses")
            st.info("New balance after withdrawal: **Rs {:,.0f}**".format(_cur - wdraw_amt))
            if st.form_submit_button("➖ Record Withdrawal", type="primary"):
                if wdraw_amt <= 0:
                    st.error("Enter an amount greater than 0.")
                else:
                    new_b = round(_cur - wdraw_amt, 2)
                    cap_data["current_capital"] = new_b
                    cap_data.setdefault("history", []).append({
                        "date":    datetime.now().strftime("%Y-%m-%d"),
                        "balance": new_b,
                        "note":    wdraw_note or "[WITHDRAWAL] Rs {:,.0f}".format(wdraw_amt),
                    })
                    save_capital(cap_data)
                    st.success("✅ Rs {:,.0f} withdrawn — New balance: Rs {:,.0f}".format(wdraw_amt, new_b))
                    st.rerun()

    with tab_reset:
        st.caption("⚠️ Use this ONLY to **fix a wrong Initial Capital**. "
                   "It resets both initial and current balance to the value you enter.")
        with st.form("cap_reset_form_nca"):
            rf1, rf2 = st.columns(2)
            init_val  = rf1.number_input("Correct Initial Capital (Rs)", value=_ini, step=1000.0, format="%.0f")
            start_dt  = rf2.text_input("Trading Start Date", value=cap_data.get("start_date", "2025-01-01"))
            if st.form_submit_button("⚠️ Reset & Set Initial Capital", type="primary"):
                cap_data["initial_capital"] = round(init_val, 2)
                cap_data["current_capital"] = round(init_val, 2)
                cap_data["start_date"]      = start_dt
                cap_data["history"]         = [{
                    "date":    start_dt,
                    "balance": round(init_val, 2),
                    "note":    "Initial starting capital",
                }]
                save_capital(cap_data)
                st.success("✅ Capital reset to Rs {:,.0f}".format(init_val))
                st.rerun()

    # ── Capital history chart + colour-coded table ─────────────────────────────
    history = cap_stats.get("history", [])
    if history:
        hdf = pd.DataFrame(history)
        hdf["date"]    = pd.to_datetime(hdf["date"], errors="coerce")
        hdf["balance"] = pd.to_numeric(hdf["balance"], errors="coerce")
        hdf = hdf.sort_values("date").reset_index(drop=True)
        fig_cap = go.Figure()
        fig_cap.add_trace(go.Scatter(x=hdf["date"], y=hdf["balance"], mode="lines+markers",
                                     line=dict(color="#3498db", width=2.5), fill="tozeroy",
                                     fillcolor="rgba(52,152,219,0.08)", marker=dict(size=8, color="#3498db"),
                                     hovertemplate="%{x|%d %b %Y}<br>Balance: Rs %{y:,.0f}<extra></extra>"))
        fig_cap.add_hline(y=cap_stats["initial"], line_dash="dash", line_color="rgba(255,255,255,0.4)",
                          annotation_text="Initial: Rs {:,.0f}".format(cap_stats["initial"]),
                          annotation_position="bottom right")
        fig_cap.update_layout(template="plotly_dark", height=350, title="💵 Capital Over Time",
                              margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_cap, use_container_width=True)

        st.subheader("📋 Transaction History")
        disp = hdf[["date", "balance", "note"]].rename(
            columns={"date": "Date", "balance": "Balance (Rs)", "note": "Note"}
        ).sort_values("Date", ascending=False).copy()
        disp["Date"] = disp["Date"].dt.strftime("%d %b %Y")

        def _nca_type(note):
            n = str(note).upper()
            if "DEPOSIT"    in n: return "➕ Deposit"
            if "WITHDRAWAL" in n: return "➖ Withdrawal"
            if "INITIAL"    in n: return "🏁 Initial"
            if "TRADE"      in n: return "📈 Trade"
            return "📝 Manual"

        def _nca_color(note):
            n = str(note).upper()
            if "DEPOSIT"    in n: return "color: #26a69a"
            if "WITHDRAWAL" in n: return "color: #ef5350"
            if "INITIAL"    in n: return "color: #f0a500"
            return ""

        disp.insert(0, "Type", disp["Note"].apply(_nca_type))
        st.dataframe(
            disp.style.apply(lambda row: [_nca_color(row["Note"])] * len(row), axis=1),
            use_container_width=True, hide_index=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📓 LOG TRADE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📓 Log Trade":
    st.title("📓 Log a Trade")
    st.caption("Every trade saved permanently to Supabase Cloud ☁️")
    st.markdown("---")
    st.subheader("Trade Details")
    c1,c2,c3,c4 = st.columns(4)
    f_sym    = c1.text_input("Symbol",    value="NIFTY50", key="lt_sym")
    f_type   = c2.selectbox("PUT / CALL", ["PUT","CALL"], key="lt_type")
    f_strike = c3.number_input("Strike",  value=22500, step=50, key="lt_strike")
    f_expiry = c4.text_input("Expiry",    placeholder="e.g. 06 Jun 2025", key="lt_expiry")
    c5,c6,c7,c8,c9 = st.columns([2, 2, 1, 1, 1])
    f_entry   = c5.number_input("Entry Price (Rs)",        value=0.0, step=0.05, format="%.2f", min_value=0.0, key="lt_entry")
    f_exit    = c6.number_input("Exit Price (Rs) — 0=OPEN",value=0.0, step=0.05, format="%.2f", min_value=0.0, key="lt_exit")
    f_lots    = c7.number_input("Lots",    value=1, step=1, min_value=1, key="lt_lots")
    f_lotsize = c8.number_input("Lot Size",value=75, step=1, min_value=1, key="lt_lotsize")
    calc_qty  = int(f_lots * f_lotsize)
    c9.metric("Total Qty", f"{calc_qty:,}")
    st.subheader("Market Conditions at Entry")
    m1,m2,m3,m4 = st.columns(4)
    f_rsi   = m1.number_input("RSI at Entry", value=50.0, step=0.1, format="%.1f", min_value=0.0, max_value=100.0, key="lt_rsi")
    f_adx   = m2.number_input("ADX at Entry", value=25.0, step=0.1, format="%.1f", min_value=0.0, max_value=100.0, key="lt_adx")
    f_st    = m3.selectbox("Supertrend", ["BEARISH","BULLISH"], key="lt_st")
    f_dsaid = m4.selectbox("Dashboard Said", ["WAIT","PUT","CALL"], key="lt_dsaid")
    st.subheader("Notes & Learning")
    n1,n2 = st.columns(2)
    f_hold    = n1.text_input("Hold Time",        placeholder="e.g. 45 min", key="lt_hold")
    f_lessons = n2.text_input("Lessons Learned",  placeholder="e.g. Never enter RSI < 35", key="lt_lessons")
    st.markdown("**📝 Trade Notes / Observations (Saved to Records):**")
    f_notes   = st.text_area("Additional Notes",  placeholder="What did you observe? Why did you enter?", height=90, key="lt_notes", label_visibility="collapsed")
    ch1,_,ch3 = st.columns(3)
    f_brok  = ch1.number_input("Brokerage (Rs)",    value=DEFAULT_BROKERAGE, step=1.0, min_value=0.0, key="lt_brok")
    f_other = ch3.number_input("Other Charges (Rs)",value=DEFAULT_OTHER,     step=1.0, min_value=0.0, key="lt_other")

    st.markdown("---")
    cap_preview = round(f_entry * f_lots * f_lotsize, 2)
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Symbol / Strike", f"{f_sym} {int(f_strike)} {f_type}")
    p2.metric("Total Quantity", f"{calc_qty:,} ({f_lots} lots)")
    p3.metric("Entry Price", f"Rs {f_entry:,.2f}")
    p4.metric("Capital Required", f"Rs {cap_preview:,.2f}")

    if f_entry <= 0:
        st.warning("⚠️ Please fill in an **Entry Price > 0** before clicking save.")

    submitted = st.button("💾 Save Trade to Cloud", use_container_width=True, type="primary")
    if submitted:
        if f_entry <= 0:
            st.error("Entry Price must be > 0.")
        else:
            now     = datetime.now()
            capital = round(f_entry * f_lots * f_lotsize, 2)
            gross   = round((f_exit - f_entry) * f_lots * f_lotsize, 2) if f_exit > 0 else 0.0
            stt     = round(f_exit * f_lots * f_lotsize * DEFAULT_STT_PCT / 100, 2) if f_exit > 0 else 0.0
            other_c = DEFAULT_OTHER if f_exit > 0 else 0.0
            net     = round(gross - f_brok - stt - other_c, 2) if f_exit > 0 else 0.0
            result  = "OPEN" if f_exit <= 0 else ("WIN" if net >= 0 else "LOSS")
            row = {
                "Trade #":         _next_trade_num(trades_df),
                "Date":            now.strftime("%Y-%m-%d"),
                "Time":            now.strftime("%H:%M"),
                "Symbol":          f_sym,
                "Option Type":     f_type,
                "Strike":          int(f_strike),
                "Expiry":          f_expiry,
                "Entry Price":     f_entry,
                "Exit Price":      f_exit if f_exit > 0 else "",
                "Lots":            int(f_lots),
                "Lot Size":        int(f_lotsize),
                "Capital Used":    capital,
                "Gross P&L":       gross  if f_exit > 0 else "",
                "Brokerage":       f_brok if f_exit > 0 else "",
                "STT":             stt    if f_exit > 0 else "",
                "Other Charges":   other_c if f_exit > 0 else "",
                "Net P&L":         net    if f_exit > 0 else "",
                "Result":          result,
                "Hold Time":       f_hold,
                "Entry RSI":       round(f_rsi,1) if f_rsi else "",
                "Entry ADX":       round(f_adx,1) if f_adx else "",
                "Supertrend":      f_st,
                "Dashboard Said":  f_dsaid,
                "Lessons Learned": f_lessons,
                "Notes":           f_notes,
            }
            new_df = pd.concat([trades_df, pd.DataFrame([row])], ignore_index=True)
            save_trades(new_df)
            emoji = "✅ WIN" if result=="WIN" else ("❌ LOSS" if result=="LOSS" else "📂 OPEN")
            st.success("Trade #{} saved! {} | Net P&L: {}".format(
                row["Trade #"], emoji, "Rs {:,.0f}".format(net) if f_exit > 0 else "Open position"))
            st.rerun()

    # ── Recent Trades Log + Delete Trade ──────────────────────────────────────────
    st.markdown("---")
    st.subheader("📋 Recent Trades Log")
    if trades_df.empty:
        st.info("No trades logged yet.")
    else:
        show_cols = [c for c in ["Trade #", "Date", "Symbol", "Option Type", "Strike",
                                 "Entry Price", "Exit Price", "Lots", "Net P&L", "Result"] if c in trades_df.columns]
        recent = trades_df[show_cols].sort_values("Trade #", ascending=False).head(20)
        st.dataframe(recent, use_container_width=True, hide_index=True)

    st.markdown("#### 🗑️ Delete a Trade")
    st.caption("⚠️ Deleting a trade removes it from your log.")

    if trades_df.empty:
        st.caption("No trades available to delete.")
    else:
        del_col1, del_col2 = st.columns([2, 1])
        trade_labels = [
            "#{} — {} {} {} | {}".format(
                int(r["Trade #"]), r["Date"], r["Symbol"],
                r["Option Type"], r["Result"])
            for _, r in trades_df.sort_values("Trade #", ascending=False).iterrows()
        ]
        sel_label = del_col1.selectbox("Select trade to delete", trade_labels, key="nc_del_sel")
        sel_num   = int(sel_label.split(" — ")[0].replace("#", "").strip())

        if del_col2.button("🗑️ Delete Selected Trade", type="secondary", use_container_width=True, key="nc_del_btn"):
            mask = pd.to_numeric(trades_df["Trade #"], errors="coerce") != sel_num
            updated_df = trades_df[mask].reset_index(drop=True)
            save_trades(updated_df)
            st.success("✅ Trade #{} deleted successfully!".format(sel_num))
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 🔄 ANGEL ONE SYNC
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔄 Angel One Sync":
    st.title("🔄 Angel One Auto-Sync")
    st.caption("Automatically fetch your executed trades from Angel One — no manual entry needed!")
    st.markdown("---")

    # ── Raw API debug panel ───────────────────────────────────────────────────
    with st.expander("🔍 Debug: Raw Angel One API response", expanded=True):
        if st.button("🔎 Check what Angel One API returns (raw)"):
            try:
                from angel_sync import _login_angel
                with st.spinner("Connecting to Angel One..."):
                    obj = _login_angel()
                    st.success("✅ Login successful!")

                    tb = obj.tradeBook()
                    st.markdown("**tradeBook() response:**")
                    st.json(tb)

                    ob = obj.orderBook()
                    st.markdown("**orderBook() response:**")
                    st.json(ob)
            except Exception as ex:
                st.error("Error: {}".format(ex))
                import traceback
                st.code(traceback.format_exc())
    st.markdown("---")

    render_angel_sync_panel(load_fn=load_trades, save_fn=save_trades, columns=TRADE_COLUMNS,
                            cap_load_fn=load_capital, cap_save_fn=save_capital)


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📋 ALL TRADES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📋 All Trades":
    st.title("📋 All Trades")
    if trades_df.empty:
        st.info("No trades yet. Log your first trade from **📓 Log Trade**.")
    else:
        fc1,fc2,fc3 = st.columns(3)
        syms     = ["All"] + sorted(trades_df["Symbol"].dropna().unique().tolist())
        filt_sym = fc1.selectbox("Symbol",      syms)
        filt_typ = fc2.selectbox("Option Type", ["All","PUT","CALL"])
        filt_res = fc3.selectbox("Result",      ["All","WIN","LOSS","OPEN"])
        view = trades_df.copy()
        if filt_sym != "All": view = view[view["Symbol"]      == filt_sym]
        if filt_typ != "All": view = view[view["Option Type"] == filt_typ]
        if filt_res != "All": view = view[view["Result"]      == filt_res]
        st.caption("{} trades shown".format(len(view)))
        st.dataframe(view.sort_values("Trade #", ascending=False), use_container_width=True, hide_index=True)
        if not view.empty:
            pnl_tot = pd.to_numeric(view["Net P&L"], errors="coerce").sum()
            d, dc   = pnl_delta(pnl_tot)
            t1, t2  = st.columns(2)
            t1.metric("Net P&L (filtered)", "Rs {:,.0f}".format(pnl_tot), d, delta_color=dc)
            t2.metric("Capital Used",       "Rs {:,.0f}".format(pd.to_numeric(view["Capital Used"],errors="coerce").sum()))


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📅 MONTHLY REPORT
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📅 Monthly Report":
    st.title("📅 Monthly P&L Report")
    st.markdown("---")
    if closed_df.empty:
        st.info("No closed trades yet.")
    else:
        closed_df["_month"] = pd.to_datetime(closed_df["Date"], errors="coerce").dt.to_period("M")
        months    = sorted(closed_df["_month"].dropna().unique(), reverse=True)
        sel_month = st.selectbox("Select Month", [str(m) for m in months] + ["All Time"])
        view = closed_df.copy() if sel_month == "All Time" else \
               closed_df[closed_df["_month"].astype(str) == sel_month].copy()
        pnl_s   = pd.to_numeric(view["Net P&L"],      errors="coerce").fillna(0)
        gross_w = pd.to_numeric(view[view["Result"]=="WIN"]["Gross P&L"],  errors="coerce").sum()
        gross_l = pd.to_numeric(view[view["Result"]=="LOSS"]["Gross P&L"], errors="coerce").sum()
        brok    = pd.to_numeric(view["Brokerage"],     errors="coerce").sum()
        stt_v   = pd.to_numeric(view["STT"],           errors="coerce").sum()
        other   = pd.to_numeric(view["Other Charges"], errors="coerce").sum()
        net     = pnl_s.sum()
        cap     = pd.to_numeric(view["Capital Used"],  errors="coerce").sum()
        w_c = (view["Result"]=="WIN").sum(); l_c = (view["Result"]=="LOSS").sum(); tot = len(view)
        st.subheader("📄 P&L Statement — {}".format(sel_month))
        cls = "pnl-pos" if net >= 0 else "pnl-neg"
        st.markdown("""
<style>
.pnl-box{{background:#1e2130;border-radius:10px;padding:20px 30px;font-family:monospace;font-size:15px;line-height:2.0}}
.pnl-pos{{color:#26a69a;font-weight:bold}}.pnl-neg{{color:#ef5350;font-weight:bold}}
.pnl-head{{color:#3498db;font-weight:bold;font-size:16px}}.pnl-div{{border-top:1px solid #444;margin:8px 0}}
</style>
<div class="pnl-box">
<span class="pnl-head">TRADING P&L STATEMENT — {title}</span><br>
<div class="pnl-div"></div>
Trades: <b>{tot}</b> &nbsp; Wins: <span class="pnl-pos">{wc}</span> &nbsp; Losses: <span class="pnl-neg">{lc}</span> &nbsp; Win Rate: <b>{wr:.1f}%</b>
<div class="pnl-div"></div>
Gross Revenue : <span class="pnl-pos">+Rs {gw:,.2f}</span><br>
Gross Loss    : <span class="pnl-neg"> Rs {gl:,.2f}</span><br>
<div class="pnl-div"></div>
Brokerage     : <span class="pnl-neg"> Rs {brok:,.2f}</span><br>
STT           : <span class="pnl-neg"> Rs {stt:,.2f}</span><br>
Other Charges : <span class="pnl-neg"> Rs {other:,.2f}</span><br>
<div class="pnl-div"></div>
<b>NET PROFIT / LOSS : <span class="{cls}">Rs {net:,.2f}</span></b><br>
<div class="pnl-div"></div>
Capital Used : Rs {cap:,.2f}
</div>""".format(title=sel_month,tot=tot,wc=w_c,lc=l_c,wr=(w_c/tot*100) if tot else 0,
                 gw=gross_w,gl=abs(gross_l),brok=brok,stt=stt_v,other=other,
                 net=net,cap=cap,cls=cls), unsafe_allow_html=True)
        st.markdown("---")
        st.dataframe(view[["Trade #","Date","Symbol","Option Type","Strike",
                            "Entry Price","Exit Price","Lots","Capital Used","Net P&L","Result"]
                    ].sort_values("Trade #",ascending=False), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📈 PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📈 Performance":
    st.title("📈 Performance Analysis")
    st.markdown("---")
    if closed_df.empty:
        st.info("No closed trades yet.")
    else:
        s = stats
        r1c1,r1c2,r1c3,r1c4 = st.columns(4)
        r1c1.metric("Total Trades", s["total_trades"])
        r1c2.metric("Win Rate",     "{:.1f}%".format(s["win_rate"]))
        r1c3.metric("Avg Win",      "Rs {:,.0f}".format(s["avg_win"]))
        r1c4.metric("Avg Loss",     "Rs {:,.0f}".format(abs(s["avg_loss"])))
        r2c1,r2c2,r2c3,r2c4 = st.columns(4)
        r2c1.metric("Reward:Risk",  "{:.2f}x".format(s["reward_risk"]))
        r2c2.metric("Max Drawdown", "Rs {:,.0f}".format(abs(s["max_drawdown"])))
        r2c3.metric("Best Trade",   "Rs {:,.0f}".format(s["best_trade"]))
        r2c4.metric("Worst Trade",  "Rs {:,.0f}".format(s["worst_trade"]))
        st.markdown("---")

        # Signal accuracy: when Dashboard Said X, what was the result?
        if "Dashboard Said" in closed_df.columns:
            st.subheader("🎯 Signal Accuracy — Was the Dashboard Right?")
            sig_acc = closed_df.groupby("Dashboard Said").apply(lambda g: pd.Series({
                "Total Trades": len(g),
                "Wins":         (g["Result"]=="WIN").sum(),
                "Losses":       (g["Result"]=="LOSS").sum(),
                "Win Rate %":   round((g["Result"]=="WIN").sum() / len(g) * 100, 1),
                "Net P&L Rs":   pd.to_numeric(g["Net P&L"],errors="coerce").sum().round(2),
            })).reset_index()
            st.dataframe(sig_acc, use_container_width=True, hide_index=True)
            st.caption("Use this to see how accurate your signals are for YOUR specific trades over time.")
            st.markdown("---")

        tab1, tab2 = st.tabs(["By Symbol", "PUT vs CALL"])
        with tab1:
            sg = closed_df.groupby("Symbol").apply(lambda g: pd.Series({
                "Trades":    len(g),
                "Wins":      (g["Result"]=="WIN").sum(),
                "Net P&L":   pd.to_numeric(g["Net P&L"],errors="coerce").sum().round(2),
                "Win Rate %":round((g["Result"]=="WIN").sum()/len(g)*100,1),
            })).reset_index()
            st.dataframe(sg, use_container_width=True, hide_index=True)
        with tab2:
            tg = closed_df.groupby("Option Type").apply(lambda g: pd.Series({
                "Trades":    len(g),
                "Wins":      (g["Result"]=="WIN").sum(),
                "Net P&L":   pd.to_numeric(g["Net P&L"],errors="coerce").sum().round(2),
                "Win Rate %":round((g["Result"]=="WIN").sum()/len(g)*100,1),
            })).reset_index()
            st.dataframe(tg, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 💸 EXPENSES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "💸 Expenses":
    st.title("💸 Charges & Expenses")
    st.markdown("---")
    if closed_df.empty:
        st.info("No closed trades yet.")
    else:
        e1,e2,e3,e4 = st.columns(4)
        e1.metric("Total Brokerage",    "Rs {:,.2f}".format(stats["total_brokerage"]))
        e2.metric("Total STT",          "Rs {:,.2f}".format(pd.to_numeric(closed_df["STT"],errors="coerce").sum()))
        e3.metric("Other Charges",      "Rs {:,.2f}".format(pd.to_numeric(closed_df["Other Charges"],errors="coerce").sum()))
        e4.metric("Total Charges Paid", "Rs {:,.2f}".format(stats["total_charges"]))
        gross_pnl = pd.to_numeric(closed_df["Gross P&L"],errors="coerce").sum()
        fig_exp = go.Figure(go.Bar(
            x=["Gross P&L","Total Charges","Net P&L"],
            y=[gross_pnl, -stats["total_charges"], stats["total_pnl"]],
            marker_color=["#3498db","#e74c3c","#26a69a" if stats["total_pnl"]>=0 else "#ef5350"],
            text=["Rs {:,.0f}".format(v) for v in [gross_pnl,stats["total_charges"],stats["total_pnl"]]],
            textposition="outside",
        ))
        fig_exp.update_layout(template="plotly_dark",height=350,
                              title="Gross P&L vs Charges vs Net P&L",
                              yaxis_title="Amount (Rs)",margin=dict(l=0,r=0,t=40,b=0))
        st.plotly_chart(fig_exp, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: ⬇️ EXPORT
# ══════════════════════════════════════════════════════════════════════════════
elif page == "⬇️ Export":
    st.title("⬇️ Export Reports")
    st.markdown("---")
    if trades_df.empty:
        st.info("No trades yet to export.")
    else:
        csv_bytes = trades_df.to_csv(index=False).encode("utf-8")
        today = datetime.now().strftime("%Y%m%d")
        st.download_button(
            label="⬇️ Download All Trades (CSV)",
            data=csv_bytes,
            file_name="My_Trades_{}.csv".format(today),
            mime="text/csv",
            use_container_width=True,
        )
        st.info("Your data is safely stored in Supabase Cloud ☁️ — no laptop needed! Download is just a backup copy.")


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 🤖 AI TRADING COACH
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🤖 AI Trading Coach":
    st.title("🤖 AI Trading Coach")
    st.caption("Powered by Google Gemini (free) · Your trade mistake analyser · Entry/exit timing coach")
    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1: TRADE MISTAKE ANALYSIS (reads your actual journal)
    # ══════════════════════════════════════════════════════════════════════════
    st.subheader("🔍 Your Trade Mistake Report — Based on YOUR actual trades")
    st.caption("The AI reads every trade you have logged and tells you exactly what timing and psychology mistakes you made.")

    _coach_df = load_trades()
    _closed_coach = _coach_df[_coach_df["Result"].isin(["WIN","LOSS"])].copy() if not _coach_df.empty else pd.DataFrame()

    if _closed_coach.empty:
        st.info(
            "📭 No closed trades found yet. Go to **📓 Log Trade** and record your trades. "
            "Once you have trades, come back here — the AI will analyse your specific mistakes."
        )
        _show_coach_analysis = False
    else:
        _show_coach_analysis = True
        _c_pnl    = pd.to_numeric(_closed_coach["Net P&L"],   errors="coerce").fillna(0)
        _c_rsi    = pd.to_numeric(_closed_coach["Entry RSI"],  errors="coerce")
        _c_adx    = pd.to_numeric(_closed_coach["Entry ADX"],  errors="coerce")
        _c_total  = len(_closed_coach)
        _c_wins   = (_closed_coach["Result"] == "WIN").sum()
        _c_wr     = round(_c_wins / _c_total * 100, 1) if _c_total else 0

        # Metrics row
        _cm1,_cm2,_cm3,_cm4 = st.columns(4)
        _cm1.metric("Trades Analysed", str(_c_total))
        _cm2.metric("Your Win Rate",   "{:.1f}%".format(_c_wr),
                    "Above avg ✅" if _c_wr>=50 else "Needs work ⚠️")
        _cm3.metric("Net P&L (All)",   "Rs {:,.0f}".format(_c_pnl.sum()))
        _cm4.metric("Avg P&L/Trade",   "Rs {:,.0f}".format(_c_pnl.mean()))

        st.markdown("---")

        # ── Collect mistakes ──────────────────────────────────────────────────
        _timing_err = []; _psych_err = []

        # T1: RSI extreme entry
        _rsi_ext = _closed_coach[_c_rsi.gt(65) | _c_rsi.lt(35)]
        if not _rsi_ext.empty:
            _ep = pd.to_numeric(_rsi_ext["Net P&L"], errors="coerce").sum()
            _el = (_rsi_ext["Result"]=="LOSS").sum()
            _timing_err.append({"mistake":"Entered in EXTREME RSI zone (>65 or <35)","count":len(_rsi_ext),
                "impact":"Rs {:,.0f} total P&L".format(_ep),"sev":"HIGH" if _el>len(_rsi_ext)//2 else "MEDIUM",
                "fix":"RSI above 65 = overbought. RSI below 35 = oversold. Both mean reversal risk is high. "
                      "Wait for RSI 40–60 before entering. You did this {}×.".format(len(_rsi_ext))})

        # T2: Against Supertrend
        if "Supertrend" in _closed_coach.columns and "Option Type" in _closed_coach.columns:
            _st_conf = _closed_coach[
                ((_closed_coach["Supertrend"].str.upper()=="BEARISH") & (_closed_coach["Option Type"].str.upper()=="CALL")) |
                ((_closed_coach["Supertrend"].str.upper()=="BULLISH") & (_closed_coach["Option Type"].str.upper()=="PUT"))
            ]
            if not _st_conf.empty:
                _sp = pd.to_numeric(_st_conf["Net P&L"], errors="coerce").sum()
                _timing_err.append({"mistake":"Entered AGAINST Supertrend direction","count":len(_st_conf),
                    "impact":"Rs {:,.0f} total P&L".format(_sp),"sev":"HIGH",
                    "fix":"If Supertrend is BEARISH → only trade PUT. If BULLISH → only trade CALL. "
                          "Going against Supertrend is the most common way to lose in F&O. You did this {}×.".format(len(_st_conf))})

        # T3: Dashboard said WAIT
        if "Dashboard Said" in _closed_coach.columns:
            _iw = _closed_coach[_closed_coach["Dashboard Said"].str.upper()=="WAIT"]
            if not _iw.empty:
                _iwp = pd.to_numeric(_iw["Net P&L"], errors="coerce").sum()
                _iwr = round((_iw["Result"]=="WIN").sum()/len(_iw)*100, 1)
                _timing_err.append({"mistake":"Entered when Dashboard said WAIT","count":len(_iw),
                    "impact":"Rs {:,.0f} total P&L (win rate: {}%)".format(_iwp,_iwr),"sev":"HIGH",
                    "fix":"Dashboard said WAIT {} time(s) but you entered anyway. "
                          "Your win rate on those trades was {}%. "
                          "The system is trying to protect you.".format(len(_iw),_iwr)})

        # T4: Weak ADX
        _adx_w = _closed_coach[_c_adx.lt(20) & _c_adx.gt(0)]
        if not _adx_w.empty:
            _ap = pd.to_numeric(_adx_w["Net P&L"], errors="coerce").sum()
            _timing_err.append({"mistake":"Entered when ADX < 20 (ranging/choppy market)","count":len(_adx_w),
                "impact":"Rs {:,.0f} total P&L".format(_ap),"sev":"MEDIUM",
                "fix":"ADX below 20 = no real trend. Options decay fast in choppy conditions. "
                      "Only enter when ADX > 25. You did this {}×.".format(len(_adx_w))})

        # P1: Revenge trading (loss>500 same day)
        if "Date" in _closed_coach.columns:
            _cs = _closed_coach.copy()
            _cs["_dt"] = pd.to_datetime(_cs["Date"], errors="coerce")
            _cs = _cs.sort_values("_dt").reset_index(drop=True)
            _rev = 0
            for _i in range(1,len(_cs)):
                _prev_r=_cs.iloc[_i-1]; _curr_r=_cs.iloc[_i]
                if (_prev_r["Result"]=="LOSS" and _curr_r["_dt"]==_prev_r["_dt"]
                        and pd.to_numeric(_prev_r["Net P&L"],errors="coerce")<-500):
                    _rev += 1
            if _rev>0:
                _psych_err.append({"mistake":"Revenge Trading — another trade same day after big loss","count":_rev,
                    "sev":"HIGH",
                    "fix":"After a loss > Rs 500 your brain is flooded with cortisol (stress hormone). "
                          "You traded on emotion, not analysis. Rule: STOP after any loss > Rs 500. "
                          "Close the app. Come back tomorrow."})

        # P2: Overtrading
        if "Date" in _closed_coach.columns:
            _dc = _closed_coach.groupby("Date").size()
            _ot = _dc[_dc>2]
            if not _ot.empty:
                _otl = sum(1 for _d,_ in _ot.items()
                           if pd.to_numeric(_closed_coach[_closed_coach["Date"]==_d]["Net P&L"],errors="coerce").sum()<0)
                _psych_err.append({"mistake":"Overtraded — 3+ trades in a single day","count":len(_ot),
                    "sev":"HIGH" if _otl>0 else "MEDIUM",
                    "fix":"More than 2 F&O trades per day = overtrading. "
                          "You did this on {} day(s), {} of which were losing days. "
                          "Rule: Maximum 2 trades per day. After 2, close the app.".format(len(_ot),_otl)})

        # P3: Opposite to dashboard
        if "Dashboard Said" in _closed_coach.columns and "Option Type" in _closed_coach.columns:
            _opp = _closed_coach[
                ((_closed_coach["Dashboard Said"].str.upper()=="PUT")  & (_closed_coach["Option Type"].str.upper()=="CALL")) |
                ((_closed_coach["Dashboard Said"].str.upper()=="CALL") & (_closed_coach["Option Type"].str.upper()=="PUT"))
            ]
            if not _opp.empty:
                _op = pd.to_numeric(_opp["Net P&L"], errors="coerce").sum()
                _psych_err.append({"mistake":"Traded OPPOSITE to Dashboard signal","count":len(_opp),
                    "sev":"HIGH",
                    "fix":"You went opposite to your own system {}× — 'I know better' thinking. "
                          "P&L on those trades: Rs {:,.0f}.".format(len(_opp),_op)})

        # ── Report card ───────────────────────────────────────────────────────
        _t_err_n  = sum(m["count"] for m in _timing_err)
        _p_err_n  = sum(m["count"] for m in _psych_err)
        _t_sc     = max(0, 100 - (_t_err_n/max(_c_total,1))*150)
        _p_sc     = max(0, 100 - (_p_err_n/max(_c_total,1))*150)
        _o_sc     = round(_t_sc*0.5 + _p_sc*0.5, 0)
        def _g(s): return "A" if s>=85 else ("B" if s>=70 else ("C" if s>=55 else ("D" if s>=40 else "F")))
        _gc = {"A":"#16a34a","B":"#2563eb","C":"#d97706","D":"#dc2626","F":"#7f1d1d"}

        _rc_html = "<div style='display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px'>"
        for _area,_sc,_sc_v in [("⏱️ Timing",_g(_t_sc),int(_t_sc)),
                                  ("🧠 Psychology",_g(_p_sc),int(_p_sc)),
                                  ("🏆 Overall",_g(_o_sc),int(_o_sc))]:
            _bg2 = _gc.get(_sc,"#374151")
            _rc_html += ("<div style='background:{b};border-radius:10px;padding:14px 18px;"
                         "min-width:140px;text-align:center;flex:1'>"
                         "<div style='font-size:34px;font-weight:900;color:#fff'>{g}</div>"
                         "<div style='font-size:12px;color:rgba(255,255,255,0.85)'>{a}</div>"
                         "<div style='font-size:11px;color:rgba(255,255,255,0.55)'>{v}/100</div>"
                         "</div>").format(b=_bg2,g=_sc,a=_area,v=_sc_v)
        _rc_html += "</div>"
        st.subheader("📋 Your Report Card")
        st.markdown(_rc_html, unsafe_allow_html=True)

        # ── Best / worst pattern ──────────────────────────────────────────────
        _w_df = _closed_coach[_closed_coach["Result"]=="WIN"]
        _l_df = _closed_coach[_closed_coach["Result"]=="LOSS"]
        _bw1,_bw2 = st.columns(2)
        with _bw1:
            if not _w_df.empty:
                _bst = _w_df["Supertrend"].mode().iloc[0] if "Supertrend" in _w_df.columns and not _w_df["Supertrend"].mode().empty else "—"
                _btp = _w_df["Option Type"].mode().iloc[0] if "Option Type" in _w_df.columns and not _w_df["Option Type"].mode().empty else "—"
                _brsi= round(_c_rsi[_closed_coach["Result"]=="WIN"].mean(),0)
                st.markdown("<div style='background:#052e16;border:1px solid #16a34a;border-radius:8px;padding:12px'>"
                    "<b style='color:#4ade80'>✅ Your WINNING pattern:</b><br>"
                    "<span style='font-size:13px;color:#bbf7d0'>{} option · Supertrend {} · RSI ~{:.0f}</span>"
                    "</div>".format(_btp,_bst,_brsi), unsafe_allow_html=True)
        with _bw2:
            if not _l_df.empty:
                _lst = _l_df["Supertrend"].mode().iloc[0] if "Supertrend" in _l_df.columns and not _l_df["Supertrend"].mode().empty else "—"
                _ltp = _l_df["Option Type"].mode().iloc[0] if "Option Type" in _l_df.columns and not _l_df["Option Type"].mode().empty else "—"
                _lrsi= round(_c_rsi[_closed_coach["Result"]=="LOSS"].mean(),0)
                st.markdown("<div style='background:#450a0a;border:1px solid #dc2626;border-radius:8px;padding:12px'>"
                    "<b style='color:#f87171'>❌ Your LOSING pattern:</b><br>"
                    "<span style='font-size:13px;color:#fecaca'>{} option · Supertrend {} · RSI ~{:.0f}</span>"
                    "</div>".format(_ltp,_lst,_lrsi), unsafe_allow_html=True)

        st.markdown("---")

        # ── Timing mistakes ───────────────────────────────────────────────────
        if _timing_err:
            st.subheader("⏱️ Timing Mistakes in Your Trades")
            for _m in _timing_err:
                _sc2 = "#450a0a" if _m["sev"]=="HIGH" else "#422006"
                _bd2 = "#dc2626" if _m["sev"]=="HIGH" else "#d97706"
                _tc2 = "#fca5a5" if _m["sev"]=="HIGH" else "#fbbf24"
                st.markdown(
                    "<div style='background:{bg};border:1.5px solid {bd};border-radius:9px;"
                    "padding:13px 17px;margin-bottom:9px'>"
                    "<div style='display:flex;justify-content:space-between;align-items:center'>"
                    "<b style='color:{tc};font-size:14px'>❌ {mk}</b>"
                    "<span style='font-size:11px;background:{bd};color:#fff;padding:2px 8px;border-radius:20px'>"
                    "{sv} · {cnt}×</span></div>"
                    "<div style='font-size:12px;color:#fde68a;margin-top:5px'>Impact: {imp}</div>"
                    "<div style='font-size:13px;color:#e2e8f0;margin-top:7px;line-height:1.7'>"
                    "💡 {fix}</div></div>".format(
                        bg=_sc2,bd=_bd2,tc=_tc2,mk=_m["mistake"],
                        sv=_m["sev"],cnt=_m["count"],imp=_m["impact"],fix=_m["fix"]),
                    unsafe_allow_html=True)
        else:
            st.success("✅ No timing mistakes found. Great discipline!")

        st.markdown("---")

        # ── Psychology mistakes ───────────────────────────────────────────────
        if _psych_err:
            st.subheader("🧠 Psychology & Discipline Mistakes")
            for _m in _psych_err:
                _sc3 = "#2d1b69" if _m["sev"]=="HIGH" else "#422006"
                _bd3 = "#7c3aed" if _m["sev"]=="HIGH" else "#d97706"
                _tc3 = "#c4b5fd" if _m["sev"]=="HIGH" else "#fbbf24"
                st.markdown(
                    "<div style='background:{bg};border:1.5px solid {bd};border-radius:9px;"
                    "padding:13px 17px;margin-bottom:9px'>"
                    "<div style='display:flex;justify-content:space-between;align-items:center'>"
                    "<b style='color:{tc};font-size:14px'>🧠 {mk}</b>"
                    "<span style='font-size:11px;background:{bd};color:#fff;padding:2px 8px;border-radius:20px'>"
                    "{sv} · {cnt}×</span></div>"
                    "<div style='font-size:13px;color:#e2e8f0;margin-top:7px;line-height:1.7'>"
                    "💡 {fix}</div></div>".format(
                        bg=_sc3,bd=_bd3,tc=_tc3,mk=_m["mistake"],
                        sv=_m["sev"],cnt=_m["count"],fix=_m["fix"]),
                    unsafe_allow_html=True)
        else:
            st.success("✅ No psychology mistakes detected. Great emotional discipline!")

        st.markdown("---")

        # ── Personal rules derived from data ─────────────────────────────────
        st.subheader("📌 Your Personal Rules — Built From YOUR Data")
        _rules = []
        if _c_wr>=50: _rules.append("✅ Your win rate {:.0f}% is above 50%. Protect it.".format(_c_wr))
        else:         _rules.append("⚠️ Win rate {:.0f}% is below 50%. Focus on fewer, higher-quality trades.".format(_c_wr))
        if _t_err_n>0: _rules.append("📌 RULE #1: Check RSI zone + Supertrend alignment BEFORE clicking buy.")
        if any("Revenge" in m["mistake"] for m in _psych_err):
            _rules.append("📌 RULE #2: After any loss > Rs 500 — close the app for the day. No exceptions.")
        if any("Overtrad" in m["mistake"] for m in _psych_err):
            _rules.append("📌 RULE #3: Maximum 2 trades per day. After 2, you are done.")
        if any("WAIT" in m["mistake"] for m in _timing_err):
            _rules.append("📌 RULE #4: When dashboard says WAIT, close your broker app immediately.")
        for _r in _rules:
            _bg3 = "#f0fdf4" if _r.startswith("✅") else "#fffbeb"
            _bd4 = "#86efac" if _r.startswith("✅") else "#fcd34d"
            st.markdown("<div style='background:{b};border:1px solid {bd};border-radius:7px;"
                        "padding:10px 15px;margin-bottom:7px;font-size:13px;color:#1e293b'>{r}</div>".format(
                        b=_bg3,bd=_bd4,r=_r), unsafe_allow_html=True)

        # ── Trade table with flags ────────────────────────────────────────────
        st.markdown("---")
        st.subheader("📊 Every Trade — With Coach Flags")
        _flags = []
        for _i2, _row2 in _closed_coach.iterrows():
            _f2 = []
            _rv2 = pd.to_numeric(_row2.get("Entry RSI",""), errors="coerce")
            _av2 = pd.to_numeric(_row2.get("Entry ADX",""), errors="coerce")
            _sv2 = str(_row2.get("Supertrend","")).upper()
            _ov2 = str(_row2.get("Option Type","")).upper()
            _dv2 = str(_row2.get("Dashboard Said","")).upper()
            if pd.notna(_rv2) and (_rv2>65 or _rv2<35): _f2.append("⚠️ RSI Extreme")
            if _sv2=="BEARISH" and _ov2=="CALL":         _f2.append("❌ Against ST")
            if _sv2=="BULLISH" and _ov2=="PUT":          _f2.append("❌ Against ST")
            if _dv2=="WAIT":                             _f2.append("⚠️ Dashboard=WAIT")
            if _dv2 in ("PUT","CALL") and _dv2!=_ov2:   _f2.append("❌ Ignored Signal")
            if pd.notna(_av2) and _av2<20:               _f2.append("⚠️ ADX Weak")
            if not _f2:                                  _f2.append("✅ Clean Entry")
            _flags.append(" | ".join(_f2))
        _closed_coach["⚑ Coach Flags"] = _flags
        _dcols = ["Trade #","Date","Option Type","Strike","Entry RSI","Entry ADX",
                  "Supertrend","Dashboard Said","Net P&L","Result","⚑ Coach Flags"]
        _avcols = [c for c in _dcols if c in _closed_coach.columns]
        st.dataframe(_closed_coach[_avcols].sort_values("Trade #",ascending=False),
                     use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### 💬 Chat with AI Coach — Ask anything about your trades")
    st.caption("Powered by Google Gemini (free) · The AI already knows your stats above.")
    st.markdown("---")

    # ── API key setup ────────────────────────────────────────────────────────
    try:
        if "gemini_api_key" in st.secrets:
            gemini_key = st.secrets["gemini_api_key"]
        else:
            gemini_key = ""
    except Exception:
        gemini_key = ""

    if not gemini_key:
        st.warning(
            "**Gemini API key not found.**\n\n"
            "To enable the AI coach:\n"
            "1. Go to [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) — it's **free**, no credit card.\n"
            "2. Create a key and copy it.\n"
            "3. In Streamlit Cloud → your app → **Settings → Secrets**, add:\n"
            "```\ngemini_api_key = \"YOUR_KEY_HERE\"\n```\n"
            "4. Save & reboot the app.\n\n"
            "Until then, you can type your key below to try it out right now (not saved anywhere)."
        )
        temp_key = st.text_input("🔑 Paste your Gemini API key here (temporary, session only)", type="password")
        if temp_key:
            gemini_key = temp_key

    if not gemini_key:
        st.info("👆 Add your free Gemini API key above to start chatting with the AI Trading Coach.")
        st.stop()

    # ── Build DEEP personalised context from all trade data + mistake analysis ─
    _today_ctx   = datetime.now(IST).strftime("%A, %d %b %Y %I:%M %p IST")
    _vd          = build_day_verdict("")
    _trade_stats = stats  # already computed at top of file

    # Build actual trade rows to inject (last 20 closed trades)
    _coach_trades_ctx = load_trades()
    _closed_ctx = _coach_trades_ctx[
        _coach_trades_ctx["Result"].isin(["WIN","LOSS"])
    ].copy() if not _coach_trades_ctx.empty else pd.DataFrame()

    _trade_rows_str = "No trades logged yet."
    _mistake_summary = "No trade history — no mistakes to analyse yet."
    _personal_rules_str = ""
    _best_pattern_str = "—"
    _worst_pattern_str = "—"

    if not _closed_ctx.empty:
        # Format last 20 trades as a compact table for the prompt
        _last20 = _closed_ctx.tail(20)
        _rows = []
        for _, _r in _last20.iterrows():
            _rows.append(
                "Trade#{tn} | {dt} | {ot} | Strike {st} | Entry {ep} | Exit {ex} | "
                "RSI@entry {rsi} | ADX@entry {adx} | Supertrend {spd} | Dashboard said {ds} | "
                "Result {res} | Net P&L Rs {pnl} | Lessons: {les}".format(
                    tn=_r.get("Trade #","?"),
                    dt=str(_r.get("Date",""))[:10],
                    ot=_r.get("Option Type","?"),
                    st=_r.get("Strike","?"),
                    ep=_r.get("Entry Price","?"),
                    ex=_r.get("Exit Price","?") if str(_r.get("Exit Price","")).strip() else "open",
                    rsi=_r.get("Entry RSI","?"),
                    adx=_r.get("Entry ADX","?"),
                    spd=_r.get("Supertrend","?"),
                    ds=_r.get("Dashboard Said","?"),
                    res=_r.get("Result","?"),
                    pnl=_r.get("Net P&L","?"),
                    les=str(_r.get("Lessons Learned","")).strip() or "none noted",
                )
            )
        _trade_rows_str = "\n".join(_rows)

        # Run mistake analysis inline
        _c_rsi_ctx = pd.to_numeric(_closed_ctx["Entry RSI"], errors="coerce")
        _c_adx_ctx = pd.to_numeric(_closed_ctx["Entry ADX"], errors="coerce")
        _c_total_ctx = len(_closed_ctx)
        _c_wr_ctx = round((_closed_ctx["Result"]=="WIN").sum() / _c_total_ctx * 100, 1)

        _mistakes_found = []

        # RSI extreme entries
        _rsi_ext_ctx = _closed_ctx[_c_rsi_ctx.gt(65) | _c_rsi_ctx.lt(35)]
        if not _rsi_ext_ctx.empty:
            _rp = pd.to_numeric(_rsi_ext_ctx["Net P&L"], errors="coerce").sum()
            _mistakes_found.append(
                "TIMING: Entered {n}x in extreme RSI zone (>65 or <35). "
                "P&L on those trades: Rs {p:,.0f}. "
                "These are high-reversal-risk entries.".format(n=len(_rsi_ext_ctx), p=_rp)
            )

        # Against Supertrend
        if "Supertrend" in _closed_ctx.columns and "Option Type" in _closed_ctx.columns:
            _st_ctx = _closed_ctx[
                ((_closed_ctx["Supertrend"].str.upper()=="BEARISH") & (_closed_ctx["Option Type"].str.upper()=="CALL")) |
                ((_closed_ctx["Supertrend"].str.upper()=="BULLISH") & (_closed_ctx["Option Type"].str.upper()=="PUT"))
            ]
            if not _st_ctx.empty:
                _sp2 = pd.to_numeric(_st_ctx["Net P&L"], errors="coerce").sum()
                _mistakes_found.append(
                    "TIMING: Entered against Supertrend {n}x (BEARISH but bought CALL, or BULLISH but bought PUT). "
                    "P&L: Rs {p:,.0f}. This is trading against the primary trend.".format(n=len(_st_ctx), p=_sp2)
                )

        # Dashboard said WAIT but entered
        if "Dashboard Said" in _closed_ctx.columns:
            _iw_ctx = _closed_ctx[_closed_ctx["Dashboard Said"].str.upper()=="WAIT"]
            if not _iw_ctx.empty:
                _iwp2 = pd.to_numeric(_iw_ctx["Net P&L"], errors="coerce").sum()
                _iwr2 = round((_iw_ctx["Result"]=="WIN").sum()/len(_iw_ctx)*100,1)
                _mistakes_found.append(
                    "TIMING: Entered {n}x when dashboard said WAIT. "
                    "Win rate on those: {wr}%. P&L: Rs {p:,.0f}. "
                    "Trader is ignoring the system's caution signal.".format(
                        n=len(_iw_ctx), wr=_iwr2, p=_iwp2)
                )

        # Opposite to dashboard
        if "Dashboard Said" in _closed_ctx.columns and "Option Type" in _closed_ctx.columns:
            _opp_ctx = _closed_ctx[
                ((_closed_ctx["Dashboard Said"].str.upper()=="PUT") & (_closed_ctx["Option Type"].str.upper()=="CALL")) |
                ((_closed_ctx["Dashboard Said"].str.upper()=="CALL") & (_closed_ctx["Option Type"].str.upper()=="PUT"))
            ]
            if not _opp_ctx.empty:
                _op2 = pd.to_numeric(_opp_ctx["Net P&L"], errors="coerce").sum()
                _mistakes_found.append(
                    "PSYCHOLOGY: Traded opposite to dashboard signal {n}x. "
                    "P&L: Rs {p:,.0f}. Classic overconfidence / 'I know better' pattern.".format(
                        n=len(_opp_ctx), p=_op2)
                )

        # Revenge trading
        if "Date" in _closed_ctx.columns:
            _cs2 = _closed_ctx.copy()
            _cs2["_dt2"] = pd.to_datetime(_cs2["Date"], errors="coerce")
            _cs2 = _cs2.sort_values("_dt2").reset_index(drop=True)
            _rev2 = 0
            for _i3 in range(1, len(_cs2)):
                _p3 = _cs2.iloc[_i3-1]; _c3 = _cs2.iloc[_i3]
                if (_p3["Result"]=="LOSS" and _c3["_dt2"]==_p3["_dt2"]
                        and pd.to_numeric(_p3["Net P&L"], errors="coerce") < -500):
                    _rev2 += 1
            if _rev2 > 0:
                _mistakes_found.append(
                    "PSYCHOLOGY: Revenge traded {n}x — placed a new trade the same day "
                    "immediately after a loss > Rs 500. Classic emotional trading.".format(n=_rev2)
                )

        # Overtrading
        if "Date" in _closed_ctx.columns:
            _dc2 = _closed_ctx.groupby("Date").size()
            _ot2 = _dc2[_dc2 > 2]
            if not _ot2.empty:
                _mistakes_found.append(
                    "PSYCHOLOGY: Overtraded on {n} day(s) — placed 3+ trades in a single day. "
                    "This is the most common capital-destruction pattern.".format(n=len(_ot2))
                )

        # ADX weak
        _adx_w2 = _closed_ctx[_c_adx_ctx.lt(20) & _c_adx_ctx.gt(0)]
        if not _adx_w2.empty:
            _mistakes_found.append(
                "TIMING: Entered {n}x when ADX was below 20 (choppy/ranging market). "
                "Options lose premium fast in no-trend conditions.".format(n=len(_adx_w2))
            )

        _mistake_summary = "\n".join("- " + m for m in _mistakes_found) if _mistakes_found else "No specific mistakes detected in current data."

        # Personal rules
        _pr = []
        if _c_wr_ctx < 50: _pr.append("Win rate is {:.0f}% — below 50%, needs improvement".format(_c_wr_ctx))
        if _rsi_ext_ctx is not None and not _rsi_ext_ctx.empty: _pr.append("Must check RSI zone before every entry")
        if any("Revenge" in m for m in _mistakes_found): _pr.append("Must stop trading after any loss > Rs 500")
        if any("Overtrad" in m for m in _mistakes_found): _pr.append("Maximum 2 trades per day — hard rule")
        _personal_rules_str = "; ".join(_pr) if _pr else "No specific rules triggered yet."

        # Best/worst pattern
        _w2 = _closed_ctx[_closed_ctx["Result"]=="WIN"]
        _l2 = _closed_ctx[_closed_ctx["Result"]=="LOSS"]
        if not _w2.empty and "Option Type" in _w2.columns:
            _btp2 = _w2["Option Type"].mode().iloc[0] if not _w2["Option Type"].mode().empty else "—"
            _bst2 = _w2["Supertrend"].mode().iloc[0] if "Supertrend" in _w2.columns and not _w2["Supertrend"].mode().empty else "—"
            _brsi2 = round(_c_rsi_ctx[_closed_ctx["Result"]=="WIN"].mean(), 0)
            _best_pattern_str = "{} option, Supertrend {}, RSI ~{:.0f}".format(_btp2, _bst2, _brsi2)
        if not _l2.empty and "Option Type" in _l2.columns:
            _ltp2 = _l2["Option Type"].mode().iloc[0] if not _l2["Option Type"].mode().empty else "—"
            _lst2 = _l2["Supertrend"].mode().iloc[0] if "Supertrend" in _l2.columns and not _l2["Supertrend"].mode().empty else "—"
            _lrsi2 = round(_c_rsi_ctx[_closed_ctx["Result"]=="LOSS"].mean(), 0)
            _worst_pattern_str = "{} option, Supertrend {}, RSI ~{:.0f}".format(_ltp2, _lst2, _lrsi2)

    # Pre-compute conditional labels so .format() stays clean
    _wr_val  = _trade_stats["win_rate"]
    _rr_val  = _trade_stats["reward_risk"]
    _wr_note = "(BELOW 50% — needs urgent improvement)" if _wr_val < 50 else "(above 50% — protect it)"
    _rr_note = "(BAD — avg loss bigger than avg win)" if _rr_val < 1.0 else ("(OK — improve to 1.5+)" if _rr_val < 1.5 else "(GOOD)")

    SYSTEM_PROMPT = (
        "You are a brutally honest, specific, personal Nifty F&O trading coach for an Indian retail trader.\n\n"
        "CRITICAL RULES FOR YOUR RESPONSES:\n"
        "1. NEVER give generic advice. Every answer MUST reference the trader's actual data shown below.\n"
        "2. If the trader asks about their mistakes — name the exact mistakes found in their trade history.\n"
        "3. If they ask why they are losing — point to the specific patterns in their data.\n"
        "4. If they ask should they trade today — use the Day Verdict and current time window.\n"
        "5. Be direct. Do not pad responses. Under 250 words unless they ask for detail.\n"
        "6. Always cite numbers from their data (e.g. 'You entered RSI extreme zone 3 times').\n"
        "7. Never say 'it depends' without immediately saying what it depends on and what YOU recommend.\n\n"
        "=== TRADER'S LIVE PROFILE ===\n"
        "Date/Time: {dt}\n"
        "Today's Market Verdict: {verdict}\n"
        "Verdict Detail: {vdetail}\n"
        "Checks: {passn} passed | {warnn} cautions | {failn} failed\n"
        "Time Window Right Now: {tw_label} — {tw_note}\n\n"
        "=== TRADER'S PERFORMANCE STATS ===\n"
        "Total Closed Trades: {total_trades}\n"
        "Win Rate: {win_rate}% {wr_note}\n"
        "Total Net P&L: Rs {total_pnl:,.0f}\n"
        "Best Trade: Rs {best:,.0f} | Worst Trade: Rs {worst:,.0f}\n"
        "Avg Win: Rs {avg_win:,.0f} | Avg Loss: Rs {avg_loss:,.0f}\n"
        "Reward:Risk Ratio: {rr} {rr_note}\n"
        "Max Drawdown: Rs {mdd:,.0f}\n"
        "Total Charges Paid: Rs {charges:,.0f}\n\n"
        "=== WINNING SETUP PATTERN (when trader wins most) ===\n"
        "{best_pattern}\n\n"
        "=== LOSING SETUP PATTERN (when trader loses most) ===\n"
        "{worst_pattern}\n\n"
        "=== SPECIFIC MISTAKES DETECTED IN TRADE HISTORY ===\n"
        "{mistakes}\n\n"
        "=== PERSONAL RULES TRIGGERED BY DATA ===\n"
        "{rules}\n\n"
        "=== LAST 20 ACTUAL TRADES (most recent first) ===\n"
        "{trade_rows}\n\n"
        "When the trader asks ANY question, your answer must be grounded in the data above.\n"
        "Do NOT give textbook answers. Give answers that address THIS trader's specific patterns.\n"
    ).format(
        dt=_today_ctx,
        verdict=_vd["verdict"],
        vdetail=_vd["verdict_detail"],
        passn=_vd["pass_count"],
        warnn=_vd["warn_count"],
        failn=_vd["fail_count"],
        tw_label=_vd["tw"]["label"],
        tw_note=_vd["tw"]["note"],
        total_trades=_trade_stats["total_trades"],
        win_rate=_wr_val,
        wr_note=_wr_note,
        total_pnl=_trade_stats["total_pnl"],
        best=_trade_stats["best_trade"],
        worst=_trade_stats["worst_trade"],
        avg_win=_trade_stats["avg_win"],
        avg_loss=_trade_stats["avg_loss"],
        rr=_rr_val,
        rr_note=_rr_note,
        mdd=_trade_stats["max_drawdown"],
        charges=_trade_stats["total_charges"],
        best_pattern=_best_pattern_str,
        worst_pattern=_worst_pattern_str,
        mistakes=_mistake_summary,
        rules=_personal_rules_str,
        trade_rows=_trade_rows_str,
    )

    # ── Suggested starter questions (personalised based on data) ─────────────
    st.markdown("**💡 Try asking — these are specific to YOUR trade history:**")
    q_cols = st.columns(3)
    # Dynamically build questions based on what mistakes were actually found
    starter_qs = ["What are my biggest mistakes?", "Why am I losing money?", "Should I trade today?"]
    if _mistake_summary != "No trade history — no mistakes to analyse yet.":
        if "RSI" in _mistake_summary:
            starter_qs.append("Explain my RSI entry problem")
        if "Supertrend" in _mistake_summary:
            starter_qs.append("Why is trading against Supertrend bad for me?")
        if "Revenge" in _mistake_summary:
            starter_qs.append("How do I stop revenge trading?")
        if "Overtrad" in _mistake_summary:
            starter_qs.append("How do I stop overtrading?")
        if "WAIT" in _mistake_summary:
            starter_qs.append("Why should I trust the dashboard's WAIT signal?")
    starter_qs = starter_qs[:6]  # keep max 6
    for i, q in enumerate(starter_qs):
        if q_cols[i % 3].button(q, key="sq_{}".format(i), use_container_width=True):
            if "ai_messages" not in st.session_state:
                st.session_state["ai_messages"] = []
            st.session_state["ai_messages"].append({"role": "user", "content": q})
            st.rerun()

    st.markdown("---")

    # ── Chat history ──────────────────────────────────────────────────────────
    if "ai_messages" not in st.session_state:
        st.session_state["ai_messages"] = []

    for msg in st.session_state["ai_messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── Chat input ────────────────────────────────────────────────────────────
    user_input = st.chat_input("Ask your trading question…")

    if user_input:
        st.session_state["ai_messages"].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=gemini_key)

                    # Dynamic discovery: query Google AI for currently supported models
                    supported_models = []
                    try:
                        for m in genai.list_models():
                            if "generateContent" in getattr(m, "supported_generation_methods", []):
                                supported_models.append(m.name)
                    except Exception:
                        pass

                    # Fallback list if list_models() fails
                    candidate_models = supported_models or [
                        "models/gemini-2.5-flash",
                        "models/gemini-1.5-flash",
                        "models/gemini-1.5-pro",
                        "models/gemini-pro",
                        "gemini-2.5-flash",
                        "gemini-1.5-flash",
                        "gemini-1.5-pro",
                    ]

                    # Prioritize flash models first for fast responses
                    candidate_models.sort(key=lambda name: (0 if "flash" in name.lower() else 1))

                    # Build chat history for context (last 10 turns to stay within token limits)
                    history_for_api = []
                    for m in st.session_state["ai_messages"][:-1][-10:]:
                        history_for_api.append({
                            "role": "user" if m["role"] == "user" else "model",
                            "parts": [m["content"]],
                        })
                    reply = None
                    last_err = ""
                    for _model_name in candidate_models:
                        try:
                            # Strip "models/" prefix if present when passing to GenerativeModel
                            clean_name = _model_name.replace("models/", "")
                            model = genai.GenerativeModel(
                                model_name=clean_name,
                                system_instruction=SYSTEM_PROMPT,
                            )
                            chat = model.start_chat(history=history_for_api)
                            response = chat.send_message(user_input)
                            reply = response.text
                            break
                        except Exception as _me:
                            last_err = str(_me)
                            continue
                    if reply is None:
                        reply = "⚠️ All Gemini models unavailable: `{}`. Try again later.".format(last_err)
                except Exception as ai_err:
                    reply = "⚠️ Could not get a response: `{}`. Check your API key or try again.".format(str(ai_err))
                st.markdown(reply)
        st.session_state["ai_messages"].append({"role": "assistant", "content": reply})

    # ── Reset button ──────────────────────────────────────────────────────────
    if st.session_state.get("ai_messages"):
        if st.button("🗑️ Clear Chat", use_container_width=False):
            st.session_state["ai_messages"] = []
            st.rerun()

    st.markdown("---")
    st.caption("⚠️ AI Trading Coach is for **educational purposes only**. Not financial advice. F&O trading involves significant risk.")


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 🤝 AI TRADING PARTNER
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🤝 AI Trading Partner":

    st.title("🤝 AI Trading Partner")
    st.caption(
        "Not a coach. A co-trader. Reads live candles right now. "
        "Remembers every pattern we traded together. Grows with you every day."
    )

    # ── Gemini key check ──────────────────────────────────────────────────────
    try:
        _pk = st.secrets.get("gemini_api_key", "")
    except Exception:
        _pk = ""
    if not _pk:
        st.warning(
            "**Gemini API key needed.**\n\n"
            "Go to Streamlit Cloud → your app → **Settings → Secrets** and add:\n"
            "```\ngemini_api_key = \"YOUR_FREE_KEY\"\n```\n"
            "Get a free key at [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)"
        )
        _pk_tmp = st.text_input("🔑 Paste key here to try now (not saved)", type="password", key="partner_key_tmp")
        if _pk_tmp:
            _pk = _pk_tmp
        else:
            st.stop()

    # ── Load live chart data (same symbol/interval from sidebar) ─────────────
    try:
        _pt_df = load_chart_data(symbol, interval, period)
        _pt_s  = get_summary(_pt_df)
        _pt_d  = compute_decision(_pt_s)
        _pt_v  = build_day_verdict(manual_event)
        _pt_ps = compute_precision_signal(_pt_df, _pt_s, _pt_d, _pt_v)
        _has_live = True
    except Exception as _e:
        st.error("Could not load live data: {}".format(_e))
        _has_live = False

    # ── Load all past trades ──────────────────────────────────────────────────
    _pt_trades = load_trades()
    _pt_closed = _pt_trades[_pt_trades["Result"].isin(["WIN","LOSS"])].copy() \
        if not _pt_trades.empty else pd.DataFrame()

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION A: LIVE SIGNAL — what to do RIGHT NOW
    # ─────────────────────────────────────────────────────────────────────────
    if _has_live:
        _ltp   = _pt_s["close"]
        _atr   = _pt_s["atr"] if _pt_s["atr"] > 0 else _ltp * 0.005
        _dirn  = _pt_ps.get("direction", _pt_d["direction"])
        _tw    = _pt_v["tw"]
        _now_t = datetime.now(IST).strftime("%H:%M")

        # Colour coding
        if _dirn == "CALL":
            _sbg, _sbd, _sfc = "#052e16", "#16a34a", "#4ade80"
            _entry_px = round(_ltp + _atr * 0.1, 0)      # slight premium above LTP
            _target1  = round(_ltp + _atr * 1.5, 0)
            _target2  = round(_ltp + _atr * 3.0, 0)
            _sl_px    = round(_ltp - _atr * 0.75, 0)
            _atm      = round(_ltp / 50) * 50
            _trade_str = "BUY {atm} CE (CALL)".format(atm=int(_atm))
            _reason_short = "Bullish setup — {bull} bull signals vs {bear} bear".format(
                bull=_pt_d["bull_score"], bear=_pt_d["bear_score"])
        elif _dirn == "PUT":
            _sbg, _sbd, _sfc = "#2e0505", "#dc2626", "#f87171"
            _entry_px = round(_ltp - _atr * 0.1, 0)
            _target1  = round(_ltp - _atr * 1.5, 0)
            _target2  = round(_ltp - _atr * 3.0, 0)
            _sl_px    = round(_ltp + _atr * 0.75, 0)
            _atm      = round(_ltp / 50) * 50
            _trade_str = "BUY {atm} PE (PUT)".format(atm=int(_atm))
            _reason_short = "Bearish setup — {bear} bear signals vs {bull} bull".format(
                bear=_pt_d["bear_score"], bull=_pt_d["bull_score"])
        else:
            _sbg, _sbd, _sfc = "#1c1c0a", "#ca8a04", "#fde047"
            _entry_px = _target1 = _target2 = _sl_px = 0
            _atm      = round(_ltp / 50) * 50
            _trade_str = "WAIT — DO NOT ENTER"
            _reason_short = "Mixed signals. No clear edge right now."

        # ── Big live call box ─────────────────────────────────────────────────
        if _dirn in ("CALL", "PUT"):
            st.markdown(
                "<div style='background:{bg};border:3px solid {bd};border-radius:14px;"
                "padding:20px 26px;margin-bottom:16px'>"
                "<div style='font-size:13px;color:{fc};opacity:0.7;margin-bottom:4px'>"
                "⏰ NOW — {tw} &nbsp;|&nbsp; {sym} {ivl}</div>"
                "<div style='font-size:36px;font-weight:900;color:{fc};letter-spacing:1px'>"
                "{trade}</div>"
                "<div style='display:flex;gap:28px;margin-top:14px;flex-wrap:wrap'>"
                "<div><div style='font-size:11px;color:{fc};opacity:0.65'>📍 ENTER WHEN NIFTY</div>"
                "<div style='font-size:22px;font-weight:800;color:{fc}'>"
                "{dirword} Rs {ep:,.0f}</div></div>"
                "<div><div style='font-size:11px;color:{fc};opacity:0.65'>✅ TARGET 1 (book 50%)</div>"
                "<div style='font-size:22px;font-weight:800;color:#4ade80'>Rs {t1:,.0f}</div></div>"
                "<div><div style='font-size:11px;color:{fc};opacity:0.65'>🏁 TARGET 2 (exit all)</div>"
                "<div style='font-size:22px;font-weight:800;color:#86efac'>Rs {t2:,.0f}</div></div>"
                "<div><div style='font-size:11px;color:{fc};opacity:0.65'>🛑 STOP LOSS — EXIT ALL</div>"
                "<div style='font-size:22px;font-weight:800;color:#fca5a5'>Rs {sl:,.0f}</div></div>"
                "</div>"
                "<div style='font-size:12px;color:{fc};opacity:0.7;margin-top:10px'>"
                "Why: {why}</div>"
                "</div>".format(
                    bg=_sbg, bd=_sbd, fc=_sfc,
                    tw=_tw["label"], sym=symbol, ivl=interval,
                    trade=_trade_str,
                    dirword="crosses above" if _dirn=="CALL" else "drops below",
                    ep=_entry_px, t1=_target1, t2=_target2, sl=_sl_px,
                    why=_reason_short,
                ),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='background:{bg};border:2px solid {bd};border-radius:14px;"
                "padding:18px 24px;margin-bottom:16px;text-align:center'>"
                "<div style='font-size:28px;font-weight:900;color:{fc}'>{trade}</div>"
                "<div style='font-size:13px;color:{fc};opacity:0.75;margin-top:6px'>{why}</div>"
                "</div>".format(bg=_sbg, bd=_sbd, fc=_sfc, trade=_trade_str, why=_reason_short),
                unsafe_allow_html=True,
            )

        # ── What the current candle is saying ────────────────────────────────
        _patterns_now = detect_candle_patterns(_pt_df)
        _top_pat = next((p for p in _patterns_now if p["signal"] != "WAIT"), None)

        st.markdown("---")
        _pc1, _pc2, _pc3, _pc4, _pc5 = st.columns(5)
        _pc1.metric("LTP",        "Rs {:,.0f}".format(_ltp))
        _pc2.metric("RSI",        "{:.1f}".format(_pt_s["rsi"]),
                    "OB⚠️" if _pt_s["rsi"]>65 else ("OS⚠️" if _pt_s["rsi"]<35 else "OK"))
        _pc3.metric("Supertrend", _pt_s["supertrend"])
        _pc4.metric("ADX",        "{:.1f}".format(_pt_s["adx"]),
                    "Strong" if _pt_s["adx"]>25 else "Weak/Choppy")
        _pc5.metric("Candle",     _top_pat["name"] if _top_pat else "No pattern",
                    _top_pat["signal"] if _top_pat else "—")

        # ── Pattern history lookup — "last time we saw this" ─────────────────
        if _top_pat and not _pt_closed.empty:
            _same_pat_trades = _pt_closed[
                _pt_closed["Notes"].str.contains(_top_pat["name"], case=False, na=False) |
                _pt_closed["Lessons Learned"].str.contains(_top_pat["name"], case=False, na=False)
            ]
            if not _same_pat_trades.empty:
                _sp_pnl = pd.to_numeric(_same_pat_trades["Net P&L"], errors="coerce").sum()
                _sp_wr  = round((_same_pat_trades["Result"]=="WIN").sum() / len(_same_pat_trades) * 100, 0)
                st.info(
                    "🧠 **Pattern memory:** Last time we saw **{}** in your trades, "
                    "you had **{:.0f}% win rate** over {} trade(s), total P&L Rs {:,.0f}. "
                    "Factor this into your decision.".format(
                        _top_pat["name"], _sp_wr, len(_same_pat_trades), _sp_pnl)
                )

    st.markdown("---")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION B: PSYCHOLOGY CHECK-IN before trading
    # ─────────────────────────────────────────────────────────────────────────
    st.subheader("🧘 How are you feeling RIGHT NOW? (takes 10 seconds)")
    st.caption(
        "Your partner reads this before every suggestion. "
        "Your mental state is as important as RSI. Be honest."
    )

    _pcol1, _pcol2 = st.columns([2, 1])
    with _pcol1:
        _mood = st.select_slider(
            "Mental state right now",
            options=["😰 Anxious", "😟 Worried", "😐 Neutral", "😊 Calm", "💪 Confident", "🔥 Overexcited"],
            value="😊 Calm",
            key="partner_mood",
        )
        _psych_note = st.text_input(
            "Any thoughts affecting your trading today? (optional but powerful)",
            placeholder="e.g. Lost ₹2000 yesterday and want to recover... / Feeling patient today / Market looks scary",
            key="partner_psych_note",
        )
    with _pcol2:
        _mood_risk = {
            "😰 Anxious":     ("HIGH RISK", "#dc2626", "Anxiety = paralysis or panic exits. Trade ½ lot or skip today."),
            "😟 Worried":     ("ELEVATED",  "#d97706", "Worry means you'll exit too early or too late. Be strict with SL."),
            "😐 Neutral":     ("MODERATE",  "#94a3b8", "Neutral is fine. Follow the system mechanically."),
            "😊 Calm":        ("LOW RISK",  "#16a34a", "Calm = best state for trading. Full lot size OK."),
            "💪 Confident":   ("LOW RISK",  "#2563eb", "Confidence is good. Don't let it become overconfidence."),
            "🔥 Overexcited": ("HIGH RISK", "#dc2626", "Excitement = impulsive entries. Wait for confirmation. ½ lot max."),
        }
        _mr, _mc, _mt = _mood_risk.get(_mood, ("MODERATE", "#94a3b8", ""))
        st.markdown(
            "<div style='background:#0f172a;border:2px solid {c};border-radius:10px;"
            "padding:14px;text-align:center;margin-top:8px'>"
            "<div style='font-size:11px;color:#94a3b8'>Psychology Risk</div>"
            "<div style='font-size:20px;font-weight:900;color:{c}'>{r}</div>"
            "<div style='font-size:12px;color:#cbd5e1;margin-top:6px;line-height:1.5'>{t}</div>"
            "</div>".format(c=_mc, r=_mr, t=_mt),
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION C: PATTERN MEMORY — what we learned from past trades
    # ─────────────────────────────────────────────────────────────────────────
    st.subheader("🧠 What We Learned Together (Pattern Memory)")
    st.caption("Every trade teaches us something. This is what your partner has learned from your history.")

    if _pt_closed.empty:
        st.info("📭 No closed trades yet. Make your first trade and log it — your partner starts learning immediately.")
    else:
        _pm_rsi  = pd.to_numeric(_pt_closed["Entry RSI"],  errors="coerce")
        _pm_adx  = pd.to_numeric(_pt_closed["Entry ADX"],  errors="coerce")
        _pm_pnl  = pd.to_numeric(_pt_closed["Net P&L"],    errors="coerce").fillna(0)
        _pt_total = len(_pt_closed)
        _pt_wins  = (_pt_closed["Result"]=="WIN").sum()

        # Best and worst candle patterns from notes
        _pat_memory = {}
        for _, _tr in _pt_closed.iterrows():
            _notes_combined = (str(_tr.get("Notes","")) + " " + str(_tr.get("Lessons Learned",""))).lower()
            for _pname in ["bullish engulfing","bearish engulfing","hammer","shooting star",
                           "doji","morning star","evening star","pin bar","inside bar",
                           "marubozu","harami","spinning top"]:
                if _pname in _notes_combined:
                    if _pname not in _pat_memory:
                        _pat_memory[_pname] = {"wins":0, "losses":0, "pnl":0}
                    if _tr.get("Result") == "WIN":
                        _pat_memory[_pname]["wins"]   += 1
                    else:
                        _pat_memory[_pname]["losses"] += 1
                    _pat_memory[_pname]["pnl"] += float(pd.to_numeric(_tr.get("Net P&L",0), errors="coerce") or 0)

        # RSI zone performance
        _rsi_zones = {
            "35–50 (bearish)":  _pt_closed[_pm_rsi.between(35,50)],
            "50–65 (bullish)":  _pt_closed[_pm_rsi.between(50,65)],
            ">65 (overbought)": _pt_closed[_pm_rsi.gt(65)],
            "<35 (oversold)":   _pt_closed[_pm_rsi.lt(35)],
        }

        _mem_col1, _mem_col2 = st.columns(2)

        with _mem_col1:
            st.markdown("**📊 Your performance by RSI zone at entry:**")
            for _zname, _zdf in _rsi_zones.items():
                if _zdf.empty:
                    continue
                _zw   = (_zdf["Result"]=="WIN").sum()
                _zpnl = pd.to_numeric(_zdf["Net P&L"], errors="coerce").sum()
                _zwr  = round(_zw / len(_zdf) * 100, 0)
                _zbg  = "#052e16" if _zwr >= 60 else ("#422006" if _zwr >= 40 else "#450a0a")
                _zbd  = "#16a34a" if _zwr >= 60 else ("#d97706" if _zwr >= 40 else "#dc2626")
                st.markdown(
                    "<div style='background:{bg};border:1px solid {bd};border-radius:7px;"
                    "padding:8px 12px;margin-bottom:6px;display:flex;justify-content:space-between;"
                    "align-items:center'>"
                    "<span style='font-size:13px;color:#e2e8f0'>RSI {z}</span>"
                    "<span style='font-size:13px;font-weight:700;color:{bd}'>"
                    "{wr:.0f}% WR · {n} trades · Rs {pnl:,.0f}</span>"
                    "</div>".format(bg=_zbg, bd=_zbd, z=_zname, wr=_zwr,
                                    n=len(_zdf), pnl=_zpnl),
                    unsafe_allow_html=True,
                )

        with _mem_col2:
            st.markdown("**🕯️ Candle patterns found in your notes:**")
            if _pat_memory:
                for _pn, _pv in sorted(_pat_memory.items(),
                                        key=lambda x: x[1]["pnl"], reverse=True):
                    _pw  = _pv["wins"]; _pl = _pv["losses"]
                    _pwr = round(_pw/(_pw+_pl)*100, 0) if (_pw+_pl) > 0 else 0
                    _ppnl = _pv["pnl"]
                    _pbg = "#052e16" if _pwr>=60 else ("#422006" if _pwr>=40 else "#450a0a")
                    _pbd = "#16a34a" if _pwr>=60 else ("#d97706" if _pwr>=40 else "#dc2626")
                    st.markdown(
                        "<div style='background:{bg};border:1px solid {bd};border-radius:7px;"
                        "padding:8px 12px;margin-bottom:6px;display:flex;justify-content:space-between;"
                        "align-items:center'>"
                        "<span style='font-size:13px;color:#e2e8f0'>{pn}</span>"
                        "<span style='font-size:13px;font-weight:700;color:{bd}'>"
                        "{wr:.0f}% WR · Rs {ppnl:,.0f}</span>"
                        "</div>".format(bg=_pbg, bd=_pbd, pn=_pn.title(),
                                        wr=_pwr, ppnl=_ppnl),
                        unsafe_allow_html=True,
                    )
            else:
                st.info(
                    "No candle patterns found in your trade notes yet. "
                    "When you log a trade, mention the candle pattern in Notes "
                    "(e.g. 'bearish engulfing' or 'hammer') and your partner will track it."
                )

        # ── Yesterday's summary / tomorrow's brief ────────────────────────────
        _today_str = datetime.now(IST).strftime("%Y-%m-%d")
        _yest_str  = (datetime.now(IST) - timedelta(days=1)).strftime("%Y-%m-%d")

        _today_trades = _pt_closed[_pt_closed["Date"].astype(str).str[:10] == _today_str]
        _yest_trades  = _pt_closed[_pt_closed["Date"].astype(str).str[:10] == _yest_str]

        if not _today_trades.empty:
            _td_pnl = pd.to_numeric(_today_trades["Net P&L"], errors="coerce").sum()
            _td_wr  = round((_today_trades["Result"]=="WIN").sum() / len(_today_trades) * 100, 0)
            st.markdown("---")
            _td_col = "#4ade80" if _td_pnl >= 0 else "#f87171"
            st.markdown(
                "<div style='background:#0f172a;border:2px solid {c};border-radius:10px;"
                "padding:14px 18px;margin-bottom:10px'>"
                "<b style='color:{c}'>📅 TODAY'S SESSION SO FAR</b><br>"
                "<span style='font-size:13px;color:#e2e8f0'>"
                "{n} trade(s) · {wr:.0f}% win rate · Net P&L: "
                "<b style='color:{c}'>Rs {pnl:,.0f}</b></span>"
                "</div>".format(c=_td_col, n=len(_today_trades), wr=_td_wr, pnl=_td_pnl),
                unsafe_allow_html=True,
            )

        if not _yest_trades.empty:
            _yd_pnl  = pd.to_numeric(_yest_trades["Net P&L"], errors="coerce").sum()
            _yd_wr   = round((_yest_trades["Result"]=="WIN").sum() / len(_yest_trades) * 100, 0)
            _yd_pats = []
            for _, _yr in _yest_trades.iterrows():
                _ynt = (str(_yr.get("Notes","")) + " " + str(_yr.get("Lessons Learned",""))).strip()
                if _ynt and _ynt != "nan nan": _yd_pats.append(_ynt[:80])
            _yd_pat_str = " | ".join(_yd_pats[:3]) if _yd_pats else "No notes logged for yesterday"
            _yd_col = "#4ade80" if _yd_pnl >= 0 else "#f87171"
            st.markdown(
                "<div style='background:#0f172a;border:1px solid #334155;border-radius:10px;"
                "padding:14px 18px;margin-bottom:10px'>"
                "<b style='color:#94a3b8'>📖 YESTERDAY'S DEBRIEF</b><br>"
                "<span style='font-size:13px;color:#e2e8f0'>"
                "{n} trade(s) · {wr:.0f}% WR · P&L: "
                "<b style='color:{c}'>Rs {pnl:,.0f}</b></span><br>"
                "<span style='font-size:12px;color:#64748b;margin-top:4px;display:block'>"
                "What happened: {pats}</span>"
                "</div>".format(c=_yd_col, n=len(_yest_trades),
                                wr=_yd_wr, pnl=_yd_pnl, pats=_yd_pat_str),
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION D: PARTNER CHAT — Gemini with full live + memory context
    # ─────────────────────────────────────────────────────────────────────────
    st.subheader("💬 Talk to Your Trading Partner")
    st.caption(
        "Your partner knows: today's live signal · your candle right now · "
        "your last 20 trades · your psychology · every pattern we've traded together."
    )

    # Build the live candle description for the prompt
    _live_candle_ctx = "Live data unavailable."
    if _has_live:
        _last_candle = _pt_df.iloc[-1]
        _prev_candle = _pt_df.iloc[-2] if len(_pt_df) >= 2 else _pt_df.iloc[-1]
        _body_pct = abs(float(_last_candle["Close"]) - float(_last_candle["Open"])) / float(_last_candle["Open"]) * 100
        _c_dir = "GREEN (bullish)" if float(_last_candle["Close"]) >= float(_last_candle["Open"]) else "RED (bearish)"
        _live_candle_ctx = (
            "Symbol: {sym} | Interval: {ivl} | LTP: Rs {ltp:,.2f}\n"
            "Current candle: {cdir} | Body: {bp:.2f}% | RSI: {rsi:.1f} | ADX: {adx:.1f}\n"
            "Supertrend: {st} | EMA Cross: {ec} | VWAP: Rs {vwap:,.2f} | "
            "Price vs VWAP: {pvwap}\n"
            "MACD: {macd:.2f} vs Signal: {msig:.2f} (histogram: {mhist:.2f})\n"
            "ATR: {atr:.2f} | CMF: {cmf:.3f}\n"
            "Candle pattern: {pat}\n"
            "Signal engine says: {dirn} (bull votes: {bv}, bear votes: {brv})\n"
            "Entry time suggestion: {et} | Time window: {tw}\n"
            "Day verdict: {verdict}"
        ).format(
            sym=symbol, ivl=interval, ltp=_ltp,
            cdir=_c_dir, bp=_body_pct,
            rsi=_pt_s["rsi"], adx=_pt_s["adx"],
            st=_pt_s["supertrend"], ec=_pt_s["ema_cross"],
            vwap=_pt_s["vwap"],
            pvwap="ABOVE (bullish)" if _ltp > _pt_s["vwap"] else "BELOW (bearish)",
            macd=_pt_s["macd"], msig=_pt_s["macd_signal"],
            mhist=round(_pt_s["macd"]-_pt_s["macd_signal"], 3),
            atr=_atr, cmf=_pt_s["cmf"],
            pat=_top_pat["name"] + " (" + _top_pat["signal"] + ")" if _top_pat else "No clear pattern",
            dirn=_dirn, bv=_pt_ps.get("bull_votes",0), brv=_pt_ps.get("bear_votes",0),
            et=_pt_ps.get("entry_time","—"), tw=_pt_v["tw"]["label"],
            verdict=_pt_v["verdict"],
        )

    # Build pattern memory context for prompt
    _pat_mem_ctx = "No pattern memory yet (no trades logged)."
    if not _pt_closed.empty:
        _pm_lines = []
        # RSI zone win rates
        for _zn, _zdf2 in _rsi_zones.items() if '_rsi_zones' in dir() else []:
            if not _zdf2.empty:
                _zw2  = (_zdf2["Result"]=="WIN").sum()
                _zwr2 = round(_zw2/len(_zdf2)*100, 0)
                _zpnl2= pd.to_numeric(_zdf2["Net P&L"], errors="coerce").sum()
                _pm_lines.append("RSI {z}: {wr:.0f}% WR, {n} trades, Rs {pnl:,.0f}".format(
                    z=_zn, wr=_zwr2, n=len(_zdf2), pnl=_zpnl2))
        # Candle pattern memory
        if '_pat_memory' in dir() and _pat_memory:
            for _pn2, _pv2 in _pat_memory.items():
                _pw2 = _pv2["wins"]; _pl2 = _pv2["losses"]
                _pwr2= round(_pw2/(_pw2+_pl2)*100,0) if (_pw2+_pl2)>0 else 0
                _pm_lines.append("{}: {:.0f}% WR, Rs {:.0f} total P&L".format(
                    _pn2.title(), _pwr2, _pv2["pnl"]))
        _pat_mem_ctx = "\n".join(_pm_lines) if _pm_lines else "Pattern data building up — keep logging trades."

    # Build psychology context
    _psych_ctx = "Psychology: {} | Note: {}".format(
        st.session_state.get("partner_mood","Not provided"),
        st.session_state.get("partner_psych_note","Nothing noted"),
    )

    # Build last 15 trades for context
    _pt_trade_rows = "No closed trades yet."
    if not _pt_closed.empty:
        _pt_last15 = _pt_closed.tail(15)
        _pt_rows_list = []
        for _, _r in _pt_last15.iterrows():
            _pt_rows_list.append(
                "#{tn} {dt} | {ot} strike {st} | entry {ep} | exit {ex} | "
                "RSI {rsi} | ADX {adx} | ST {spd} | {res} | Rs {pnl} | "
                "candle/notes: {nt}".format(
                    tn=_r.get("Trade #","?"), dt=str(_r.get("Date",""))[:10],
                    ot=_r.get("Option Type","?"), st=_r.get("Strike","?"),
                    ep=_r.get("Entry Price","?"), ex=_r.get("Exit Price","?"),
                    rsi=_r.get("Entry RSI","?"), adx=_r.get("Entry ADX","?"),
                    spd=_r.get("Supertrend","?"), res=_r.get("Result","?"),
                    pnl=_r.get("Net P&L","?"),
                    nt=(str(_r.get("Notes",""))+" "+str(_r.get("Lessons Learned",""))).strip()[:60] or "none",
                )
            )
        _pt_trade_rows = "\n".join(_pt_rows_list)

    _partner_prompt = (
        "You are Raja's personal Nifty F&O trading PARTNER — not a coach, not an advisor. "
        "You have been trading Nifty options together every day. "
        "You know every trade he made, every mistake, every win, his psychology right now, "
        "and you are looking at the same live charts he is.\n\n"

        "HOW YOU RESPOND:\n"
        "- Talk like a trading partner: 'We', 'Let's', 'I think', 'Last time we saw this...'\n"
        "- Give specific actions: 'Enter 24350 PE now', 'Exit at 24200', 'SL at 24420'\n"
        "- Reference past trade data: 'Last time Supertrend flipped BEARISH + RSI was 63, we made Rs 1800'\n"
        "- Address his psychology: if he is anxious/overexcited, tell him to reduce size or skip\n"
        "- Learn out loud: 'Based on our data, bearish engulfing on BEARISH Supertrend has 70% WR for us'\n"
        "- Never be generic. Every sentence must be specific to his data or the live chart\n"
        "- If he asks 'should I trade now' — give a YES/NO with exact entry/exit levels or exact reason to wait\n\n"

        "=== LIVE CHART RIGHT NOW ===\n{live}\n\n"
        "=== HIS PSYCHOLOGY RIGHT NOW ===\n{psych}\n\n"
        "=== WHAT WE LEARNED FROM OUR TRADE HISTORY ===\n{mem}\n\n"
        "=== OUR LAST 15 TRADES ===\n{trades}\n\n"
        "=== OVERALL STATS ===\n"
        "Total trades: {total} | Win rate: {wr}% | Net P&L: Rs {pnl:,.0f} | "
        "Avg win: Rs {aw:,.0f} | Avg loss: Rs {al:,.0f} | R:R ratio: {rr}\n\n"
        "Always end your response with one of:\n"
        "✅ ACTION: [exact trade call] or ⏳ WAIT: [exact condition to watch for]"
    ).format(
        live=_live_candle_ctx,
        psych=_psych_ctx,
        mem=_pat_mem_ctx,
        trades=_pt_trade_rows,
        total=stats["total_trades"],
        wr=stats["win_rate"],
        pnl=stats["total_pnl"],
        aw=stats["avg_win"],
        al=stats["avg_loss"],
        rr=stats["reward_risk"],
    )

    # ── Quick action buttons ──────────────────────────────────────────────────
    st.markdown("**⚡ Quick — ask your partner:**")
    _qa_cols = st.columns(3)
    _quick_qs = [
        "Should we trade right now?",
        "What does this candle mean for us?",
        "What did we learn from yesterday?",
        "I'm feeling nervous — should I still trade?",
        "What's our best setup based on our history?",
        "Give me exact entry, target, SL for now",
    ]
    for _qi, _qq in enumerate(_quick_qs):
        if _qa_cols[_qi % 3].button(_qq, key="pq_{}".format(_qi), use_container_width=True):
            st.session_state.setdefault("partner_messages", [])
            st.session_state["partner_messages"].append({"role": "user", "content": _qq})
            st.rerun()

    st.markdown("---")

    # ── Partner chat history ──────────────────────────────────────────────────
    if "partner_messages" not in st.session_state:
        st.session_state["partner_messages"] = []

    for _pm in st.session_state["partner_messages"]:
        with st.chat_message(_pm["role"],
                             avatar="🧑" if _pm["role"]=="user" else "🤝"):
            st.markdown(_pm["content"])

    # ── Chat input ────────────────────────────────────────────────────────────
    _partner_input = st.chat_input("Talk to your trading partner…")

    if _partner_input:
        st.session_state["partner_messages"].append({"role": "user", "content": _partner_input})
        with st.chat_message("user", avatar="🧑"):
            st.markdown(_partner_input)

        with st.chat_message("assistant", avatar="🤝"):
            with st.spinner("Partner is reading the charts…"):
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=_pk)

                    _sup_models = []
                    try:
                        for _mm in genai.list_models():
                            if "generateContent" in getattr(_mm, "supported_generation_methods", []):
                                _sup_models.append(_mm.name)
                    except Exception:
                        pass
                    _cands = _sup_models or [
                        "gemini-2.5-flash", "gemini-1.5-flash",
                        "gemini-1.5-pro",   "gemini-pro",
                    ]
                    _cands.sort(key=lambda n: (0 if "flash" in n.lower() else 1))

                    _hist_api = []
                    for _hm in st.session_state["partner_messages"][:-1][-8:]:
                        _hist_api.append({
                            "role": "user" if _hm["role"]=="user" else "model",
                            "parts": [_hm["content"]],
                        })

                    _preply = None; _perr = ""
                    for _mn in _cands:
                        try:
                            _mdl = genai.GenerativeModel(
                                model_name=_mn.replace("models/",""),
                                system_instruction=_partner_prompt,
                            )
                            _ch = _mdl.start_chat(history=_hist_api)
                            _preply = _ch.send_message(_partner_input).text
                            break
                        except Exception as _me2:
                            _perr = str(_me2); continue

                    if _preply is None:
                        _preply = "⚠️ Partner unavailable right now: {}. Try again in a moment.".format(_perr)
                except Exception as _pe:
                    _preply = "⚠️ Error: {}".format(str(_pe))
                st.markdown(_preply)
        st.session_state["partner_messages"].append({"role": "assistant", "content": _preply})

    if st.session_state.get("partner_messages"):
        if st.button("🗑️ New conversation", key="clear_partner"):
            st.session_state["partner_messages"] = []
            st.rerun()

    st.markdown("---")
    st.caption(
        "🤝 Trading Partner AI uses live Nifty data + your personal trade history. "
        "All trade calls are for educational analysis only. Not SEBI-registered financial advice. "
        "Always use your own judgement and set stop-losses before entering any trade."
    )


# ── Global footer ─────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("📈 Nifty F&O Unified Dashboard | Cloud Edition | Educational use only — NOT financial advice")
