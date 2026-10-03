"""
My Trading Records — Streamlit Cloud App
Hosted on Streamlit Cloud — works on mobile, tablet, any device.
Data stored in Google Sheets (cloud) — safe even if laptop is lost.
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from io import BytesIO

import streamlit as st
import plotly.graph_objects as go
from angel_sync import render_angel_sync_panel

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="My Trading Records",
    page_icon="📒",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
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

# ─────────────────────────────────────────────────────────────────────────────
# Google Sheets helpers
# ─────────────────────────────────────────────────────────────────────────────
def _get_conn():
    try:
        if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
            from streamlit_gsheets import GSheetsConnection
            return st.connection("gsheets", type=GSheetsConnection)
    except Exception:
        pass
    return None


@st.cache_data(ttl=5, show_spinner=False)
def load_trades() -> pd.DataFrame:
    conn = _get_conn()
    if conn:
        try:
            df = conn.read(worksheet="Trades", ttl="0s")
            if df is not None and not df.empty:
                for col in COLUMNS:
                    if col not in df.columns:
                        df[col] = ""
                return df[COLUMNS]
        except Exception:
            pass
    return pd.DataFrame(columns=COLUMNS)


@st.cache_data(ttl=5, show_spinner=False)
def load_capital() -> dict:
    conn = _get_conn()
    if conn:
        try:
            cdf = conn.read(worksheet="Capital", ttl="0s")
            if cdf is not None and not cdf.empty:
                row = cdf.iloc[0].to_dict()
                hist_raw = row.get("history_json", "[]")
                history = json.loads(hist_raw) if isinstance(hist_raw, str) else []
                return {
                    "initial_capital": float(row.get("initial_capital", 40000.0)),
                    "current_capital": float(row.get("current_capital", 40000.0)),
                    "start_date":      str(row.get("start_date", "2025-01-01")),
                    "notes":           str(row.get("notes", "")),
                    "history":         history,
                }
        except Exception:
            pass
    return {
        "initial_capital": 40000.0,
        "current_capital": 40000.0,
        "start_date":      "2025-01-01",
        "notes":           "Started trading Nifty F&O options",
        "history":         [{"date": "2025-01-01", "balance": 40000.0, "note": "Initial capital"}],
    }


def save_trades(df: pd.DataFrame):
    conn = _get_conn()
    if conn:
        try:
            conn.update(worksheet="Trades", data=df)
            st.cache_data.clear()
        except Exception as e:
            st.error("Could not save to Google Sheets: {}".format(e))


def save_capital(data: dict):
    conn = _get_conn()
    if conn:
        try:
            cdf = pd.DataFrame([{
                "initial_capital": data.get("initial_capital", 40000.0),
                "current_capital": data.get("current_capital", 40000.0),
                "start_date":      data.get("start_date", "2025-01-01"),
                "notes":           data.get("notes", ""),
                "history_json":    json.dumps(data.get("history", [])),
            }])
            conn.update(worksheet="Capital", data=cdf)
            st.cache_data.clear()
        except Exception as e:
            st.error("Could not save capital: {}".format(e))


def delete_trade_entry(df: pd.DataFrame, trade_num: int, cap_data: dict) -> tuple:
    """Remove trade row and reverse capital. Returns (new_df, new_cap_data, status_msg)."""
    mask  = pd.to_numeric(df["Trade #"], errors="coerce") == trade_num
    if not mask.any():
        return df, cap_data, "Trade #{} not found.".format(trade_num)
    trade  = df[mask].iloc[0]
    result = str(trade.get("Result", ""))
    try:
        net = float(trade.get("Net P&L", 0) or 0)
    except Exception:
        net = 0.0
    new_df = df[~mask].reset_index(drop=True)
    msg = "✅ Trade #{} deleted (OPEN — no capital change).".format(trade_num)
    if result in ("WIN", "LOSS") and net != 0.0:
        current = cap_data.get("current_capital", 40000.0)
        new_bal = round(current - net, 2)
        cap_data.setdefault("history", []).append({
            "date":    datetime.now().strftime("%Y-%m-%d"),
            "balance": new_bal,
            "note":    "Deleted Trade #{} {} | Reversed Rs {:,.0f}".format(trade_num, result, net),
        })
        cap_data["current_capital"] = new_bal
        msg = "✅ Trade #{} deleted & capital reversed. New Balance: Rs {:,.0f}".format(trade_num, new_bal)
    return new_df, cap_data, msg


# ─────────────────────────────────────────────────────────────────────────────
# Stats helpers
# ─────────────────────────────────────────────────────────────────────────────
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
    return {
        "initial": initial, "current": current,
        "pnl": pnl, "pnl_pct": pct,
        "days": days, "history": data.get("history", []),
    }


def pnl_delta(val):
    return ("▲ Rs {:,.0f}".format(val) if val >= 0 else "▼ Rs {:,.0f}".format(abs(val)),
            "normal" if val >= 0 else "inverse")


def _next_trade_num(df):
    if df.empty or df["Trade #"].isna().all():
        return 1
    return int(pd.to_numeric(df["Trade #"], errors="coerce").max()) + 1


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
st.sidebar.image("https://img.icons8.com/color/96/combo-chart.png", width=60)
st.sidebar.title("My Trading Records")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Go to",
    ["📊 Dashboard", "💰 My Capital", "📓 Log Trade", "🔄 Angel One Sync",
     "📋 All Trades", "📅 Monthly Report", "📈 Performance", "💸 Expenses", "⬇️ Export"],
)
st.sidebar.markdown("---")
conn_ok = _get_conn() is not None
if conn_ok:
    st.sidebar.success("☁️ Storage: **Google Sheets (Live Cloud)**")
else:
    st.sidebar.error("⚠️ Google Sheets not connected.\nAdd secrets in Streamlit Cloud settings.")

# ─────────────────────────────────────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────────────────────────────────────
df        = load_trades()
stats     = get_stats(df)
cap_data  = load_capital()
cap_stats = get_capital_stats(cap_data)
closed_df = df[df["Result"].isin(["WIN", "LOSS"])].copy() if not df.empty else pd.DataFrame()


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 1 — DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
if page == "📊 Dashboard":
    st.title("📊 My Trading Dashboard")
    st.caption("Your personal performance overview — updated live from Google Sheets.")
    st.markdown("---")

    remaining_pct = (cap_stats["current"] / cap_stats["initial"] * 100) if cap_stats["initial"] else 0
    cap_d, cap_dc = pnl_delta(cap_stats["pnl"])
    cc1, cc2, cc3, cc4, cc5 = st.columns(5)
    cc1.metric("💰 Initial Capital",  "Rs {:,.0f}".format(cap_stats["initial"]))
    cc2.metric("💵 Current Balance",  "Rs {:,.0f}".format(cap_stats["current"]), cap_d, delta_color=cap_dc)
    cc3.metric("📉 Total P&L",        "Rs {:,.0f}".format(abs(cap_stats["pnl"])),
               "{:.1f}%".format(cap_stats["pnl_pct"]),
               delta_color="normal" if cap_stats["pnl"] >= 0 else "inverse")
    cc4.metric("📅 Days Trading",     "{} days".format(cap_stats["days"]))
    cc5.metric("🏦 Capital Remaining","{:.1f}%".format(remaining_pct),
               delta_color="normal" if remaining_pct >= 80 else "inverse")

    prog_color = "🟢" if remaining_pct >= 80 else ("🟡" if remaining_pct >= 60 else "🔴")
    st.progress(min(int(remaining_pct), 100),
                text="{} Rs {:,.0f} remaining of Rs {:,.0f} ({}%)".format(
                    prog_color, cap_stats["current"], cap_stats["initial"], round(remaining_pct, 1)))
    st.markdown("---")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Trades",  stats["total_trades"])
    k2.metric("Win Rate",      "{:.1f}%".format(stats["win_rate"]))
    d, dc = pnl_delta(stats["total_pnl"])
    k3.metric("Net P&L (All Time)", "Rs {:,.0f}".format(stats["total_pnl"]), d, delta_color=dc)
    k4.metric("Reward : Risk", "{:.2f}".format(stats["reward_risk"]),
              "Good" if stats["reward_risk"] >= 1.5 else "Needs improvement")

    k5, k6, k7, k8 = st.columns(4)
    k5.metric("Wins",        stats["wins"])
    k6.metric("Losses",      stats["losses"], delta_color="inverse")
    k7.metric("Best Trade",  "Rs {:,.0f}".format(stats["best_trade"]))
    k8.metric("Worst Trade", "Rs {:,.0f}".format(stats["worst_trade"]))
    st.markdown("---")

    if not closed_df.empty:
        pnl_series = pd.to_numeric(closed_df["Net P&L"], errors="coerce").fillna(0)
        col_left, col_right = st.columns([3, 2])
        with col_left:
            equity     = pnl_series.cumsum().reset_index(drop=True)
            trade_nums = list(range(1, len(equity) + 1))
            colors     = ["#26a69a" if v >= 0 else "#ef5350" for v in pnl_series]
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=trade_nums, y=equity, mode="lines+markers",
                line=dict(color="#3498db", width=2.5),
                marker=dict(color=colors, size=9),
                hovertemplate="Trade %{x}<br>Cumulative P&L: Rs %{y:,.0f}<extra></extra>",
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.3)")
            fig.update_layout(template="plotly_dark", height=320, title="📈 Equity Curve",
                              xaxis_title="Trade Number", yaxis_title="Cumulative P&L (Rs)",
                              margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig, width="stretch")
        with col_right:
            pie = go.Figure(go.Pie(
                labels=["Wins", "Losses"], values=[stats["wins"], stats["losses"]],
                marker=dict(colors=["#26a69a", "#ef5350"]), hole=0.5,
                textinfo="label+percent",
            ))
            pie.update_layout(template="plotly_dark", height=320, title="🏆 Win / Loss Ratio",
                              margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
            st.plotly_chart(pie, width="stretch")

        if "Date" in closed_df.columns:
            closed_df["Month"] = pd.to_datetime(closed_df["Date"], errors="coerce").dt.strftime("%b %Y")
            monthly = closed_df.groupby("Month")["Net P&L"].apply(
                lambda x: pd.to_numeric(x, errors="coerce").sum()).reset_index()
            bar_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in monthly["Net P&L"]]
            bar_fig = go.Figure(go.Bar(
                x=monthly["Month"], y=monthly["Net P&L"], marker_color=bar_colors,
                text=["Rs {:,.0f}".format(v) for v in monthly["Net P&L"]], textposition="outside",
            ))
            bar_fig.update_layout(template="plotly_dark", height=300, title="📅 Monthly Net P&L",
                                  xaxis_title="Month", yaxis_title="Net P&L (Rs)",
                                  margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(bar_fig, width="stretch")

        st.markdown("#### 🕐 Last 5 Trades")
        recent_cols = ["Trade #", "Date", "Symbol", "Option Type", "Strike",
                       "Entry Price", "Exit Price", "Net P&L", "Result"]
        st.dataframe(df[recent_cols].tail(5).sort_index(ascending=False),
                     width="stretch", hide_index=True)
    else:
        st.info("No closed trades yet. Go to **📓 Log Trade** to record your first trade!")


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 2 — MY CAPITAL
# ═════════════════════════════════════════════════════════════════════════════
elif page == "💰 My Capital":
    st.title("💰 My Capital Tracker")
    st.markdown("---")

    remaining_pct = (cap_stats["current"] / cap_stats["initial"] * 100) if cap_stats["initial"] else 0
    cap_d, cap_dc = pnl_delta(cap_stats["pnl"])
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("💰 Initial Capital", "Rs {:,.0f}".format(cap_stats["initial"]))
    c2.metric("💵 Current Balance", "Rs {:,.0f}".format(cap_stats["current"]), cap_d, delta_color=cap_dc)
    c3.metric("📊 P&L",             "Rs {:,.0f}".format(cap_stats["pnl"]),
              "{:.2f}%".format(cap_stats["pnl_pct"]),
              delta_color="normal" if cap_stats["pnl"] >= 0 else "inverse")
    c4.metric("📅 Days Trading",    "{} days".format(cap_stats["days"]))
    c5.metric("🏦 Capital Left",    "{:.1f}%".format(remaining_pct),
              delta_color="normal" if remaining_pct >= 80 else "inverse")

    prog_color = "🟢" if remaining_pct >= 80 else ("🟡" if remaining_pct >= 60 else "🔴")
    st.progress(min(int(remaining_pct), 100),
                text="{} Rs {:,.0f} of Rs {:,.0f} remaining ({:.1f}%)".format(
                    prog_color, cap_stats["current"], cap_stats["initial"], remaining_pct))
    st.markdown("---")

    with st.expander("⚙️ Update Capital Settings", expanded=False):
        with st.form("capital_form"):
            sf1, sf2, sf3 = st.columns(3)
            new_initial = sf1.number_input("Initial Capital (Rs)",
                                           value=float(cap_data.get("initial_capital", 40000)), step=1000.0, format="%.0f")
            new_current = sf2.number_input("Current Balance (Rs)",
                                           value=float(cap_data.get("current_capital", 40000)), step=100.0, format="%.0f")
            new_start   = sf3.text_input("Start Date", value=cap_data.get("start_date", "2025-01-01"))
            new_note    = st.text_input("Note", placeholder="e.g. Added Rs 10,000 top-up")
            if st.form_submit_button("💾 Save Capital Settings"):
                cap_data["initial_capital"] = new_initial
                cap_data["current_capital"] = round(new_current, 2)
                cap_data["start_date"]      = new_start
                cap_data.setdefault("history", []).append({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "balance": round(new_current, 2),
                    "note": new_note if new_note else "Manual update",
                })
                save_capital(cap_data)
                st.success("Capital updated! Current balance: Rs {:,.0f}".format(new_current))
                st.rerun()

    history = cap_stats.get("history", [])
    if history:
        hist_df = pd.DataFrame(history)
        hist_df["date"]    = pd.to_datetime(hist_df["date"], errors="coerce")
        hist_df["balance"] = pd.to_numeric(hist_df["balance"], errors="coerce")
        hist_df = hist_df.sort_values("date").reset_index(drop=True)
        fig_cap = go.Figure()
        fig_cap.add_trace(go.Scatter(
            x=hist_df["date"], y=hist_df["balance"], mode="lines+markers",
            line=dict(color="#3498db", width=2.5), fill="tozeroy",
            fillcolor="rgba(52,152,219,0.08)", marker=dict(size=8, color="#3498db"),
            hovertemplate="%{x|%d %b %Y}<br>Balance: Rs %{y:,.0f}<extra></extra>",
        ))
        fig_cap.add_hline(y=cap_stats["initial"], line_dash="dash",
                          line_color="rgba(255,255,255,0.4)",
                          annotation_text="Initial: Rs {:,.0f}".format(cap_stats["initial"]),
                          annotation_position="bottom right")
        fig_cap.update_layout(template="plotly_dark", height=350,
                              title="💵 Capital Balance Over Time",
                              xaxis_title="Date", yaxis_title="Balance (Rs)",
                              margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_cap, width="stretch")
        st.subheader("📋 Balance History")
        st.dataframe(hist_df[["date","balance","note"]].rename(
            columns={"date":"Date","balance":"Balance (Rs)","note":"Note"}
        ).sort_values("Date", ascending=False), width="stretch", hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 3 — LOG TRADE
# ═════════════════════════════════════════════════════════════════════════════
elif page == "📓 Log Trade":
    st.title("📓 Log a Trade")
    st.caption("Every trade is saved permanently to Google Sheets ☁️")
    st.markdown("---")

    # ── Enter-key → move to next field (prevents form submission on Enter) ────
    st.markdown("""
