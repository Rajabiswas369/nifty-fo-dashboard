"""
Nifty F&O Signal Dashboard
===========================
  📈 Live Signal Dashboard    — RSI, ADX, Supertrend, MACD, VWAP, trade decision, interactive charts
  📰 Market News & Verdict    — Should I trade today? 9-Gate checks + live headlines + events calendar

This app is purely for TRADING SIGNALS & MARKET ANALYSIS.
For trade records, capital management, and reporting go to the Records app.

Data via yfinance. Educational use only.
"""

import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from xml.etree import ElementTree as ET

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pytz

from goal_engine import (
    load_goal_cloud, save_goal_cloud,
    calculate_compounding_schedule, evaluate_goal_progress
)
from angel_sync import (
    is_angel_configured, get_live_positions, get_live_margins, fetch_angel_trades
)

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Nifty F&O Signal Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═════════════════════════════════════════════════════════════════════════════
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
st.sidebar.title("Nifty F&O Signal Dashboard")
st.sidebar.markdown("---")
st.sidebar.info("📊 **This app:** Live signals, indicators & news.\n\n💼 For trade records & capital, use the Records app.")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "📂 Navigate",
    [
        "📈 Signal Dashboard",
        "🕹️ Angel One Live Cockpit",
        "🎯 Goal & Compounding Engine",
        "📰 Market News & Verdict",
    ],
    index=0,
)
st.sidebar.markdown("---")

# Storage / Cloud Status
try:
    _supa_ok = "supabase_url" in st.secrets and "supabase_key" in st.secrets
except Exception:
    _supa_ok = False

if _supa_ok:
    st.sidebar.success("☁️ Storage: **Supabase Cloud (Live)**")
else:
    st.sidebar.warning("⚠️ Supabase not connected")

try:
    from angel_sync import is_angel_configured
    if is_angel_configured():
        st.sidebar.success("✅ Angel One **Configured**")
    else:
        st.sidebar.info("ℹ️ Angel One not configured")
except Exception:
    pass

st.sidebar.markdown("---")

# Controls for all pages
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
    close, high, low = df["Close"], df["High"], df["Low"]

    raw_vol = df["Volume"].copy().astype(float) if "Volume" in df.columns else pd.Series(0.0, index=df.index)
    raw_vol = raw_vol.where(raw_vol > 0, other=np.nan)
    vol_all_nan = raw_vol.isna().all()
    vol = raw_vol if not vol_all_nan else df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(0.0, index=df.index)

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
        import requests
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
        })
        hist = yf.Ticker("^NSEI", session=session).history(period="5d", interval="1d")
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


