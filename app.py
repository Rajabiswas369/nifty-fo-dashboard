"""
Nifty F&O Unified Cloud Dashboard & Trading Journal
====================================================
All-in-one Streamlit Cloud App:
  📈 Live Signal Dashboard    — RSI, ADX, Supertrend, MACD, VWAP, trade decision, interactive charts
  📰 Market News & Verdict    — Should I trade today? 9-Gate checks + live headlines + events calendar
  📊 My Records Dashboard     — Capital growth, win/loss stats, equity curve
  💰 My Capital               — Capital tracker, reset starting balance, deposits, withdrawals
  📓 Log Trade                — Manual trade entry + live journal table + instant delete option
  🔄 Angel One Sync           — Auto-fetch executed trades from Angel One
  📋 All Trades               — View, filter, and inspect all trades
  📅 Monthly Report           — Monthly P&L calendar & breakdowns
  📈 Performance              — Win rate by symbol, option type, RSI zone
  💸 Expenses                 — Brokerage, STT, and charges breakdown
  ⬇️ Export                   — Download Excel & CSV reports

Data stored permanently in Supabase Cloud.
"""

import os
import json
import traceback
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

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Nifty F&O All-in-One Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═════════════════════════════════════════════════════════════════════════════
# CONSTANTS & CONFIG
# ═════════════════════════════════════════════════════════════════════════════
COLUMNS = [
    "Trade #", "Date", "Time", "Symbol", "Option Type", "Strike", "Expiry",
    "Entry Price", "Exit Price", "Lots", "Lot Size", "Capital Used",
    "Gross P&L", "Brokerage", "STT", "Other Charges", "Net P&L", "Result",
    "Hold Time", "Entry RSI", "Entry ADX", "Supertrend", "Dashboard Said",
    "Lessons Learned", "Notes",
]
DEFAULT_BROKERAGE = 40.0
DEFAULT_STT_PCT   = 0.05
DEFAULT_OTHER     = 15.0

COL_TO_DB = {
    "Trade #":        "trade_num",
    "Date":           "date",
    "Time":           "time",
    "Symbol":         "symbol",
    "Option Type":    "option_type",
    "Strike":         "strike",
    "Expiry":         "expiry",
    "Entry Price":    "entry_price",
    "Exit Price":     "exit_price",
    "Lots":           "lots",
    "Lot Size":       "lot_size",
    "Capital Used":   "capital_used",
    "Gross P&L":      "gross_pnl",
    "Brokerage":      "brokerage",
    "STT":            "stt",
    "Other Charges":  "other_charges",
    "Net P&L":        "net_pnl",
    "Result":         "result",
    "Hold Time":      "hold_time",
    "Entry RSI":      "entry_rsi",
    "Entry ADX":      "entry_adx",
    "Supertrend":     "supertrend",
    "Dashboard Said": "dashboard_said",
    "Lessons Learned":"lessons_learned",
    "Notes":          "notes",
}
DB_TO_COL = {v: k for k, v in COL_TO_DB.items()}

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
# SUPABASE HELPERS
# ═════════════════════════════════════════════════════════════════════════════
def _is_cloud() -> bool:
    try:
        return "supabase_url" in st.secrets and "supabase_key" in st.secrets
    except Exception:
        return False


def _get_client():
    from supabase import create_client
    return create_client(st.secrets["supabase_url"], st.secrets["supabase_key"])


@st.cache_data(ttl=10, show_spinner=False)
def load_trades() -> pd.DataFrame:
    if not _is_cloud():
        if "trades_df" not in st.session_state:
            st.session_state.trades_df = pd.DataFrame(columns=COLUMNS)
        return st.session_state.trades_df.copy()
    try:
        client = _get_client()
        resp   = client.table("trades").select("*").order("trade_num").execute()
        data   = resp.data
        if not data:
            return pd.DataFrame(columns=COLUMNS)
        df = pd.DataFrame(data).rename(columns=DB_TO_COL)
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df[COLUMNS]
    except Exception as e:
        st.warning("Could not load trades: {}".format(e))
        return pd.DataFrame(columns=COLUMNS)


@st.cache_data(ttl=10, show_spinner=False)
def load_capital() -> dict:
    default = {
        "initial_capital": 40000.0, "current_capital": 40000.0,
        "start_date": "2025-01-01", "notes": "Started trading Nifty F&O",
        "history": [{"date": "2025-01-01", "balance": 40000.0, "note": "Initial capital"}],
    }
    if not _is_cloud():
        return st.session_state.get("capital_data", default)
    try:
        client = _get_client()
        resp   = client.table("capital").select("*").order("date").execute()
        data   = resp.data
        if not data:
            return default
        history = [{"date": r.get("date", ""), "balance": float(r.get("balance", 40000)),
                    "note": r.get("note", "")} for r in data]
        initial = float(data[0].get("balance", 40000.0))
        current = float(data[-1].get("balance", 40000.0))
        return {
            "initial_capital": initial,
            "current_capital": current,
            "start_date":      data[0].get("date", "2025-01-01"),
            "notes":           data[-1].get("note", ""),
            "history":         history,
        }
    except Exception as e:
        return default


def save_trades(df: pd.DataFrame):
    load_trades.clear()
    if not _is_cloud():
        st.session_state.trades_df = df.copy()
        return
    client = _get_client()
    try:
        client.table("trades").delete().gte("trade_num", 0).execute()
        if not df.empty:
            rows = df.copy().rename(columns=COL_TO_DB)
            db_cols = list(COL_TO_DB.values())
            rows = rows[[c for c in db_cols if c in rows.columns]]
            num_cols = ["trade_num", "strike", "entry_price", "exit_price",
                        "lots", "lot_size", "capital_used", "gross_pnl",
                        "brokerage", "stt", "other_charges", "net_pnl",
                        "entry_rsi", "entry_adx"]
            for col in num_cols:
                if col in rows.columns:
                    rows[col] = pd.to_numeric(rows[col], errors="coerce")
            rows = rows.where(pd.notnull(rows), None)
            recs = rows.to_dict("records")
            for r in recs:
                client.table("trades").insert(r).execute()
    except Exception as e:
        st.error("❌ Supabase write failed: {}".format(e))


def save_capital(data: dict):
    load_capital.clear()
    if not _is_cloud():
        st.session_state.capital_data = data
        return
    client = _get_client()
    try:
        client.table("capital").delete().neq("date", "1900-01-01").execute()
        history = data.get("history", [])
        if not history:
            history = [{"date": data.get("start_date", "2025-01-01"),
                        "balance": data.get("initial_capital", 40000.0),
                        "note": "Initial capital"}]
        recs = [{"date": str(h.get("date", "")), "balance": float(h.get("balance", 40000.0)),
                 "note": str(h.get("note", ""))} for h in history]
        if recs:
            client.table("capital").insert(recs).execute()
    except Exception as e:
        st.error("❌ Supabase capital write failed: {}".format(e))


def get_stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {k: 0 for k in ["total_trades", "wins", "losses", "win_rate", "total_pnl",
                               "avg_win", "avg_loss", "best_trade", "worst_trade", "reward_risk"]}
    closed = df[df["Result"].isin(["WIN", "LOSS"])].copy()
    if closed.empty:
        return {k: 0 for k in ["total_trades", "wins", "losses", "win_rate", "total_pnl",
                               "avg_win", "avg_loss", "best_trade", "worst_trade", "reward_risk"]}
    pnl = pd.to_numeric(closed["Net P&L"], errors="coerce").fillna(0)
    w   = pnl[pnl > 0]
    l   = pnl[pnl < 0]
    wins = len(w); losses = len(l)
    avg_w = float(w.mean()) if wins else 0.0
    avg_l = float(l.mean()) if losses else 0.0
    rr    = round(abs(avg_w / avg_l), 2) if avg_l != 0 else 0.0
    return {
        "total_trades": len(closed),
        "wins":         wins,
        "losses":       losses,
        "win_rate":     round(wins / len(closed) * 100, 1) if len(closed) else 0.0,
        "total_pnl":    round(float(pnl.sum()), 2),
        "avg_win":      round(avg_w, 2),
        "avg_loss":     round(avg_l, 2),
        "best_trade":   round(float(pnl.max()), 2) if len(pnl) else 0.0,
        "worst_trade":  round(float(pnl.min()), 2) if len(pnl) else 0.0,
        "reward_risk":  rr,
    }