<script>
(function() {
    function attachEnterNav() {
        var inputs = Array.from(document.querySelectorAll(
            'input[type="number"], input[type="text"]'
        )).filter(function(el) {
            return el.closest('[data-testid="stNumberInput"], [data-testid="stTextInput"]');
        });
        inputs.forEach(function(el, idx) {
            el.removeAttribute('data-enter-nav');
            el.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    e.stopPropagation();
                    var next = inputs[idx + 1];
                    if (next) { next.focus(); next.select(); }
                }
            });
            el.setAttribute('data-enter-nav', '1');
        });
    }
    // Run once on load and again after Streamlit re-renders
    setTimeout(attachEnterNav, 800);
    var observer = new MutationObserver(function() { setTimeout(attachEnterNav, 300); });
    observer.observe(document.body, { childList: true, subtree: true });
})();
</script>
""", unsafe_allow_html=True)


    st.subheader("Trade Details")
    c1, c2, c3, c4 = st.columns(4)
    f_symbol  = c1.text_input("Symbol",           value="NIFTY50", key="lt_sym")
    f_type    = c2.selectbox("PUT / CALL",         ["PUT", "CALL"], key="lt_type")
    f_strike  = c3.number_input("Strike",          value=22500, step=50, key="lt_strike")
    f_expiry  = c4.text_input("Expiry",            placeholder="e.g. 06 Jun 2025", key="lt_expiry")

    c5, c6, c7, c8, c9 = st.columns([2, 2, 1, 1, 1])
    f_entry   = c5.number_input("Entry Price (Rs)", value=0.0, step=0.05, format="%.2f", min_value=0.0, key="lt_entry")
    f_exit    = c6.number_input("Exit Price (Rs) — 0 if still open", value=0.0, step=0.05, format="%.2f", min_value=0.0, key="lt_exit")
    f_lots    = c7.number_input("Lots",            value=1, step=1, min_value=1, key="lt_lots")
    f_lotsize = c8.number_input("Lot Size",        value=75, step=1, min_value=1, key="lt_lotsize")
    calc_qty  = int(f_lots * f_lotsize)
    c9.metric("Total Qty", f"{calc_qty:,}")

    st.subheader("Market Conditions at Entry")
    m1, m2, m3, m4 = st.columns(4)
    f_rsi    = m1.number_input("RSI at Entry",  value=50.0, step=0.1, format="%.1f", min_value=0.0, max_value=100.0, key="lt_rsi")
    f_adx    = m2.number_input("ADX at Entry",  value=25.0, step=0.1, format="%.1f", min_value=0.0, max_value=100.0, key="lt_adx")
    f_st     = m3.selectbox("Supertrend",       ["BEARISH", "BULLISH"], key="lt_st")
    f_dsaid  = m4.selectbox("Dashboard Said",   ["WAIT", "PUT", "CALL"], key="lt_dsaid")

    st.subheader("Notes & Learning")
    n1, n2 = st.columns(2)
    f_hold    = n1.text_input("Hold Time",       placeholder="e.g. 45 min", key="lt_hold")
    f_lessons = n2.text_input("Lessons Learned", placeholder="e.g. Never enter when RSI < 35", key="lt_lessons")
    st.markdown("**📝 Trade Notes / Observations (Saved to Records):**")
    f_notes   = st.text_area("Additional Notes", placeholder="What did you observe? Why did you enter?", height=90, key="lt_notes", label_visibility="collapsed")

    st.subheader("Charges")
    ch1, ch2, ch3 = st.columns(3)
    f_brok  = ch1.number_input("Brokerage (Rs)",    value=DEFAULT_BROKERAGE, step=1.0, min_value=0.0, key="lt_brok")
    f_other = ch3.number_input("Other Charges (Rs)", value=DEFAULT_OTHER,    step=1.0, min_value=0.0, key="lt_other")

    st.markdown("---")
    cap_preview = round(f_entry * f_lots * f_lotsize, 2)
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Symbol / Strike", f"{f_symbol} {int(f_strike)} {f_type}")
    p2.metric("Total Quantity", f"{calc_qty:,} ({f_lots} lots)")
    p3.metric("Entry Price", f"Rs {f_entry:,.2f}")
    p4.metric("Capital Required", f"Rs {cap_preview:,.2f}")

    if f_entry <= 0:
        st.warning("⚠️ Please fill in an **Entry Price > 0** before clicking save.")

    submitted = st.button("💾 Save Trade to Cloud", use_container_width=True, type="primary")

    if submitted:
        if f_entry <= 0:
            st.error("Entry Price must be greater than 0.")
        else:
            now     = datetime.now()
            capital = round(f_entry * f_lots * f_lotsize, 2)
            gross   = round((f_exit - f_entry) * f_lots * f_lotsize, 2) if f_exit > 0 else 0.0
            stt     = round(f_exit * f_lots * f_lotsize * DEFAULT_STT_PCT / 100, 2) if f_exit > 0 else 0.0
            other   = DEFAULT_OTHER if f_exit > 0 else 0.0
            net     = round(gross - f_brok - stt - other, 2) if f_exit > 0 else 0.0
            result  = "OPEN" if f_exit <= 0 else ("WIN" if net >= 0 else "LOSS")
            row = {
                "Trade #":        _next_trade_num(df),
                "Date":           now.strftime("%Y-%m-%d"),
                "Time":           now.strftime("%H:%M"),
                "Symbol":         f_symbol,
                "Option Type":    f_type,
                "Strike":         int(f_strike),
                "Expiry":         f_expiry,
                "Entry Price":    f_entry,
                "Exit Price":     f_exit if f_exit > 0 else "",
                "Lots":           int(f_lots),
                "Lot Size":       int(f_lotsize),
                "Capital Used":   capital,
                "Gross P&L":      gross  if f_exit > 0 else "",
                "Brokerage":      f_brok if f_exit > 0 else "",
                "STT":            stt    if f_exit > 0 else "",
                "Other Charges":  other  if f_exit > 0 else "",
                "Net P&L":        net    if f_exit > 0 else "",
                "Result":         result,
                "Hold Time":      f_hold,
                "Entry RSI":      round(f_rsi, 1) if f_rsi else "",
                "Entry ADX":      round(f_adx, 1) if f_adx else "",
                "Supertrend":     f_st,
                "Dashboard Said": f_dsaid,
                "Lessons Learned":f_lessons,
                "Notes":          f_notes,
            }
            new_df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            save_trades(new_df)

            # ── Auto-update capital when trade is closed ───────────────────────
            if result in ("WIN", "LOSS"):
                current_bal = cap_stats["current"]
                new_bal     = round(current_bal + net, 2)
                cap_data.setdefault("history", []).append({
                    "date":    now.strftime("%Y-%m-%d"),
                    "balance": new_bal,
                    "note":    "Trade #{} {} {} {} | Net P&L: Rs {:,.0f}".format(
                        row["Trade #"], result, f_symbol, f_type, net),
                })
                cap_data["current_capital"] = new_bal
                save_capital(cap_data)

            emoji = "✅ WIN" if result == "WIN" else ("❌ LOSS" if result == "LOSS" else "📂 OPEN")
            pnl_msg = "Rs {:,.0f}".format(net) if f_exit > 0 else "Open"
            if result in ("WIN", "LOSS"):
                bal_msg = " | New Balance: Rs {:,.0f}".format(cap_data["current_capital"])
            else:
                bal_msg = ""
            st.success("Trade #{} saved to cloud! {} | Net P&L: {}{}".format(
                row["Trade #"], emoji, pnl_msg, bal_msg))
            st.cache_data.clear()
            st.rerun()

    # ── Recent Trades Log + Delete ─────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📋 Recent Trades Log")
    if df.empty:
        st.info("No trades logged yet.")
    else:
        show_cols = ["Trade #", "Date", "Symbol", "Option Type", "Strike",
                     "Entry Price", "Exit Price", "Lots", "Net P&L", "Result"]
        recent = df[show_cols].sort_values("Trade #", ascending=False).head(20)
        st.dataframe(recent, use_container_width=True, hide_index=True)

        st.markdown("#### 🗑️ Delete a Trade")
        st.caption("⚠️ Deleting a closed trade will also reverse its impact on your capital balance.")
        del_col1, del_col2 = st.columns([2, 1])
        trade_labels = [
            "#{} — {} {} {} | {}".format(
                int(r["Trade #"]), r["Date"], r["Symbol"],
                r["Option Type"], r["Result"])
            for _, r in df.sort_values("Trade #", ascending=False).iterrows()
        ]
        sel_label = del_col1.selectbox("Select trade to delete", trade_labels, key="lt_del_sel")
        sel_num   = int(sel_label.split(" — ")[0].replace("#", "").strip())

        if del_col2.button("🗑️ Delete Selected Trade", type="secondary", use_container_width=True, key="lt_del_btn"):
            fresh_cap = load_capital()
            new_df, new_cap, msg = delete_trade_entry(df, sel_num, fresh_cap)
            save_trades(new_df)
            save_capital(new_cap)
            st.success(msg)
            st.cache_data.clear()
            st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 4 — ANGEL ONE SYNC
# ═════════════════════════════════════════════════════════════════════════════
elif page == "🔄 Angel One Sync":
    st.title("🔄 Angel One Auto-Sync")
    st.caption("Automatically fetch your executed trades from Angel One — no manual entry needed!")
    st.markdown("---")
    render_angel_sync_panel(
        load_fn=load_trades,
        save_fn=save_trades,
        columns=COLUMNS,
    )


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 5 — ALL TRADES
# ═════════════════════════════════════════════════════════════════════════════
elif page == "📋 All Trades":
    st.title("📋 All Trades")
    if df.empty:
        st.info("No trades yet. Log your first trade from **📓 Log Trade**.")
    else:
        fc1, fc2, fc3 = st.columns(3)
        syms    = ["All"] + sorted(df["Symbol"].dropna().unique().tolist())
        filt_sym  = fc1.selectbox("Symbol",      syms)
        filt_type = fc2.selectbox("Option Type", ["All", "PUT", "CALL"])
        filt_res  = fc3.selectbox("Result",      ["All", "WIN", "LOSS", "OPEN"])
        view = df.copy()
        if filt_sym  != "All": view = view[view["Symbol"]      == filt_sym]
        if filt_type != "All": view = view[view["Option Type"] == filt_type]
        if filt_res  != "All": view = view[view["Result"]      == filt_res]
        st.caption("{} trades shown".format(len(view)))
        st.dataframe(view.sort_values("Trade #", ascending=False), width="stretch", hide_index=True)
        if not view.empty:
            pnl_tot = pd.to_numeric(view["Net P&L"], errors="coerce").sum()
            d, dc   = pnl_delta(pnl_tot)
            t1, t2  = st.columns(2)
            t1.metric("Net P&L (filtered)", "Rs {:,.0f}".format(pnl_tot), d, delta_color=dc)
            t2.metric("Capital Used (filtered)", "Rs {:,.0f}".format(
                pd.to_numeric(view["Capital Used"], errors="coerce").sum()))


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 5 — MONTHLY REPORT
# ═════════════════════════════════════════════════════════════════════════════
elif page == "📅 Monthly Report":
    st.title("📅 Monthly P&L Report")
    st.markdown("---")
    if closed_df.empty:
        st.info("No closed trades yet.")
    else:
        closed_df["_month"] = pd.to_datetime(closed_df["Date"], errors="coerce").dt.to_period("M")
        months    = sorted(closed_df["_month"].dropna().unique(), reverse=True)
        sel_month = st.selectbox("Select Month",
                                 options=[str(m) for m in months] + ["All Time"], index=0)
        view = closed_df.copy() if sel_month == "All Time" else \
               closed_df[closed_df["_month"].astype(str) == sel_month].copy()
        title_str = sel_month
        pnl_s   = pd.to_numeric(view["Net P&L"],      errors="coerce").fillna(0)
        gross_w = pd.to_numeric(view[view["Result"] == "WIN"]["Gross P&L"],  errors="coerce").sum()
        gross_l = pd.to_numeric(view[view["Result"] == "LOSS"]["Gross P&L"], errors="coerce").sum()
        brok    = pd.to_numeric(view["Brokerage"],     errors="coerce").sum()
        stt_v   = pd.to_numeric(view["STT"],           errors="coerce").sum()
        other   = pd.to_numeric(view["Other Charges"], errors="coerce").sum()
        net     = pnl_s.sum()
        cap     = pd.to_numeric(view["Capital Used"],  errors="coerce").sum()
        w_count = (view["Result"] == "WIN").sum()
        l_count = (view["Result"] == "LOSS").sum()
        total   = len(view)
        st.subheader("📄 P&L Statement — {}".format(title_str))
        st.markdown("""
