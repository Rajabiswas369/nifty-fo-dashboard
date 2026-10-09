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
    st.caption("Powered by Google Gemini (free) · Discuss your trades, get step-by-step guidance, ask anything about F&O.")
    st.markdown("---")

    # ── API key setup ────────────────────────────────────────────────────────
    try:
        gemini_key = st.secrets.get("gemini_api_key", "")
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

    # ── Build live context from dashboard data ────────────────────────────────
    _today_ctx = datetime.now(IST).strftime("%A, %d %b %Y %I:%M %p IST")
    _vd = build_day_verdict("")
    _trade_stats = stats  # already computed at top of file

    SYSTEM_PROMPT = """You are an expert Nifty F&O (Futures & Options) trading coach for Indian markets.
You help retail traders understand NSE options strategies, risk management, trade setups, and discipline.
You are friendly, practical, and never recommend specific buy/sell calls — instead you teach the process.

Always remind the trader that F&O trading carries high risk and can result in loss of capital.
Never provide specific financial advice; focus on education, discipline, and process.

Current live context from the trader's dashboard:
- Date/Time: {dt}
- Day Verdict: {verdict} ({vdetail})
- Today's Checks: {passn} passed, {warnn} cautions, {failn} failed
- Total Trades Logged: {total_trades}
- Win Rate: {win_rate}%
- Total Net P&L: Rs {total_pnl:,.0f}
- Best Trade: Rs {best:,.0f} | Worst Trade: Rs {worst:,.0f}
- Avg Win: Rs {avg_win:,.0f} | Avg Loss: Rs {avg_loss:,.0f}
- Reward:Risk Ratio: {rr}
- Max Drawdown: Rs {mdd:,.0f}
- Total Charges Paid: Rs {charges:,.0f}

Use this context to give personalised, actionable guidance.
When the trader asks "should I trade today?" use the Day Verdict to explain.
When they ask about their stats, reference the numbers above.
Keep responses concise — under 300 words unless a detailed explanation is requested.
""".format(
        dt=_today_ctx,
        verdict=_vd["verdict"],
        vdetail=_vd["verdict_detail"],
        passn=_vd["pass_count"],
        warnn=_vd["warn_count"],
        failn=_vd["fail_count"],
        total_trades=_trade_stats["total_trades"],
        win_rate=_trade_stats["win_rate"],
        total_pnl=_trade_stats["total_pnl"],
        best=_trade_stats["best_trade"],
        worst=_trade_stats["worst_trade"],
        avg_win=_trade_stats["avg_win"],
        avg_loss=_trade_stats["avg_loss"],
        rr=_trade_stats["reward_risk"],
        mdd=_trade_stats["max_drawdown"],
        charges=_trade_stats["total_charges"],
    )

    # ── Suggested starter questions ───────────────────────────────────────────
    st.markdown("**💡 Try asking:**")
    q_cols = st.columns(3)
    starter_qs = [
        "Should I trade today?",
        "What's wrong with my win rate?",
        "How do I set my stop-loss for NIFTY options?",
        "Explain ATM vs OTM options",
        "How do I manage a losing streak?",
        "What is the 9-gate entry checklist?",
    ]
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


# ── Global footer ─────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("📈 Nifty F&O Unified Dashboard | Cloud Edition | Educational use only — NOT financial advice")