def get_capital_stats(data: dict) -> dict:
    initial = float(data.get("initial_capital", 40000.0))
    current = float(data.get("current_capital", 40000.0))
    pnl     = round(current - initial, 2)
    pct     = round((pnl / initial) * 100, 2) if initial else 0.0
    try:
        d0   = datetime.strptime(str(data.get("start_date", "2025-01-01")), "%Y-%m-%d").date()
        days = max((datetime.now().date() - d0).days, 0)
    except Exception:
        days = 0
    return {"initial": initial, "current": current, "pnl": pnl, "pnl_pct": pct,
            "days": days, "history": data.get("history", [])}


def pnl_delta(val):
    d  = ("▲ Rs {:,.0f}".format(val) if val >= 0 else "▼ Rs {:,.0f}".format(abs(val)))
    dc = "normal" if val >= 0 else "inverse"
    return d, dc


from angel_sync import render_angel_sync_panel, is_angel_configured

# ═════════════════════════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION
# ═════════════════════════════════════════════════════════════════════════════
st.sidebar.image("https://img.icons8.com/color/96/combo-chart.png", width=56)
st.sidebar.title("Nifty F&O AI Trader")
st.sidebar.markdown("---")

if _is_cloud():
    st.sidebar.success("☁️ Storage: **Supabase Cloud (Live)**")
else:
    st.sidebar.warning("💻 Running locally — memory only")

angel_ok = is_angel_configured()
if angel_ok:
    st.sidebar.success("✅ Angel One **Configured**")
else:
    st.sidebar.info("ℹ️ Angel One not configured")

st.sidebar.markdown("---")

page = st.sidebar.radio(
    "📂 Navigate",
    [
        "📈 Signal Dashboard",
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
    ],
    index=0,
)
st.sidebar.markdown("---")

# Controls for Signal Dashboard
if page in ("📈 Signal Dashboard", "📰 Market News & Verdict"):
    symbol   = st.sidebar.selectbox("Symbol", list(NSE_SYMBOLS.keys()), index=0)
    interval = st.sidebar.selectbox("Timeframe", ["1d", "1h", "15m", "5m"], index=0)
    period_map = {"1d": ["6mo", "1y", "2y", "5y"], "1h": ["1mo", "3mo", "6mo"],
                  "15m": ["5d", "1mo", "2mo"], "5m": ["5d", "1mo"]}
    period = st.sidebar.selectbox("Period", period_map[interval], index=1)
    show_supertrend = st.sidebar.checkbox("Show Supertrend",      value=True)
    show_bb         = st.sidebar.checkbox("Show Bollinger Bands", value=True)
    show_adx        = st.sidebar.checkbox("Show ADX Panel",       value=True)
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
else:
    symbol = "NIFTY50"; interval = "1d"; period = "1y"
    total_capital = 50000; risk_per_trade = 2; lot_size = 75
    watchlist = []; manual_event = ""; refresh = False

# ── Load persistent data ───────────────────────────────────────────────────────
trades_df = load_trades()
cap_data  = load_capital()
stats     = get_stats(trades_df)
cap_stats = get_capital_stats(cap_data)
closed_df = trades_df[trades_df["Result"].isin(["WIN", "LOSS"])].copy() if not trades_df.empty else pd.DataFrame()


# ═════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
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
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]

    df["EMA_9"]   = _ta.trend.EMAIndicator(close, 9).ema_indicator()
    df["EMA_21"]  = _ta.trend.EMAIndicator(close, 21).ema_indicator()
    df["EMA_50"]  = _ta.trend.EMAIndicator(close, 50).ema_indicator()
    df["EMA_200"] = _ta.trend.EMAIndicator(close, 200).ema_indicator()

    macd = _ta.trend.MACD(close, 26, 12, 9)
    df["MACD"] = macd.macd(); df["MACD_signal"] = macd.macd_signal(); df["MACD_hist"] = macd.macd_diff()

    adx = _ta.trend.ADXIndicator(high, low, close, 14)
    df["ADX"] = adx.adx(); df["ADX_pos"] = adx.adx_pos(); df["ADX_neg"] = adx.adx_neg()

    df = _supertrend(df)

    df["RSI"] = _ta.momentum.RSIIndicator(close, 14).rsi()

    bb = _ta.volatility.BollingerBands(close, 20, 2)
    df["BB_upper"] = bb.bollinger_hband(); df["BB_lower"] = bb.bollinger_lband()
    df["BB_pct"]   = bb.bollinger_pband()
    df["ATR"] = _ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range()

    df["VWAP"] = _ta.volume.VolumeWeightedAveragePrice(high, low, close, vol).volume_weighted_average_price()
    df["CMF"]  = _ta.volume.ChaikinMoneyFlowIndicator(high, low, close, vol, 20).chaikin_money_flow()

    df["EMA_cross"]  = np.where(df["EMA_9"] > df["EMA_21"], 1, -1)
    df["MACD_cross"] = np.where(df["MACD"]  > df["MACD_signal"], 1, -1)
    df["RSI_zone"]   = pd.cut(df["RSI"], bins=[0, 30, 50, 70, 100],
                               labels=["Oversold", "Bearish", "Bullish", "Overbought"])
    df.dropna(inplace=True)
    return df


def get_summary(df: pd.DataFrame) -> dict:
    last = df.iloc[-1]
    return {
        "close":       round(float(last["Close"]),       2),
        "rsi":         round(float(last["RSI"]),         2),
        "macd":        round(float(last["MACD"]),        2),
        "macd_signal": round(float(last["MACD_signal"]), 2),
        "adx":         round(float(last["ADX"]),         2),
        "atr":         round(float(last["ATR"]),         2),
        "bb_pct":      round(float(last["BB_pct"]),      2),
        "supertrend":  "BULLISH" if last["ST_trend"] == 1 else "BEARISH",
        "ema_cross":   "BULLISH" if last["EMA_cross"] == 1 else "BEARISH",
        "rsi_zone":    str(last["RSI_zone"]),
        "vwap":        round(float(last["VWAP"]),  2),
        "cmf":         round(float(last["CMF"]),   4),
    }