# ═════════════════════════════════════════════════════════════════════════════
# CANDLESTICK PATTERN DETECTOR
# ═════════════════════════════════════════════════════════════════════════════
def detect_candle_patterns(df: pd.DataFrame) -> list:
    """
    Detect the last 1–3 candle patterns.
    Returns a list of detected pattern dicts: {name, signal, strength, desc}.
    """
    if len(df) < 3:
        return []

    c0 = df.iloc[-1]   # latest (current) candle
    c1 = df.iloc[-2]   # previous candle
    c2 = df.iloc[-3]   # two candles back

    o0, h0, lo0, cl0 = float(c0["Open"]), float(c0["High"]), float(c0["Low"]), float(c0["Close"])
    o1, h1, lo1, cl1 = float(c1["Open"]), float(c1["High"]), float(c1["Low"]), float(c1["Close"])
    o2, h2, lo2, cl2 = float(c2["Open"]), float(c2["High"]), float(c2["Low"]), float(c2["Close"])

    body0  = abs(cl0 - o0)
    body1  = abs(cl1 - o1)
    range0 = h0 - lo0 if h0 > lo0 else 0.0001
    range1 = h1 - lo1 if h1 > lo1 else 0.0001

    patterns = []

    # ── BULLISH ENGULFING ──────────────────────────────────────────────────────
    if (cl1 < o1                                     # c1 is bearish
            and cl0 > o0                             # c0 is bullish
            and o0 <= cl1                            # opens at or below c1 close
            and cl0 >= o1                            # closes at or above c1 open
            and body0 > body1 * 0.9):
        patterns.append({
            "name":     "Bullish Engulfing",
            "signal":   "CALL",
            "strength": "STRONG",
            "desc":     "Current candle fully engulfs the prior bearish candle — buyers have taken control.",
        })

    # ── BEARISH ENGULFING ──────────────────────────────────────────────────────
    if (cl1 > o1                                     # c1 is bullish
            and cl0 < o0                             # c0 is bearish
            and o0 >= cl1                            # opens at or above c1 close
            and cl0 <= o1                            # closes at or below c1 open
            and body0 > body1 * 0.9):
        patterns.append({
            "name":     "Bearish Engulfing",
            "signal":   "PUT",
            "strength": "STRONG",
            "desc":     "Current candle fully engulfs the prior bullish candle — sellers have taken control.",
        })

    # ── HAMMER (bullish reversal after down move) ──────────────────────────────
    lower_wick0 = min(o0, cl0) - lo0
    upper_wick0 = h0 - max(o0, cl0)
    if (lower_wick0 >= 2 * body0
            and upper_wick0 <= body0 * 0.5
            and cl0 > o0
            and cl1 < o1):
        patterns.append({
            "name":     "Hammer",
            "signal":   "CALL",
            "strength": "MEDIUM",
            "desc":     "Long lower wick with small body after a down candle — bulls rejected lower prices.",
        })

    # ── SHOOTING STAR (bearish reversal after up move) ─────────────────────────
    upper_wick0 = h0 - max(o0, cl0)
    lower_wick0 = min(o0, cl0) - lo0
    if (upper_wick0 >= 2 * body0
            and lower_wick0 <= body0 * 0.5
            and cl0 < o0
            and cl1 > o1):
        patterns.append({
            "name":     "Shooting Star",
            "signal":   "PUT",
            "strength": "MEDIUM",
            "desc":     "Long upper wick with small body after an up candle — bears rejected higher prices.",
        })

    # ── DOJI (indecision — wait for next candle) ───────────────────────────────
    if body0 <= range0 * 0.08:
        patterns.append({
            "name":     "Doji",
            "signal":   "WAIT",
            "strength": "WEAK",
            "desc":     "Open ≈ Close. Market indecision. Wait for the next candle to confirm direction.",
        })

    # ── BULLISH MARUBOZU (strong bull candle) ──────────────────────────────────
    if (cl0 > o0
            and body0 >= range0 * 0.85
            and cl0 >= h0 * 0.998):
        patterns.append({
            "name":     "Bullish Marubozu",
            "signal":   "CALL",
            "strength": "STRONG",
            "desc":     "Large bull candle with almost no wicks — strong buying momentum in this candle.",
        })

    # ── BEARISH MARUBOZU (strong bear candle) ──────────────────────────────────
    if (cl0 < o0
            and body0 >= range0 * 0.85
            and o0 >= h0 * 0.998):
        patterns.append({
            "name":     "Bearish Marubozu",
            "signal":   "PUT",
            "strength": "STRONG",
            "desc":     "Large bear candle with almost no wicks — strong selling momentum in this candle.",
        })

    # ── MORNING STAR (3-candle bullish reversal) ───────────────────────────────
    if (cl2 < o2                                     # c2 bearish
            and body1 <= range1 * 0.3               # c1 small body (indecision)
            and cl0 > o0                             # c0 bullish
            and cl0 > (o2 + cl2) / 2):              # c0 closes above c2 midpoint
        patterns.append({
            "name":     "Morning Star",
            "signal":   "CALL",
            "strength": "STRONG",
            "desc":     "3-candle reversal: big bear → small body → big bull. Trend reversal to upside likely.",
        })

    # ── EVENING STAR (3-candle bearish reversal) ───────────────────────────────
    if (cl2 > o2                                     # c2 bullish
            and body1 <= range1 * 0.3               # c1 small body (indecision)
            and cl0 < o0                             # c0 bearish
            and cl0 < (o2 + cl2) / 2):              # c0 closes below c2 midpoint
        patterns.append({
            "name":     "Evening Star",
            "signal":   "PUT",
            "strength": "STRONG",
            "desc":     "3-candle reversal: big bull → small body → big bear. Trend reversal to downside likely.",
        })

    # ── INSIDE BAR (range compression — breakout pending) ─────────────────────
    if h0 < h1 and lo0 > lo1:
        patterns.append({
            "name":     "Inside Bar",
            "signal":   "WAIT",
            "strength": "WEAK",
            "desc":     "Current candle is within prior candle's range. Breakout pending — wait for next candle.",
        })

    return patterns