<style>
.pnl-box{{background:#1e2130;border-radius:10px;padding:20px 30px;font-family:monospace;font-size:15px;line-height:2.0}}
.pnl-pos{{color:#26a69a;font-weight:bold}}.pnl-neg{{color:#ef5350;font-weight:bold}}
.pnl-head{{color:#3498db;font-weight:bold;font-size:16px}}.pnl-div{{border-top:1px solid #444;margin:8px 0}}
</style>
<div class="pnl-box">
<span class="pnl-head">TRADING P&L STATEMENT — {title}</span><br>
<div class="pnl-div"></div>
Total Trades: <b>{total}</b> &nbsp; Wins: <span class="pnl-pos">{wins}</span> &nbsp; Losses: <span class="pnl-neg">{losses}</span> &nbsp; Win Rate: <b>{wr:.1f}%</b>
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
Total Capital Used : Rs {cap:,.2f}
</div>""".format(title=title_str, total=total, wins=w_count, losses=l_count,
                 wr=(w_count/total*100) if total else 0,
                 gw=gross_w, gl=abs(gross_l), brok=brok, stt=stt_v,
                 other=other, net=net, cap=cap,
                 cls="pnl-pos" if net >= 0 else "pnl-neg"),
                    unsafe_allow_html=True)
        st.markdown("---")
        st.dataframe(view[["Trade #","Date","Symbol","Option Type","Strike",
                            "Entry Price","Exit Price","Lots","Capital Used",
                            "Net P&L","Result"]].sort_values("Trade #", ascending=False),
                     width="stretch", hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 6 — PERFORMANCE
# ═════════════════════════════════════════════════════════════════════════════
elif page == "📈 Performance":
    st.title("📈 Performance Analysis")
    st.markdown("---")
    if closed_df.empty:
        st.info("No closed trades yet.")
    else:
        s = stats
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)
        r1c1.metric("Total Trades", s["total_trades"])
        r1c2.metric("Win Rate",     "{:.1f}%".format(s["win_rate"]))
        r1c3.metric("Avg Win",      "Rs {:,.0f}".format(s["avg_win"]))
        r1c4.metric("Avg Loss",     "Rs {:,.0f}".format(abs(s["avg_loss"])))
        r2c1, r2c2, r2c3, r2c4 = st.columns(4)
        r2c1.metric("Reward:Risk",  "{:.2f}x".format(s["reward_risk"]))
        r2c2.metric("Max Drawdown", "Rs {:,.0f}".format(abs(s["max_drawdown"])))
        r2c3.metric("Best Trade",   "Rs {:,.0f}".format(s["best_trade"]))
        r2c4.metric("Worst Trade",  "Rs {:,.0f}".format(s["worst_trade"]))
        st.markdown("---")
        tab_sym, tab_type = st.tabs(["By Symbol", "PUT vs CALL"])
        with tab_sym:
            sg = closed_df.groupby("Symbol").apply(lambda g: pd.Series({
                "Trades":    len(g),
                "Wins":      (g["Result"] == "WIN").sum(),
                "Net P&L":   pd.to_numeric(g["Net P&L"], errors="coerce").sum().round(2),
                "Win Rate %":round((g["Result"] == "WIN").sum() / len(g) * 100, 1),
            })).reset_index()
            st.dataframe(sg, width="stretch", hide_index=True)
        with tab_type:
            tg = closed_df.groupby("Option Type").apply(lambda g: pd.Series({
                "Trades":    len(g),
                "Wins":      (g["Result"] == "WIN").sum(),
                "Net P&L":   pd.to_numeric(g["Net P&L"], errors="coerce").sum().round(2),
                "Win Rate %":round((g["Result"] == "WIN").sum() / len(g) * 100, 1),
            })).reset_index()
            st.dataframe(tg, width="stretch", hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 7 — EXPENSES
# ═════════════════════════════════════════════════════════════════════════════
elif page == "💸 Expenses":
    st.title("💸 Charges & Expenses")
    st.markdown("---")
    if closed_df.empty:
        st.info("No closed trades yet.")
    else:
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("Total Brokerage",    "Rs {:,.2f}".format(stats["total_brokerage"]))
        e2.metric("Total STT",          "Rs {:,.2f}".format(pd.to_numeric(closed_df["STT"],errors="coerce").sum()))
        e3.metric("Other Charges",      "Rs {:,.2f}".format(pd.to_numeric(closed_df["Other Charges"],errors="coerce").sum()))
        e4.metric("Total Charges Paid", "Rs {:,.2f}".format(stats["total_charges"]))
        gross_pnl = pd.to_numeric(closed_df["Gross P&L"], errors="coerce").sum()
        fig_exp = go.Figure(go.Bar(
            x=["Gross P&L", "Total Charges", "Net P&L"],
            y=[gross_pnl, -stats["total_charges"], stats["total_pnl"]],
            marker_color=["#3498db","#e74c3c","#26a69a" if stats["total_pnl"]>=0 else "#ef5350"],
            text=["Rs {:,.0f}".format(v) for v in [gross_pnl, stats["total_charges"], stats["total_pnl"]]],
            textposition="outside",
        ))
        fig_exp.update_layout(template="plotly_dark", height=350,
                              title="Gross P&L vs Charges vs Net P&L",
                              yaxis_title="Amount (Rs)", margin=dict(l=0,r=0,t=40,b=0))
        st.plotly_chart(fig_exp, width="stretch")


# ═════════════════════════════════════════════════════════════════════════════
# PAGE 8 — EXPORT
# ═════════════════════════════════════════════════════════════════════════════
elif page == "⬇️ Export":
    st.title("⬇️ Export Reports")
    st.markdown("---")
    if df.empty:
        st.info("No trades yet to export.")
    else:
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        today = datetime.now().strftime("%Y%m%d")
        st.download_button(
            label="⬇️ Download CSV (All Trades)",
            data=csv_bytes,
            file_name="My_Trades_{}.csv".format(today),
            mime="text/csv",
            width="stretch",
        )
        st.info("Your data is safely stored in Google Sheets ☁️ — no laptop needed!")


# Footer
st.markdown("---")
st.caption("📒 My Personal Trading Records | Cloud Edition | Not financial advice")