@st.cache_data(ttl=300)
def load_chart_data(sym, ivl, per):
    import yfinance as yf
    ticker = NSE_SYMBOLS.get(sym, sym)
    df = yf.download(ticker, period=per, interval=ivl, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError("No data for {}".format(sym))
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    df.sort_index(inplace=True)
    df.dropna(inplace=True)
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
# DAY VERDICT & MARKET NEWS
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


@st.cache_data(ttl=600)
def fetch_nifty_gap() -> dict:
    try:
        import yfinance as yf
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
                "▲" if gap_data["direction"] == "UP" else "▼", gabs, abs(gap_data["gap_pct"]),
                "Normal." if gabs <= 150 else "LARGE GAP — wait for gap-fill first.")
            checks.append((icon, "Nifty Gap", txt, True if gabs <= 150 else None))
        else:
            checks.append(("ℹ️", "Nifty Gap", "Gap data unavailable — check manually.", None))

        if weekday == 3:
            checks.append(("⚠️", "Weekly Expiry", "Thursday expiry — volatile after 1 PM. Exit by 1 PM if in profit.", None))
        else:
            checks.append(("✅", "Weekly Expiry", "Expiry in {} day(s). No pressure today.".format((3 - weekday) % 7), True))

    fail  = sum(1 for _, _, _, p in checks if p is False)
    warn  = sum(1 for _, _, _, p in checks if p is None)
    passn = sum(1 for _, _, _, p in checks if p is True)

    if market_status in ("HOLIDAY", "WEEKEND"):
        v, vi, vbg, vbd, vc = "NSE CLOSED TODAY", "🚫", "#fef2f2", "#fca5a5", "#991b1b"
        vd = "Market closed. Come back on next trading day."
    elif has_extreme:
        v, vi, vbg, vbd, vc = "NO TRADE — EXTREME EVENT", "🚫", "#fef2f2", "#fca5a5", "#991b1b"
        vd = "High-impact event today. Signals unreliable. Sit out."
    elif tw["status"] in ("closed", "avoid"):
        v, vi, vbg, vbd, vc = "NOT YET / MARKET CLOSED", "⏳", "#fffbeb", "#fcd34d", "#92400e"
        vd = tw["note"]
    elif fail == 0 and warn <= 1:
        v, vi, vbg, vbd, vc = "GREEN LIGHT — OK TO TRADE", "🟢", "#f0fdf4", "#86efac", "#14532d"
        vd = "All checks passed. Use 9-Gate entry checklist before any trade."
    elif fail == 0 and warn >= 2:
        v, vi, vbg, vbd, vc = "CAUTION — TRADE CAREFULLY", "🟡", "#fffbeb", "#fcd34d", "#78350f"
        vd = "Multiple caution flags. Trade half lot size. Strict 9 Gates."
    else:
        v, vi, vbg, vbd, vc = "NO TRADE TODAY", "🔴", "#fef2f2", "#fca5a5", "#991b1b"
        vd = "Hard stops triggered. Risk > reward today. Sit out."

    return dict(verdict=v, verdict_icon=vi, verdict_bg=vbg, verdict_border=vbd,
                verdict_color=vc, verdict_detail=vd, checks=checks,
                market_status=market_status, has_extreme_event=has_extreme, tw=tw,
                holiday_name=holiday_name, now_ist=now_ist, day_name=day_name,
                day_status=day_status, day_note=day_note, gap_data=gap_data,
                event_name=event_name, pass_count=passn, warn_count=warn, fail_count=fail)