# ═════════════════════════════════════════════════════════════════════════════
# PRECISION ENTRY SIGNAL ENGINE
# ═════════════════════════════════════════════════════════════════════════════
def compute_precision_signal(df: pd.DataFrame, summary: dict, decision: dict,
                              vdict: dict) -> dict:
    """
    Combines candlestick pattern + live indicators to produce a precision
    BUY NOW / SELL PUT NOW signal with exact entry & exit time windows.

    Returns a dict:
      action       — "BUY CALL NOW" | "BUY PUT NOW" | "WAIT" | "NO TRADE"
      entry_time   — datetime string "HH:MM"
      exit_5m      — exit-by datetime string for 5-min trade
      exit_10m     — exit-by datetime string for 10-min trade
      exit_15m     — exit-by datetime string for 15-min trade
      signal_score — int 0–10 (how many checks fired)
      max_score    — int (total checks)
      pattern_name — top candle pattern name or "None"
      pattern_desc — pattern description
      reasons      — list[str]
      warnings     — list[str]
      tw_status    — time window status string
    """
    now_ist    = datetime.now(IST)
    tw         = vdict["tw"]
    reasons    = []
    warnings   = []
    score      = 0
    max_score  = 0
    direction  = "WAIT"

    # ── Gate 1: market must be in a tradeable time window ─────────────────────
    if tw["status"] not in ("best", "ok", "caution"):
        return {
            "action": "NO TRADE", "entry_time": now_ist.strftime("%H:%M"),
            "exit_5m": "—", "exit_10m": "—", "exit_15m": "—",
            "signal_score": 0, "max_score": 1, "pattern_name": "N/A",
            "pattern_desc": tw["note"], "reasons": [], "tw_status": tw["status"],
            "warnings": ["Market window: {} — {}".format(tw["label"], tw["note"])],
        }

    # ── Gate 2: no extreme events ──────────────────────────────────────────────
    if vdict.get("has_extreme_event"):
        return {
            "action": "NO TRADE", "entry_time": now_ist.strftime("%H:%M"),
            "exit_5m": "—", "exit_10m": "—", "exit_15m": "—",
            "signal_score": 0, "max_score": 1, "pattern_name": "N/A",
            "pattern_desc": "Extreme market event today — no trades.",
            "reasons": [], "tw_status": tw["status"],
            "warnings": ["Extreme event active: {}".format(vdict.get("event_name", ""))],
        }

    # ── Candle pattern ─────────────────────────────────────────────────────────
    patterns   = detect_candle_patterns(df)
    top_pat    = next((p for p in patterns if p["signal"] != "WAIT"), None)
    pat_name   = top_pat["name"]   if top_pat else "No clear pattern"
    pat_desc   = top_pat["desc"]   if top_pat else "No dominant candlestick pattern detected on the current candle."
    pat_signal = top_pat["signal"] if top_pat else "WAIT"
    pat_strength = top_pat["strength"] if top_pat else "WEAK"

    # ── Score candle pattern ───────────────────────────────────────────────────
    max_score += 2
    if pat_signal != "WAIT":
        pat_pts = {"STRONG": 2, "MEDIUM": 1, "WEAK": 0}[pat_strength]
        score  += pat_pts
        if pat_pts > 0:
            reasons.append("🕯️ {} ({}) → {}".format(pat_name, pat_strength, pat_signal))

    # ── Score MACD momentum ────────────────────────────────────────────────────
    max_score += 2
    macd_bull = summary["macd"] > summary["macd_signal"]
    macd_hist_rising = False
    if len(df) >= 2:
        h_now  = float(df["MACD_hist"].iloc[-1])
        h_prev = float(df["MACD_hist"].iloc[-2])
        macd_hist_rising = h_now > h_prev
    if macd_bull and macd_hist_rising:
        score += 2; reasons.append("📊 MACD above signal AND histogram rising (strong bull momentum)")
    elif macd_bull:
        score += 1; reasons.append("📊 MACD above signal (mild bull momentum)")
    elif not macd_bull and not macd_hist_rising:
        score += 2; reasons.append("📊 MACD below signal AND histogram falling (strong bear momentum)")
    elif not macd_bull:
        score += 1; reasons.append("📊 MACD below signal (mild bear momentum)")

    # ── Score RSI position ─────────────────────────────────────────────────────
    max_score += 1
    rsi = summary["rsi"]
    if 40 <= rsi <= 60:
        warnings.append("RSI {:.1f} neutral — momentum not decisive yet.".format(rsi))
    elif 55 < rsi <= 65:
        score += 1; reasons.append("📈 RSI {:.1f} in bullish zone".format(rsi))
    elif rsi > 65:
        warnings.append("RSI {:.1f} OVERBOUGHT — CALL entries risky, prefer PUT.".format(rsi))
        score += 1  # bearish lean
    elif 35 <= rsi < 45:
        score += 1; reasons.append("📉 RSI {:.1f} in bearish zone".format(rsi))
    elif rsi < 35:
        warnings.append("RSI {:.1f} OVERSOLD — PUT entries risky, prefer CALL.".format(rsi))
        score += 1  # bullish lean

    # ── Score Supertrend ───────────────────────────────────────────────────────
    max_score += 1
    if summary["supertrend"] != "WAIT":
        score += 1
        reasons.append("🔺 Supertrend: {}".format(summary["supertrend"]))

    # ── Score VWAP alignment ───────────────────────────────────────────────────
    max_score += 1
    above_vwap = summary["close"] > summary["vwap"]
    if above_vwap:
        score += 1; reasons.append("💹 Price above VWAP (institutional buy side)")
    else:
        score += 1; reasons.append("💹 Price below VWAP (institutional sell side)")

    # ── Score ADX trend strength ───────────────────────────────────────────────
    max_score += 1
    if summary["adx"] > 25:
        score += 1; reasons.append("📐 ADX {:.1f} — trend is strong, signals reliable".format(summary["adx"]))
    else:
        warnings.append("ADX {:.1f} — weak trend, choppy market, reduce size.".format(summary["adx"]))

    # ── Score EMA cross ────────────────────────────────────────────────────────
    max_score += 1
    ema_bull = summary["ema_cross"] == "BULLISH"
    score   += 1
    reasons.append("📏 EMA Cross: {}".format(summary["ema_cross"]))

    # ── Determine direction ────────────────────────────────────────────────────
    # Weighted vote combining pattern + indicators
    bull_votes = 0; bear_votes = 0

    if pat_signal == "CALL":  bull_votes += 2 if pat_strength == "STRONG" else 1
    if pat_signal == "PUT":   bear_votes += 2 if pat_strength == "STRONG" else 1
    if macd_bull:             bull_votes += 2 if macd_hist_rising else 1
    else:                     bear_votes += 2 if not macd_hist_rising else 1
    if above_vwap:            bull_votes += 1
    else:                     bear_votes += 1
    if ema_bull:              bull_votes += 1
    else:                     bear_votes += 1
    if summary["supertrend"] == "BULLISH": bull_votes += 1
    else:                                  bear_votes += 1
    if rsi > 55 and rsi <= 65: bull_votes += 1
    if rsi < 45 and rsi >= 35: bear_votes += 1
    if rsi > 65:               bear_votes += 1   # overbought → lean put
    if rsi < 35:               bull_votes += 1   # oversold  → lean call

    total_votes = bull_votes + bear_votes
    if total_votes == 0:
        direction = "WAIT"
    elif bull_votes > bear_votes:
        bull_conf = bull_votes / total_votes
        direction = "CALL" if bull_conf >= 0.55 else "WAIT"
    else:
        bear_conf = bear_votes / total_votes
        direction = "PUT" if bear_conf >= 0.55 else "WAIT"

    # Threshold: need at least 5/8 score to fire
    min_score = max(4, int(max_score * 0.55))
    if score < min_score:
        direction = "WAIT"
        warnings.append("Signal score {}/{} below threshold {} — no entry.".format(score, max_score, min_score))

    # ── Build action & times ───────────────────────────────────────────────────
    if direction == "CALL":
        action = "🟢 BUY CALL NOW"
    elif direction == "PUT":
        action = "🔴 BUY PUT NOW"
    else:
        action = "🟡 WAIT — No Entry"

    entry_dt  = now_ist
    exit_5m   = (entry_dt + timedelta(minutes=5)).strftime("%H:%M")
    exit_10m  = (entry_dt + timedelta(minutes=10)).strftime("%H:%M")
    exit_15m  = (entry_dt + timedelta(minutes=15)).strftime("%H:%M")

    return {
        "action":       action,
        "direction":    direction,
        "entry_time":   entry_dt.strftime("%H:%M"),
        "exit_5m":      exit_5m,
        "exit_10m":     exit_10m,
        "exit_15m":     exit_15m,
        "signal_score": score,
        "max_score":    max_score,
        "pattern_name": pat_name,
        "pattern_desc": pat_desc,
        "patterns":     patterns,
        "reasons":      reasons,
        "warnings":     warnings,
        "bull_votes":   bull_votes,
        "bear_votes":   bear_votes,
        "tw_status":    tw["status"],
    }


