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
        "📰 Market News & Verdict",
    ],
    index=0,
)
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

st.markdown("---")
st.caption("📈 Nifty F&O Signal Dashboard | Data via yfinance | Educational & personal use only")