@st.cache_data(ttl=900)
def fetch_market_news() -> list:
    feeds = [
        ("https://news.google.com/rss/search?q=nifty+RBI+sensex+india+market&hl=en-IN&gl=IN&ceid=IN:en", "Google News"),
        ("https://feeds.feedburner.com/ndtvprofit-latest-news", "NDTV Profit"),
    ]
    HIGH_KW = ["rbi", "rate", "repo", "fed", "fomc", "budget", "gdp", "cpi", "inflation",
               "election", "war", "crude", "rupee", "circuit", "crash", "rally", "fii",
               "ban", "sebi", "tax", "stt", "f&o", "expiry", "result", "earnings"]
    articles = []
    for url, src in feeds:
        try:
            resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
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
                    impact = "🔴 HIGH" if any(k in tl for k in ["rbi", "rate", "repo", "fed", "fomc", "budget", "circuit", "crash", "election", "war", "ban"]) else "🟡 MEDIUM"
                else:
                    impact = "⚪ LOW"
                articles.append({"title": title, "link": link, "published": pub[:25], "source": src,
                                 "impact": impact, "keywords": ", ".join(match[:4]) or "—"})
        except Exception:
            continue
    order = {"🔴 HIGH": 0, "🟡 MEDIUM": 1, "⚪ LOW": 2}
    articles.sort(key=lambda x: order.get(x["impact"], 3))
    return articles


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


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📈 SIGNAL DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if page == "📈 Signal Dashboard":
    if refresh:
        st.cache_data.clear()

    try:
        df_chart = load_chart_data(symbol, interval, period)
    except Exception as e:
        st.error("Failed to load chart data for {}: {}".format(symbol, e))
        st.stop()

    summary  = get_summary(df_chart)
    decision = compute_decision(summary)
    advice   = compute_strike_advice(summary["close"], summary["atr"],
                                     total_capital, risk_per_trade, lot_size)
    vdict    = build_day_verdict(manual_event)

    render_verdict_badge(vdict)

    st.title("📈 {} — {} Signal Dashboard".format(symbol, interval))
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    pc = df_chart["Close"].iloc[-1] - df_chart["Close"].iloc[-2]
    pp = (pc / df_chart["Close"].iloc[-2]) * 100
    c1.metric("LTP",        "Rs {:.2f}".format(summary["close"]),  "{} {:.2f}%".format("▲" if pc >= 0 else "▼", abs(pp)), delta_color="normal" if pc >= 0 else "inverse")
    c2.metric("RSI (14)",   "{:.1f}".format(summary["rsi"]),        summary["rsi_zone"])
    c3.metric("ADX",        "{:.1f}".format(summary["adx"]),        "Strong" if summary["adx"] > 25 else "Weak/Ranging")
    c4.metric("ATR",        "Rs {:.1f}".format(summary["atr"]),     "Volatility")
    c5.metric("Supertrend", summary["supertrend"])
    c6.metric("EMA Cross",  summary["ema_cross"])
    st.markdown("---")

    # Trade Decision Panel
    st.subheader("🎯 Trade Decision Panel")
    for w in decision["warnings"]:
        st.warning("⚠️  " + w)
    dc1, dc2, dc3 = st.columns([1, 2, 2])
    with dc1:
        dir_icon = {"PUT": "🔴", "CALL": "🟢", "WAIT": "🟡"}[decision["direction"]]
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
    oa1, oa2, oa3, oa4, oa5, oa6 = st.columns(6)
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

    # Main Chart
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.50, 0.17, 0.17, 0.16],
                        subplot_titles=("Price + Indicators", "RSI", "MACD", "Volume"))
    fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart["Open"], high=df_chart["High"],
                                  low=df_chart["Low"], close=df_chart["Close"], name="Price",
                                  increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), row=1, col=1)
    for ema, color in [("EMA_9", "#f39c12"), ("EMA_21", "#3498db"), ("EMA_50", "#9b59b6"), ("EMA_200", "#e74c3c")]:
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart[ema], name=ema,
                                 line=dict(color=color, width=1), opacity=0.8), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["VWAP"], name="VWAP",
                             line=dict(color="#ffffff", width=1.2, dash="dot"), opacity=0.6), row=1, col=1)
    if show_bb:
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["BB_upper"], name="BB Upper",
                                 line=dict(color="rgba(150,150,150,0.5)", width=1, dash="dot")), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["BB_lower"], name="BB Lower",
                                 line=dict(color="rgba(150,150,150,0.5)", width=1, dash="dot"),
                                 fill="tonexty", fillcolor="rgba(150,150,150,0.05)"), row=1, col=1)
    if show_supertrend:
        bull_st = df_chart[df_chart["ST_trend"] == 1]
        bear_st = df_chart[df_chart["ST_trend"] == -1]
        fig.add_trace(go.Scatter(x=bull_st.index, y=bull_st["ST_value"], mode="markers",
                                 marker=dict(color="#26a69a", size=4, symbol="triangle-up"), name="ST Bull"), row=1, col=1)
        fig.add_trace(go.Scatter(x=bear_st.index, y=bear_st["ST_value"], mode="markers",
                                 marker=dict(color="#ef5350", size=4, symbol="triangle-down"), name="ST Bear"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["RSI"], name="RSI",
                             line=dict(color="#3498db", width=1.5)), row=2, col=1)
    fig.add_hrect(y0=65, y1=100, fillcolor="rgba(239,83,80,0.08)", line_width=0, row=2, col=1)
    fig.add_hrect(y0=0, y1=35, fillcolor="rgba(38,166,154,0.08)", line_width=0, row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.4, row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.4, row=2, col=1)
    colors_hist = ["#26a69a" if v >= 0 else "#ef5350" for v in df_chart["MACD_hist"]]
    fig.add_trace(go.Bar(x=df_chart.index, y=df_chart["MACD_hist"], name="Histogram",
                         marker_color=colors_hist, opacity=0.7), row=3, col=1)
    fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["MACD"], name="MACD",
                             line=dict(color="#3498db", width=1.2)), row=3, col=1)
    fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["MACD_signal"], name="Signal",
                             line=dict(color="#f39c12", width=1.2)), row=3, col=1)
    vol_colors = ["#26a69a" if df_chart["Close"].iloc[i] >= df_chart["Open"].iloc[i] else "#ef5350"
                  for i in range(len(df_chart))]
    fig.add_trace(go.Bar(x=df_chart.index, y=df_chart["Volume"], name="Volume",
                         marker_color=vol_colors, opacity=0.7), row=4, col=1)
    fig.update_layout(height=780, template="plotly_dark", xaxis_rangeslider_visible=False,
                      showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, x=1),
                      margin=dict(l=0, r=0, t=30, b=0))
    fig.update_yaxes(title_text="Price (Rs)", row=1, col=1)
    fig.update_yaxes(title_text="RSI", row=2, col=1, range=[0, 100])
    fig.update_yaxes(title_text="MACD", row=3, col=1)
    fig.update_yaxes(title_text="Volume", row=4, col=1)
    st.plotly_chart(fig, use_container_width=True)
    st.markdown("---")

    # Watchlist
    if watchlist:
        st.subheader("📋 Watchlist Overview")
        rows = []
        for sym in watchlist:
            try:
                wdf = load_chart_data(sym, "1d", "1mo")
                s   = get_summary(wdf)
                dec = compute_decision(s)
                chg = wdf["Close"].iloc[-1] - wdf["Close"].iloc[-2]
                pct = (chg / wdf["Close"].iloc[-2]) * 100
                rsi_tag = ("🔴 {:.1f} OB".format(s["rsi"]) if s["rsi"] > 65 else
                            ("🟢 {:.1f} OS".format(s["rsi"]) if s["rsi"] < 35 else
                             ("🟢 {:.1f}".format(s["rsi"]) if s["rsi"] > 55 else
                              ("🔴 {:.1f}".format(s["rsi"]) if s["rsi"] < 45 else "🟡 {:.1f}".format(s["rsi"])))))
                rows.append({
                    "Symbol":    sym,
                    "LTP (Rs)":  "Rs {:.2f}".format(s["close"]),
                    "Change %":  "{} {:.2f}%".format("▲" if chg >= 0 else "▼", abs(pct)),
                    "RSI":       rsi_tag,
                    "ADX":       "{:.1f} {}".format(s["adx"], "Strong" if s["adx"] > 25 else "Weak"),
                    "Supertrend": s["supertrend"],
                    "MACD":      "Bullish" if s["macd"] > s["macd_signal"] else "Bearish",
                    "Signal":    {"PUT": "🔴 PUT", "CALL": "🟢 CALL", "WAIT": "🟡 WAIT"}[dec["direction"]],
                    "Confidence": "{:.0f}%".format(dec["confidence"] * 100),
                })
            except Exception:
                rows.append({"Symbol": sym, "LTP (Rs)": "Error", "Change %": "-", "RSI": "-",
                             "ADX": "-", "Supertrend": "-", "MACD": "-", "Signal": "-", "Confidence": "-"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.markdown("---")

    st.caption("Data via yfinance. Educational use only. NOT financial advice.")


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📰 MARKET NEWS & VERDICT
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📰 Market News & Verdict":
    vdict = build_day_verdict(manual_event)
    now_ist = vdict["now_ist"]; gap_data = vdict["gap_data"]; tw = vdict["tw"]; checks = vdict["checks"]
    vbg, vbd, vc, vi, v, vd = vdict["verdict_bg"], vdict["verdict_border"], vdict["verdict_color"], vdict["verdict_icon"], vdict["verdict"], vdict["verdict_detail"]
    p, w, f = vdict["pass_count"], vdict["warn_count"], vdict["fail_count"]

    st.title("📰 Market News & Trade Verdict")
    st.caption("Live headlines · Event calendar · Should I trade today?")
    st.markdown("<div style='background:{bg};border:2.5px solid {bd};border-radius:12px;"
                "padding:22px 28px;text-align:center;margin-bottom:20px'>"
                "<div style='font-size:44px;margin-bottom:6px'>{icon}</div>"
                "<div style='font-size:24px;font-weight:900;color:{col};margin-bottom:8px'>{v}</div>"
                "<div style='font-size:14px;color:#374151;line-height:1.8;max-width:560px;margin:0 auto'>{vd}</div>"
                "<div style='margin-top:14px;font-size:13px;color:#6b7280'>"
                "✅ {p} passed | ⚠️ {w} cautions | ❌ {f} failed | {ts}"
                "</div></div>".format(bg=vbg, bd=vbd, col=vc, icon=vi, v=v, vd=vd, p=p, w=w, f=f,
                                      ts=now_ist.strftime("%d %b %Y  %I:%M %p IST")),
                unsafe_allow_html=True)

    dc1, dc2, dc3, dc4 = st.columns(4)
    dc1.metric("📅 Date", now_ist.strftime("%d %b %Y"))
    dc2.metric("🗓️ Day",  vdict["day_name"])
    dc3.metric("🕐 IST",  now_ist.strftime("%I:%M %p"))
    dc4.metric("🏦 NSE",  "CLOSED" if vdict["market_status"] != "OPEN_DAY" else "OPEN",
               vdict["holiday_name"] or vdict["day_name"])
    st.markdown("---")

    left, right = st.columns(2)
    with left:
        st.subheader("🔍 Today's Checks")
        for icon, label, text, passed in checks:
            bg = "#dcfce7" if passed is True else ("#fee2e2" if passed is False else "#fef3c7")
            bd = "#86efac" if passed is True else ("#fca5a5" if passed is False else "#fcd34d")
            st.markdown("<div style='background:{bg};border:1px solid {bd};border-radius:7px;"
                        "padding:9px 13px;margin-bottom:8px;font-size:13px'>"
                        "<b>{icon} {label}</b><br><span style='color:#374151'>{text}</span></div>".format(
                            bg=bg, bd=bd, icon=icon, label=label, text=text), unsafe_allow_html=True)
    with right:
        st.subheader("⏱️ Time Window")
        tw_colors = {"best": "#dcfce7", "ok": "#dbeafe", "caution": "#fef3c7", "avoid": "#f3f4f6", "closed": "#f3f4f6"}
        html = "<div style='display:flex;gap:4px;flex-wrap:wrap;margin-bottom:12px'>"
        for trange, tlabel, tstatus in [("9:15–9:44", "Opening", "avoid"), ("9:45–10:29", "Early", "caution"),
                                          ("10:30–12:59", "Prime ✅", "best"), ("1:00–2:29", "Mid ✅", "ok"),
                                          ("2:30–3:14", "Late ⚠️", "caution"), ("3:15–3:30", "Close", "avoid")]:
            is_cur = any(x in tw["label"] for x in [trange.split("–")[0], tlabel.replace(" ✅", "").replace(" ⚠️", "")])
            bg = tw_colors.get(tstatus, "#f3f4f6")
            bdr = "2px solid #1d4ed8" if is_cur else "1px solid #e5e7eb"
            html += "<div style='background:{bg};border:{bdr};border-radius:6px;padding:6px 9px;font-size:11px;font-weight:{fw};text-align:center'>{r}<br>{l}</div>".format(
                bg=bg, bdr=bdr, fw="700" if is_cur else "400", r=trange, l=tlabel)
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)
        st.caption("Current: **{}** — {}".format(tw["label"], tw["note"]))
        st.markdown("---")
        st.markdown("**📊 Nifty Gap vs previous close**")
        if gap_data["ok"]:
            gp = gap_data["gap_pts"]; gpct = gap_data["gap_pct"]
            col_g = "#059669" if gap_data["direction"] == "UP" else "#dc2626"
            st.markdown("<div style='font-size:26px;font-weight:800;color:{c}'>"
                        "{a} {pts:+.0f} pts ({pct:+.2f}%)</div>"
                        "<div style='font-size:12px;color:#57606a;margin-top:4px'>"
                        "Prev: Rs {prev:,.2f} → Last: Rs {last:,.2f}</div>".format(
                            c=col_g, a="▲" if gap_data["direction"] == "UP" else "▼",
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
            upcoming.append({"Date": d.strftime("%d %b %Y (%A)"), "Event": hn, "Type": "🏖️ Holiday",
                              "Days Away": (d - today_d).days, "Impact": "🔴 CLOSED"})
    for ds, (en, imp) in SCHEDULED_EVENTS.items():
        d = date.fromisoformat(ds)
        if d >= today_d:
            upcoming.append({"Date": d.strftime("%d %b %Y (%A)"), "Event": en, "Type": "📌 Event",
                              "Days Away": (d - today_d).days, "Impact": "🚫 EXTREME" if imp == "EXTREME" else "⚠️ HIGH"})
    if upcoming:
        upcoming.sort(key=lambda x: x["Days Away"])
        st.dataframe(pd.DataFrame(upcoming[:12])[["Date", "Event", "Type", "Impact", "Days Away"]],
                     use_container_width=True, hide_index=True)
    for e in [x for x in upcoming if x["Days Away"] <= 2]:
        st.warning("⚠️ **{}** is {} day(s) away — {}".format(e["Event"], e["Days Away"], e["Impact"]))
    st.markdown("---")

    # Live news
    st.subheader("📡 Live Market Headlines")
    if st.button("🔄 Refresh News"):
        st.cache_data.clear()
    with st.spinner("Fetching headlines..."):
        articles = fetch_market_news()
    if not articles:
        st.info("Could not fetch news. Check MoneyControl or NSE manually.")
    else:
        imp_filter = st.radio("Filter", ["All", "🔴 HIGH only", "🟡 MEDIUM+"], horizontal=True)
        filtered = articles if imp_filter == "All" else (
            [a for a in articles if a["impact"] == "🔴 HIGH"] if imp_filter == "🔴 HIGH only" else
            [a for a in articles if a["impact"] in ("🔴 HIGH", "🟡 MEDIUM")])
        for art in filtered[:20]:
            imp = art["impact"]
            bg  = "#fef2f2" if imp == "🔴 HIGH" else ("#fffbeb" if imp == "🟡 MEDIUM" else "#f9fafb")
            bd  = "#fca5a5" if imp == "🔴 HIGH" else ("#fcd34d" if imp == "🟡 MEDIUM" else "#e5e7eb")
            kws = " · ".join(["<code style='font-size:10px;background:#f3f4f6;padding:1px 4px;border-radius:3px'>{}</code>".format(k)
                              for k in art["keywords"].split(", ") if k and k != "—"])
            st.markdown("<div style='background:{bg};border:1px solid {bd};border-radius:8px;padding:10px 14px;margin-bottom:8px'>"
                        "<div style='display:flex;justify-content:space-between;align-items:flex-start;gap:8px'>"
                        "<a href='{link}' target='_blank' style='font-size:13px;font-weight:600;color:#1d4ed8;text-decoration:none;flex:1'>{title}</a>"
                        "<span style='font-size:11px;white-space:nowrap;font-weight:700'>{imp}</span></div>"
                        "<div style='font-size:11px;color:#6b7280;margin-top:5px'>{src} | {pub}{kw}</div></div>".format(
                            bg=bg, bd=bd, link=art["link"], title=art["title"], imp=imp,
                            src=art["source"], pub=art["published"], kw=(" | " + kws) if kws else ""),
                        unsafe_allow_html=True)
        hc = sum(1 for a in articles if a["impact"] == "🔴 HIGH")
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
    st.markdown("---")

    rem_pct = (cap_stats["current"] / cap_stats["initial"] * 100) if cap_stats["initial"] else 0
    rem_pct_safe = max(0, min(int(rem_pct), 100))
    cap_d, cap_dc = pnl_delta(cap_stats["pnl"])
    cc1, cc2, cc3, cc4, cc5 = st.columns(5)
    cc1.metric("💰 Initial Capital",  "Rs {:,.0f}".format(cap_stats["initial"]))
    cc2.metric("💵 Current Balance",  "Rs {:,.0f}".format(cap_stats["current"]), cap_d, delta_color=cap_dc)
    cc3.metric("📉 P&L",              "Rs {:,.0f}".format(cap_stats["pnl"]),
               "{:.1f}%".format(cap_stats["pnl_pct"]),
               delta_color="normal" if cap_stats["pnl"] >= 0 else "inverse")
    cc4.metric("📅 Days Trading",     "{} days".format(cap_stats["days"]))
    cc5.metric("🏦 Capital Left",     "{:.1f}%".format(rem_pct),
               delta_color="normal" if rem_pct >= 80 else "inverse")

    prog = "🟢" if rem_pct >= 80 else ("🟡" if rem_pct >= 60 else "🔴")
    st.progress(rem_pct_safe,
                text="{} Rs {:,.0f} of Rs {:,.0f} remaining ({:.1f}%)".format(
                    prog, cap_stats["current"], cap_stats["initial"], rem_pct))

    with st.expander("✏️ Edit / Fix Capital", expanded=False):
        edit_tab1, edit_tab2 = st.tabs(["🔧 Set / Fix Initial Capital", "➕ Add Capital Deposit"])

        with edit_tab1:
            st.caption("⚠️ Use this to **correct the Initial Capital** shown above (currently shows Rs {:,.0f}).".format(cap_stats["initial"]))
            with st.form("dash_reset_cap_form"):
                dr1, dr2 = st.columns(2)
                new_init = dr1.number_input(
                    "Correct Initial Capital (Rs)",
                    value=float(cap_stats["initial"]) if cap_stats["initial"] else 40000.0,
                    step=1000.0, format="%.0f",
                )
                new_start_date = dr2.date_input("Trading Start Date", value=datetime.today())
                if st.form_submit_button("⚠️ Reset & Set Initial Capital to Rs {:,.0f}".format(new_init), type="primary"):
                    fresh = load_capital()
                    fresh["initial_capital"] = float(new_init)
                    fresh["current_capital"] = float(new_init)
                    fresh["start_date"]      = new_start_date.strftime("%Y-%m-%d")
                    fresh["history"]         = [{"date": new_start_date.strftime("%Y-%m-%d"),
                                                 "balance": float(new_init), "note": "Initial capital reset"}]
                    save_capital(fresh)
                    st.success("✅ Initial capital reset to Rs {:,.0f}".format(new_init))
                    st.rerun()

        with edit_tab2:
            st.caption("Added more money to your trading account? Enter **how much you deposited**.")
            with st.form("dash_deposit_form"):
                dd1, dd2 = st.columns(2)
                deposit_amt = dd1.number_input(
                    "Amount Deposited (Rs)",
                    value=0.0, min_value=0.0,
                    step=1000.0, format="%.0f",
                )
                deposit_note = dd2.text_input("Note", placeholder="e.g. Added funds from bank")
                if st.form_submit_button("➕ Add Rs {:,.0f} to Capital".format(deposit_amt), type="primary"):
                    if deposit_amt <= 0:
                        st.error("Enter an amount greater than 0.")
                    else:
                        fresh = load_capital()
                        new_bal = round(float(fresh.get("current_capital", 40000.0)) + deposit_amt, 2)
                        fresh["current_capital"] = new_bal
                        fresh["history"] = fresh.get("history", []) + [{
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "balance": new_bal,
                            "note": deposit_note or "Deposit Rs {:,.0f}".format(deposit_amt)
                        }]
                        save_capital(fresh)
                        st.success("✅ Rs {:,.0f} added — New balance: Rs {:,.0f}".format(deposit_amt, new_bal))
                        st.rerun()

    st.markdown("---")

    # Trade KPIs
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Trades", stats["total_trades"])
    k2.metric("Win Rate",     "{:.1f}%".format(stats["win_rate"]))
    d, dc = pnl_delta(stats["total_pnl"])
    k3.metric("Net P&L",      "Rs {:,.0f}".format(stats["total_pnl"]), d, delta_color=dc)
    k4.metric("Reward:Risk",  "{:.2f}x".format(stats["reward_risk"]))

    k5, k6, k7, k8 = st.columns(4)
    k5.metric("Wins",       stats["wins"])
    k6.metric("Losses",     stats["losses"])
    k7.metric("Best Trade", "Rs {:,.0f}".format(stats["best_trade"]))
    k8.metric("Worst Trade", "Rs {:,.0f}".format(stats["worst_trade"]))

    st.markdown("---")

    if not closed_df.empty:
        pnl_s = pd.to_numeric(closed_df["Net P&L"], errors="coerce").fillna(0)
        left, right = st.columns([3, 2])
        with left:
            st.subheader("📈 Cumulative P&L Growth")
            cum = pnl_s.cumsum()
            fig_pnl = go.Figure()
            fig_pnl.add_trace(go.Scatter(
                x=list(range(1, len(cum) + 1)), y=cum,
                mode="lines+markers",
                line=dict(color="#26a69a" if cum.iloc[-1] >= 0 else "#ef5350", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(38,166,154,0.1)" if cum.iloc[-1] >= 0 else "rgba(239,83,80,0.1)",
                name="Cumulative P&L",
            ))
            fig_pnl.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.3)")
            fig_pnl.update_layout(
                xaxis_title="Trade Number", yaxis_title="Net P&L (Rs)",
                template="plotly_dark", height=320,
                margin=dict(l=0, r=0, t=20, b=0),
            )
            st.plotly_chart(fig_pnl, use_container_width=True)

        with right:
            st.subheader("🎯 Win / Loss Ratio")
            fig_pie = go.Figure(go.Pie(
                labels=["Wins", "Losses"],
                values=[stats["wins"], stats["losses"]],
                hole=0.55,
                marker=dict(colors=["#26a69a", "#ef5350"]),
            ))
            fig_pie.update_layout(
                template="plotly_dark", height=320,
                margin=dict(l=0, r=0, t=20, b=0),
                showlegend=True,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        st.subheader("📋 Recent 5 Trades")
        rc = ["Trade #", "Date", "Symbol", "Option Type", "Strike",
              "Entry Price", "Exit Price", "Lots", "Net P&L", "Result"]
        st.dataframe(closed_df[rc].tail(5).sort_index(ascending=False),
                     use_container_width=True, hide_index=True)
    else:
        st.info("No closed trades yet. Go to **📓 Log Trade** to record your first trade!")


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 💰 MY CAPITAL
# ══════════════════════════════════════════════════════════════════════════════
elif page == "💰 My Capital":
    st.title("💰 Capital Tracker & Balance History")
    st.caption("Auto-updated on every closed trade. Deposit or withdraw funds anytime.")
    st.markdown("---")

    rem_pct = (cap_stats["current"] / cap_stats["initial"] * 100) if cap_stats["initial"] else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Initial Capital",  "Rs {:,.0f}".format(cap_stats["initial"]))
    d, dc = pnl_delta(cap_stats["pnl"])
    c2.metric("Current Balance",  "Rs {:,.0f}".format(cap_stats["current"]), d, delta_color=dc)
    c3.metric("Growth %",         "{:+.1f}%".format(cap_stats["pnl_pct"]),
              delta_color="normal" if cap_stats["pnl"] >= 0 else "inverse")
    c4.metric("Days Active",      "{} days".format(cap_stats["days"]))

    st.markdown("---")

    tab_dep, tab_wd, tab_set, tab_hist = st.tabs([
        "➕ Add Deposit", "➖ Withdraw Funds", "🔧 Set / Fix Initial Capital", "📜 Full History"
    ])

    with tab_dep:
        st.subheader("Add Funds to Trading Account")
        with st.form("deposit_form"):
            dep_amt  = st.number_input("Deposit Amount (Rs)", min_value=100.0, value=5000.0, step=500.0)
            dep_note = st.text_input("Note", placeholder="e.g. Added funds from salary")
            if st.form_submit_button("➕ Add Deposit", type="primary"):
                fresh = load_capital()
                new_bal = round(float(fresh.get("current_capital", 40000.0)) + dep_amt, 2)
                fresh["current_capital"] = new_bal
                fresh["history"] = fresh.get("history", []) + [{
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "balance": new_bal,
                    "note": dep_note or "Deposit Rs {:,.0f}".format(dep_amt)
                }]
                save_capital(fresh)
                st.success("✅ Deposit of Rs {:,.0f} saved! New balance: Rs {:,.0f}".format(dep_amt, new_bal))
                st.rerun()

    with tab_wd:
        st.subheader("Withdraw Funds from Trading Account")
        with st.form("withdraw_form"):
            wd_amt  = st.number_input("Withdrawal Amount (Rs)", min_value=100.0, value=2000.0, step=500.0)
            wd_note = st.text_input("Note", placeholder="e.g. Profit payout to bank")
            if st.form_submit_button("➖ Record Withdrawal", type="secondary"):
                fresh = load_capital()
                new_bal = round(float(fresh.get("current_capital", 40000.0)) - wd_amt, 2)
                fresh["current_capital"] = new_bal
                fresh["history"] = fresh.get("history", []) + [{
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "balance": new_bal,
                    "note": wd_note or "Withdrawal Rs {:,.0f}".format(wd_amt)
                }]
                save_capital(fresh)
                st.success("✅ Withdrawal of Rs {:,.0f} recorded! New balance: Rs {:,.0f}".format(wd_amt, new_bal))
                st.rerun()

    with tab_set:
        st.subheader("Reset / Fix Starting Capital")
        st.caption("Use this if your starting capital was recorded incorrectly.")
        with st.form("reset_form"):
            r_cap  = st.number_input("Starting Capital (Rs)", min_value=1000.0, value=40000.0, step=1000.0)
            r_date = st.date_input("Start Date", value=datetime.today())
            if st.form_submit_button("⚠️ Reset Starting Capital", type="primary"):
                fresh = load_capital()
                fresh["initial_capital"] = float(r_cap)
                fresh["current_capital"] = float(r_cap)
                fresh["start_date"]      = r_date.strftime("%Y-%m-%d")
                fresh["history"]         = [{"date": r_date.strftime("%Y-%m-%d"),
                                             "balance": float(r_cap), "note": "Initial capital reset"}]
                save_capital(fresh)
                st.success("✅ Capital reset to Rs {:,.0f} as of {}".format(r_cap, r_date))
                st.rerun()

    with tab_hist:
        st.subheader("Capital Log")
        hist = cap_data.get("history", [])
        if hist:
            st.dataframe(pd.DataFrame(hist).sort_index(ascending=False), use_container_width=True, hide_index=True)
        else:
            st.info("No capital history found.")


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📓 LOG TRADE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📓 Log Trade":
    st.title("📓 Manual Trade Entry")
    st.caption("Record your trade with full risk analytics & lessons learned.")
    st.markdown("---")

    with st.form("log_trade_form", clear_on_submit=True):
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)
        f_symbol = r1c1.selectbox("Symbol", list(NSE_SYMBOLS.keys()), index=0, key="lt_sym")
        f_type   = r1c2.selectbox("Option Type", ["PUT", "CALL"], key="lt_type")
        f_strike = r1c3.number_input("Strike Price", value=24000, step=50, key="lt_strike")
        f_expiry = r1c4.text_input("Expiry Date", value=datetime.today().strftime("%Y-%m-%d"), key="lt_exp")

        r2c1, r2c2, r2c3, r2c4 = st.columns(4)
        f_entry = r2c1.number_input("Entry Price (Rs)", value=100.0, step=0.5, format="%.2f", key="lt_entry")
        f_exit  = r2c2.number_input("Exit Price (Rs, 0 if OPEN)", value=0.0, step=0.5, format="%.2f", key="lt_exit")
        f_lots  = r2c3.number_input("Lots", min_value=1, value=1, step=1, key="lt_lots")
        f_size  = r2c4.number_input("Lot Size", min_value=1, value=75, step=1, key="lt_size")

        st.markdown("**Technical Indicators at Entry**")
        m1, m2, m3, m4 = st.columns(4)
        f_rsi   = m1.number_input("RSI at Entry", value=50.0, step=0.1, format="%.1f", min_value=0.0, max_value=100.0, key="lt_rsi")
        f_adx   = m2.number_input("ADX at Entry", value=25.0, step=0.1, format="%.1f", min_value=0.0, max_value=100.0, key="lt_adx")
        f_st    = m3.selectbox("Supertrend", ["BEARISH", "BULLISH"], key="lt_st")
        f_dsaid = m4.selectbox("Dashboard Said", ["PUT", "CALL", "WAIT"], key="lt_dsaid")

        st.markdown("**Reflection & Notes**")
        n1, n2, n3 = st.columns(3)
        f_hold    = n1.text_input("Hold Time", placeholder="e.g. 25 mins", key="lt_hold")
        f_lessons = n2.text_input("Lessons Learned", placeholder="e.g. Never enter RSI < 35", key="lt_lessons")
        f_notes   = n3.text_input("Notes", placeholder="e.g. Clean bounce from VWAP", key="lt_notes")

        sub = st.form_submit_button("💾 Save Trade", type="primary", use_container_width=True)

        if sub:
            now     = datetime.now()
            capital = round(f_entry * f_lots * f_size, 2)
            gross   = round((f_exit - f_entry) * f_lots * f_size, 2) if f_exit > 0 else 0.0
            stt     = round(f_exit * f_lots * f_size * DEFAULT_STT_PCT / 100, 2) if f_exit > 0 else 0.0
            other_c = DEFAULT_OTHER if f_exit > 0 else 0.0
            f_brok  = DEFAULT_BROKERAGE if f_exit > 0 else 0.0
            net     = round(gross - f_brok - stt - other_c, 2) if f_exit > 0 else 0.0
            result  = "OPEN" if f_exit <= 0 else ("WIN" if net >= 0 else "LOSS")

            trade_num = 1 if trades_df.empty else (pd.to_numeric(trades_df["Trade #"], errors="coerce").max() + 1)
            row = {
                "Trade #":         int(trade_num),
                "Date":            now.strftime("%Y-%m-%d"),
                "Time":            now.strftime("%H:%M"),
                "Symbol":          f_symbol,
                "Option Type":     f_type,
                "Strike":          f_strike,
                "Expiry":          f_expiry,
                "Entry Price":     f_entry,
                "Exit Price":      f_exit if f_exit > 0 else "",
                "Lots":            f_lots,
                "Lot Size":        f_size,
                "Capital Used":    capital,
                "Gross P&L":       gross if f_exit > 0 else "",
                "Brokerage":       f_brok if f_exit > 0 else "",
                "STT":             stt if f_exit > 0 else "",
                "Other Charges":   other_c if f_exit > 0 else "",
                "Net P&L":         net if f_exit > 0 else "",
                "Result":          result,
                "Hold Time":       f_hold,
                "Entry RSI":       round(f_rsi, 1) if f_rsi else "",
                "Entry ADX":       round(f_adx, 1) if f_adx else "",
                "Supertrend":      f_st,
                "Dashboard Said":  f_dsaid,
                "Lessons Learned": f_lessons,
                "Notes":           f_notes,
            }
            new_df = pd.concat([trades_df, pd.DataFrame([row])], ignore_index=True)
            save_trades(new_df)

            if result in ("WIN", "LOSS"):
                fresh_cap = load_capital()
                new_bal   = round(float(fresh_cap.get("current_capital", 40000.0)) + net, 2)
                fresh_cap["current_capital"] = new_bal
                fresh_cap["history"] = fresh_cap.get("history", []) + [{
                    "date": now.strftime("%Y-%m-%d"),
                    "balance": new_bal,
                    "note": "Trade #{} {} | Net P&L: Rs {:,.0f}".format(int(trade_num), result, net)
                }]
                save_capital(fresh_cap)

            emoji = "✅ WIN" if result == "WIN" else ("❌ LOSS" if result == "LOSS" else "📂 OPEN")
            st.success("Trade #{} saved! {} | Net P&L: {}".format(
                row["Trade #"], emoji, "Rs {:,.0f}".format(net) if f_exit > 0 else "Open position"))
            st.rerun()

    # ── Recent Trades Log + Delete ─────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📋 Recent Trades Log")

    fresh_df = load_trades()
    if fresh_df.empty:
        st.info("No trades logged yet in the database.")
    else:
        show_cols = ["Trade #", "Date", "Symbol", "Option Type", "Strike",
                     "Entry Price", "Exit Price", "Lots", "Net P&L", "Result"]
        recent = fresh_df[show_cols].sort_values("Trade #", ascending=False).head(20)
        st.dataframe(recent, use_container_width=True, hide_index=True)

    st.markdown("#### 🗑️ Delete a Trade")
    st.caption("⚠️ Deleting a closed trade will also reverse its impact on your capital balance.")

    if fresh_df.empty:
        st.caption("No trades available to delete.")
    else:
        del_col1, del_col2 = st.columns([2, 1])
        trade_labels = [
            "#{} — {} {} {} | {}".format(
                int(r["Trade #"]), r["Date"], r["Symbol"],
                r["Option Type"],  r["Result"])
            for _, r in fresh_df.sort_values("Trade #", ascending=False).iterrows()
        ]
        sel_label = del_col1.selectbox("Select trade to delete", trade_labels, key="lt_del_sel")
        sel_num   = int(sel_label.split(" — ")[0].replace("#", "").strip())

        if del_col2.button("🗑️ Delete Selected Trade", type="secondary", use_container_width=True, key="lt_del_btn"):
            mask = pd.to_numeric(fresh_df["Trade #"], errors="coerce") == sel_num
            trade = fresh_df[mask].iloc[0]
            result = str(trade.get("Result", ""))
            net = float(trade.get("Net P&L", 0) or 0)

            updated_df = fresh_df[~mask].reset_index(drop=True)
            save_trades(updated_df)

            if result in ("WIN", "LOSS") and net != 0.0:
                fresh_cap = load_capital()
                new_bal   = round(float(fresh_cap.get("current_capital", 40000.0)) - net, 2)
                fresh_cap["current_capital"] = new_bal
                fresh_cap["history"] = fresh_cap.get("history", []) + [{
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "balance": new_bal,
                    "note": "Reversed Trade #{} {} (Rs {:,.0f})".format(sel_num, result, net)
                }]
                save_capital(fresh_cap)

            st.success("✅ Trade #{} deleted successfully!".format(sel_num))
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 🔄 ANGEL ONE SYNC
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔄 Angel One Sync":
    st.title("🔄 Angel One Auto-Sync")
    st.caption("Automatically fetch your executed trades from Angel One — no manual entry needed!")
    st.markdown("---")
    render_angel_sync_panel(load_fn=load_trades, save_fn=save_trades, columns=COLUMNS)


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📋 ALL TRADES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📋 All Trades":
    st.title("📋 All Trades")
    if trades_df.empty:
        st.info("No trades yet. Log your first trade from **📓 Log Trade**.")
    else:
        fc1, fc2, fc3 = st.columns(3)
        syms     = ["All"] + sorted(trades_df["Symbol"].dropna().unique().tolist())
        filt_sym = fc1.selectbox("Symbol",      syms)
        filt_typ = fc2.selectbox("Option Type", ["All", "PUT", "CALL"])
        filt_res = fc3.selectbox("Result",      ["All", "WIN", "LOSS", "OPEN"])
        view = trades_df.copy()
        if filt_sym != "All": view = view[view["Symbol"] == filt_sym]
        if filt_typ != "All": view = view[view["Option Type"] == filt_typ]
        if filt_res != "All": view = view[view["Result"] == filt_res]
        st.caption("{} trades shown".format(len(view)))
        st.dataframe(view.sort_values("Trade #", ascending=False), use_container_width=True, hide_index=True)
        if not view.empty:
            pnl_tot = pd.to_numeric(view["Net P&L"], errors="coerce").sum()
            d, dc   = pnl_delta(pnl_tot)
            t1, t2  = st.columns(2)
            t1.metric("Net P&L (filtered)", "Rs {:,.0f}".format(pnl_tot), d, delta_color=dc)
            t2.metric("Capital Used",       "Rs {:,.0f}".format(pd.to_numeric(view["Capital Used"], errors="coerce").sum()))


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📅 MONTHLY REPORT
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📅 Monthly Report":
    st.title("📅 Monthly P&L Report")
    if closed_df.empty:
        st.info("No closed trades yet.")
    else:
        mdf = closed_df.copy()
        mdf["Month"] = pd.to_datetime(mdf["Date"], errors="coerce").dt.strftime("%Y-%m")
        grouped = mdf.groupby("Month").apply(lambda g: pd.Series({
            "Trades":       len(g),
            "Wins":         (g["Result"] == "WIN").sum(),
            "Losses":       (g["Result"] == "LOSS").sum(),
            "Win Rate %":   round((g["Result"] == "WIN").sum() / len(g) * 100, 1),
            "Gross P&L":    pd.to_numeric(g["Gross P&L"], errors="coerce").sum().round(2),
            "Charges":      (pd.to_numeric(g["Brokerage"], errors="coerce").sum() +
                             pd.to_numeric(g["STT"], errors="coerce").sum() +
                             pd.to_numeric(g["Other Charges"], errors="coerce").sum()).round(2),
            "Net P&L":      pd.to_numeric(g["Net P&L"], errors="coerce").sum().round(2),
        })).reset_index()

        st.dataframe(grouped, use_container_width=True, hide_index=True)

        fig_m = go.Figure()
        colors = ["#26a69a" if v >= 0 else "#ef5350" for v in grouped["Net P&L"]]
        fig_m.add_trace(go.Bar(x=grouped["Month"], y=grouped["Net P&L"], marker_color=colors))
        fig_m.update_layout(template="plotly_dark", height=300, yaxis_title="Net P&L (Rs)")
        st.plotly_chart(fig_m, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 📈 PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📈 Performance":
    st.title("📈 Performance Analysis")
    if closed_df.empty:
        st.info("No closed trades yet.")
    else:
        t1, t2, t3 = st.tabs(["By Symbol", "PUT vs CALL", "Dashboard Accuracy"])
        with t1:
            sg = closed_df.groupby("Symbol").apply(lambda g: pd.Series({
                "Trades":    len(g),
                "Wins":      (g["Result"] == "WIN").sum(),
                "Net P&L":   pd.to_numeric(g["Net P&L"], errors="coerce").sum().round(2),
                "Win Rate %": round((g["Result"] == "WIN").sum() / len(g) * 100, 1),
            })).reset_index()
            st.dataframe(sg, use_container_width=True, hide_index=True)
        with t2:
            og = closed_df.groupby("Option Type").apply(lambda g: pd.Series({
                "Trades":    len(g),
                "Wins":      (g["Result"] == "WIN").sum(),
                "Net P&L":   pd.to_numeric(g["Net P&L"], errors="coerce").sum().round(2),
                "Win Rate %": round((g["Result"] == "WIN").sum() / len(g) * 100, 1),
            })).reset_index()
            st.dataframe(og, use_container_width=True, hide_index=True)
        with t3:
            dg = closed_df.groupby("Dashboard Said").apply(lambda g: pd.Series({
                "Trades":    len(g),
                "Wins":      (g["Result"] == "WIN").sum(),
                "Net P&L":   pd.to_numeric(g["Net P&L"], errors="coerce").sum().round(2),
                "Win Rate %": round((g["Result"] == "WIN").sum() / len(g) * 100, 1),
            })).reset_index()
            st.dataframe(dg, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: 💸 EXPENSES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "💸 Expenses":
    st.title("💸 Brokerage & Taxes Breakdown")
    if closed_df.empty:
        st.info("No closed trades yet.")
    else:
        brok_tot  = pd.to_numeric(closed_df["Brokerage"], errors="coerce").sum()
        stt_tot   = pd.to_numeric(closed_df["STT"], errors="coerce").sum()
        other_tot = pd.to_numeric(closed_df["Other Charges"], errors="coerce").sum()
        grand_tot = brok_tot + stt_tot + other_tot

        e1, e2, e3, e4 = st.columns(4)
        e1.metric("Total Charges", "Rs {:,.0f}".format(grand_tot))
        e2.metric("Brokerage",     "Rs {:,.0f}".format(brok_tot))
        e3.metric("STT (Govt)",    "Rs {:,.0f}".format(stt_tot))
        e4.metric("Other Charges", "Rs {:,.0f}".format(other_tot))


# ══════════════════════════════════════════════════════════════════════════════
# ██  PAGE: ⬇️ EXPORT
# ══════════════════════════════════════════════════════════════════════════════
elif page == "⬇️ Export":
    st.title("⬇️ Export Your Records")
    st.markdown("---")
    if trades_df.empty:
        st.info("No trades to export yet.")
    else:
        st.subheader("📋 Download CSV")
        st.download_button(
            label="⬇️ Download CSV",
            data=trades_df.to_csv(index=False).encode("utf-8"),
            file_name="Raja_Trades_{}.csv".format(datetime.now().strftime("%Y%m%d")),
            mime="text/csv",
            use_container_width=True,
        )

st.markdown("---")
st.caption("📈 Nifty F&O Unified Trader & Records | Powered by Supabase Cloud | Educational & personal tracking only")