# ═════════════════════════════════════════════════════════════════════════════
# RENDER PRECISION ENTRY PANEL
# ═════════════════════════════════════════════════════════════════════════════
def render_precision_entry_panel(df: pd.DataFrame, ps: dict, interval: str):
    """
    Renders the live precision entry signal panel.
    ps = result of compute_precision_signal()
    """
    action    = ps["action"]
    direction = ps.get("direction", "WAIT")
    score     = ps["signal_score"]
    max_sc    = ps["max_score"]
    score_pct = int((score / max_sc * 100)) if max_sc > 0 else 0

    # Colour palette
    if direction == "CALL":
        bg, border, col, icon = "#0f2e1a", "#10b981", "#10b981", "🟢"
    elif direction == "PUT":
        bg, border, col, icon = "#2e0f0f", "#ef4444", "#ef4444", "🔴"
    else:
        bg, border, col, icon = "#1e1e2e", "#f59e0b", "#f59e0b", "🟡"

    st.markdown(
        """
        <div style='background:{bg};border:2px solid {bd};border-radius:10px;
        padding:16px 20px;margin-bottom:6px'>
          <div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px'>
            <div>
              <span style='font-size:22px;font-weight:900;color:{col}'>{action}</span><br>
              <span style='font-size:12px;color:#94a3b8'>Based on last candle ({ivl}) + RSI, MACD, Supertrend, VWAP, EMA</span>
            </div>
            <div style='text-align:right'>
              <span style='font-size:13px;color:#cbd5e1'>Signal Score</span><br>
              <span style='font-size:20px;font-weight:800;color:{col}'>{sc}/{mx} ({pct}%)</span>
            </div>
          </div>
          <div style='display:flex;gap:20px;margin-top:14px;flex-wrap:wrap'>
            <div style='background:#0f172a;border-radius:8px;padding:10px 16px;min-width:120px;text-align:center'>
              <div style='font-size:11px;color:#64748b;margin-bottom:2px'>⏰ ENTER AT</div>
              <div style='font-size:20px;font-weight:800;color:{col}'>{etime}</div>
            </div>
            <div style='background:#0f172a;border-radius:8px;padding:10px 16px;min-width:120px;text-align:center'>
              <div style='font-size:11px;color:#64748b;margin-bottom:2px'>⚡ EXIT BY (5 min)</div>
              <div style='font-size:18px;font-weight:700;color:#fbbf24'>{e5}</div>
            </div>
            <div style='background:#0f172a;border-radius:8px;padding:10px 16px;min-width:120px;text-align:center'>
              <div style='font-size:11px;color:#64748b;margin-bottom:2px'>🎯 EXIT BY (10 min)</div>
              <div style='font-size:18px;font-weight:700;color:#fbbf24'>{e10}</div>
            </div>
            <div style='background:#0f172a;border-radius:8px;padding:10px 16px;min-width:120px;text-align:center'>
              <div style='font-size:11px;color:#64748b;margin-bottom:2px'>🏁 EXIT BY (15 min)</div>
              <div style='font-size:18px;font-weight:700;color:#fbbf24'>{e15}</div>
            </div>
          </div>
        </div>
        """.format(
            bg=bg, bd=border, col=col, action=action, ivl=interval,
            sc=score, mx=max_sc, pct=score_pct,
            etime=ps["entry_time"], e5=ps["exit_5m"], e10=ps["exit_10m"], e15=ps["exit_15m"],
        ),
        unsafe_allow_html=True,
    )

    # Candle pattern badge
    if ps["pattern_name"] not in ("No clear pattern", "N/A"):
        st.markdown(
            "<div style='background:#1e293b;border:1px solid #334155;border-radius:6px;"
            "padding:8px 14px;margin:6px 0;font-size:13px'>"
            "🕯️ <b>Candle Pattern:</b> <span style='color:#fbbf24'>{}</span> — {}"
            "</div>".format(ps["pattern_name"], ps["pattern_desc"]),
            unsafe_allow_html=True,
        )

    # All detected patterns list
    if ps.get("patterns"):
        all_pats = [p for p in ps["patterns"] if p["signal"] != "WAIT"]
        if all_pats:
            with st.expander("🕯️ All detected candle patterns ({})".format(len(all_pats)), expanded=False):
                for p in all_pats:
                    sig_col = "#10b981" if p["signal"] == "CALL" else "#ef4444"
                    st.markdown(
                        "<span style='color:{col};font-weight:700'>[{sig}]</span> <b>{name}</b> — {desc}"
                        " <span style='font-size:11px;color:#64748b'>({strength})</span>".format(
                            col=sig_col, sig=p["signal"], name=p["name"],
                            desc=p["desc"], strength=p["strength"]),
                        unsafe_allow_html=True,
                    )

    # Reasons & warnings grid
    rc1, rc2 = st.columns(2)
    with rc1:
        if ps["reasons"]:
            st.markdown("**✅ Signal Reasons**")
            for r in ps["reasons"]:
                st.markdown("- " + r)
    with rc2:
        if ps["warnings"]:
            for w in ps["warnings"]:
                st.warning("⚠️ " + w)

    # Mini candlestick chart (last 20 candles) with BUY arrow
    if len(df) >= 5:
        look_back = min(30, len(df))
        df_mini   = df.tail(look_back).copy()
        fig_mini  = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                   vertical_spacing=0.04, row_heights=[0.75, 0.25],
                                   subplot_titles=("Last {} Candles — Signal Point".format(look_back), "Volume"))
        fig_mini.add_trace(go.Candlestick(
            x=df_mini.index,
            open=df_mini["Open"], high=df_mini["High"],
            low=df_mini["Low"],   close=df_mini["Close"],
            name="Price",
            increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        ), row=1, col=1)
        # EMA 9 & 21 on mini chart
        fig_mini.add_trace(go.Scatter(x=df_mini.index, y=df_mini["EMA_9"],  name="EMA9",
                                       line=dict(color="#f39c12", width=1), opacity=0.8), row=1, col=1)
        fig_mini.add_trace(go.Scatter(x=df_mini.index, y=df_mini["EMA_21"], name="EMA21",
                                       line=dict(color="#3498db", width=1), opacity=0.8), row=1, col=1)
        fig_mini.add_trace(go.Scatter(x=df_mini.index, y=df_mini["VWAP"],   name="VWAP",
                                       line=dict(color="#ffffff", width=1, dash="dot"), opacity=0.5), row=1, col=1)
        # Annotate last candle with the signal arrow
        last_ts = df_mini.index[-1]
        last_cl = float(df_mini["Close"].iloc[-1])
        last_hi = float(df_mini["High"].iloc[-1])
        last_lo = float(df_mini["Low"].iloc[-1])
        if direction == "CALL":
            arrow_y     = last_lo * 0.998
            arrow_ay    = -40
            arrow_color = "#10b981"
            arrow_text  = "BUY CALL"
        elif direction == "PUT":
            arrow_y     = last_hi * 1.002
            arrow_ay    = 40
            arrow_color = "#ef4444"
            arrow_text  = "BUY PUT"
        else:
            arrow_y = arrow_ay = None
            arrow_color = arrow_text = None

        if arrow_y is not None:
            fig_mini.add_annotation(
                x=last_ts, y=arrow_y,
                text="<b>{}</b><br>{} IST".format(arrow_text, ps["entry_time"]),
                showarrow=True, arrowhead=2, arrowsize=1.5,
                arrowcolor=arrow_color, ax=0, ay=arrow_ay,
                font=dict(color=arrow_color, size=12),
                bgcolor="#0f172a", bordercolor=arrow_color, borderwidth=1,
            )

        vol_colors_mini = ["#26a69a" if df_mini["Close"].iloc[i] >= df_mini["Open"].iloc[i] else "#ef5350"
                            for i in range(len(df_mini))]
        fig_mini.add_trace(go.Bar(x=df_mini.index, y=df_mini["Volume"],
                                   name="Vol", marker_color=vol_colors_mini, opacity=0.7), row=2, col=1)
        fig_mini.update_layout(
            height=400, template="plotly_dark",
            xaxis_rangeslider_visible=False,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=1, font=dict(size=10)),
            margin=dict(l=0, r=0, t=30, b=0),
        )
        fig_mini.update_yaxes(title_text="Price", row=1, col=1)
        fig_mini.update_yaxes(title_text="Vol",   row=2, col=1)
        st.plotly_chart(fig_mini, use_container_width=True)

    st.caption("⚠️ This is a signal — NOT a guarantee. Always set a SL before entering. Educational use only.")


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

    # ── Precision Entry Signal Panel ──────────────────────────────────────────
    st.subheader("⚡ Precision Entry Signal — BUY NOW with Exit Times")
    st.caption("Reads the current candle pattern + live indicators. Tells you exactly when to enter and exit (5 / 10 / 15 min windows).")
    precision_signal = compute_precision_signal(df_chart, summary, decision, vdict)
    render_precision_entry_panel(df_chart, precision_signal, interval)
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
    fig.add_hrect(y0=0,  y1=35,  fillcolor="rgba(38,166,154,0.08)", line_width=0, row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red",   opacity=0.4, row=2, col=1)
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
    fig.update_yaxes(title_text="RSI",        row=2, col=1, range=[0, 100])
    fig.update_yaxes(title_text="MACD",       row=3, col=1)
    fig.update_yaxes(title_text="Volume",     row=4, col=1)
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
                    "Signal":    {"PUT": "🔴 PUT", "CALL": "🟢 CALL", "WAIT": "🟡 WAIT"}.get(dec.get("direction", "WAIT"), "🟡 WAIT"),
                    "Confidence": "{:.0f}%".format(dec.get("confidence", 0.5) * 100),
                })
            except Exception as _err:
                rows.append({"Symbol": sym, "LTP (Rs)": "Error", "Change %": "-", "RSI": "-",
                             "ADX": "-", "Supertrend": "-", "MACD": "-", "Signal": "-", "Confidence": "-"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.markdown("---")

    st.caption("Data via yfinance. Educational use only. NOT financial advice.")


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
# ██  PAGE: 🎯 GOAL & COMPOUNDING ENGINE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🎯 Goal & Compounding Engine":
    st.title("🎯 Goal Setting & Compounding Engine")
    st.caption("Set your capital target · Choose start & end dates · See your required daily run-rate · Risk guardrails")
    st.markdown("---")

    goal = load_goal_cloud({})
    current_cap = float(goal.get("initial_capital", 50000.0))

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
            help="The initial amount you are trading with"
        )
        c_target = f2.number_input(
            "Target Goal Capital (₹)", min_value=5000.0,
            value=float(goal.get("target_capital", 1000000.0)), step=50000.0,
            help="Final target (e.g. 1000000 = ₹10 Lakh)"
        )

        try:
            def_start = datetime.strptime(goal.get("start_date", datetime.today().strftime("%Y-%m-%d")), "%Y-%m-%d").date()
        except Exception:
            def_start = datetime.today().date()
        try:
            def_end = datetime.strptime(goal.get("target_date", (datetime.today() + timedelta(days=180)).strftime("%Y-%m-%d")), "%Y-%m-%d").date()
        except Exception:
            def_end = (datetime.today() + timedelta(days=180)).date()

        d_col1, d_col2, d_col3 = st.columns(3)
        c_start_date  = d_col1.date_input("📅 Start Date", value=def_start)
        c_target_date = d_col2.date_input("🏁 Target Completion Date", value=def_end)
        calc_days   = max(1, (c_target_date - c_start_date).days)
        calc_months = round(calc_days / 30.4, 1)
        d_col3.metric("📆 Calculated Duration", f"{calc_months} Months", f"{calc_days} calendar days")

        st.markdown("**🛡️ Risk Guardrails**")
        r1, r2, r3 = st.columns(3)
        c_risk = r1.slider("Max Risk Per Trade (%)", min_value=0.5, max_value=5.0,
                           value=float(goal.get("risk_per_trade_pct", 1.5)), step=0.1)
        c_rr   = r2.slider("Target Risk:Reward (1:X)", min_value=1.0, max_value=5.0,
                           value=float(goal.get("risk_reward_ratio", 2.0)), step=0.5)
        c_loss = r3.slider("Max Daily Drawdown Stop (%)", min_value=1.0, max_value=10.0,
                           value=float(goal.get("max_daily_loss_pct", 3.0)), step=0.5)

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
            save_goal_cloud(new_goal)
            st.success(f"🎉 Goal '{c_name}' activated! Target: ₹{c_target:,.0f} by {c_target_date.strftime('%d %b %Y')}.")
            st.rerun()

    st.markdown("---")
    goal = load_goal_cloud({})
    eval_res = evaluate_goal_progress(goal, current_cap)

    g1, g2, g3, g4 = st.columns(4)
    g1.metric("🎯 Target Capital",    f"₹{eval_res['target_capital']:,.0f}",  f"Initial: ₹{eval_res['initial_capital']:,.0f}")
    g2.metric("💰 Current Capital",   f"₹{eval_res['current_capital']:,.0f}", f"{eval_res['progress_pct']}% Achieved")
    g3.metric("⏳ Trading Days Left", f"{eval_res['trading_days_remaining']} Days", f"{eval_res['trading_days_elapsed']} elapsed")
    g4.metric("📈 Required Daily Run",f"+{eval_res['daily_rate_pct']}% / day", f"~{eval_res['monthly_rate_pct']}% / mo")


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

st.markdown("---")
st.caption("📈 Nifty F&O Signal Dashboard | Data via yfinance | Educational & personal use only")
