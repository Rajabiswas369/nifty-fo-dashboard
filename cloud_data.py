"""
cloud_data.py — Supabase backend for persistent cloud storage.
All trades and capital are stored in Supabase (free, no card needed).
Falls back to in-memory storage if Supabase is not configured yet.
"""

import streamlit as st
import pandas as pd
from datetime import datetime

# ── Column schema ─────────────────────────────────────────────────────────────
TRADE_COLUMNS = [
    "Trade #", "Date", "Time", "Symbol", "Option Type", "Strike", "Expiry",
    "Entry Price", "Exit Price", "Lots", "Lot Size", "Capital Used",
    "Gross P&L", "Brokerage", "STT", "Other Charges", "Net P&L", "Result",
    "Hold Time", "Entry RSI", "Entry ADX", "Supertrend", "Dashboard Said",
    "Lessons Learned", "Notes",
]

CAPITAL_COLUMNS = ["Date", "Balance", "Note"]

# Display name → Supabase column name
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
# Reverse map: Supabase → display
DB_TO_COL = {v: k for k, v in COL_TO_DB.items()}

DEFAULT_BROKERAGE = 40.0
DEFAULT_STT_PCT   = 0.05
DEFAULT_OTHER     = 15.0


# ── Supabase connection ────────────────────────────────────────────────────────

def _get_client():
    """Return authenticated Supabase client using Streamlit secrets."""
    from supabase import create_client
    url = st.secrets["supabase_url"]
    key = st.secrets["supabase_key"]
    return create_client(url, key)


def _is_cloud() -> bool:
    """True if Supabase secrets are configured."""
    try:
        return "supabase_url" in st.secrets and "supabase_key" in st.secrets
    except Exception:
        return False


# ── Trades ─────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_trades() -> pd.DataFrame:
    """Load all trades from Supabase (or empty DataFrame if not configured)."""
    if not _is_cloud():
        if "trades_df" not in st.session_state:
            st.session_state.trades_df = pd.DataFrame(columns=TRADE_COLUMNS)
        return st.session_state.trades_df.copy()
    try:
        client   = _get_client()
        response = client.table("trades").select("*").order("trade_num").execute()
        data     = response.data
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


def _save_trades(df: pd.DataFrame) -> None:
    """Save trades to Supabase — delete all rows then re-insert."""
    load_trades.clear()
    if not _is_cloud():
        st.session_state.trades_df = df.copy()
        return
    try:
        client = _get_client()

        # Step 1: delete every existing row
        client.table("trades").delete().gte("trade_num", 0).execute()

        if df.empty:
            return

        # Step 2: rename display columns → Supabase column names
        rows = df.copy().rename(columns=COL_TO_DB)

        # Step 3: keep only columns that exist in our mapping
        db_cols = list(COL_TO_DB.values())
        rows = rows[[c for c in db_cols if c in rows.columns]]

        # Step 4: cast numeric columns to proper types (not strings)
        numeric_cols = [
            "trade_num", "strike", "entry_price", "exit_price",
            "lots", "lot_size", "capital_used", "gross_pnl",
            "brokerage", "stt", "other_charges", "net_pnl",
            "entry_rsi", "entry_adx",
        ]
        for col in numeric_cols:
            if col in rows.columns:
                rows[col] = pd.to_numeric(rows[col], errors="coerce")

        # Step 5: replace NaN/None with None for clean JSON
        rows = rows.where(pd.notnull(rows), None)
        records = rows.to_dict("records")

        if records:
            client.table("trades").insert(records).execute()
    except Exception as e:
        st.error("Could not save trade: {}".format(e))


def add_trade(
    symbol: str, option_type: str, strike: int, expiry: str,
    entry_price: float, exit_price: float, lots: int, lot_size: int,
    entry_rsi: float = 0.0, entry_adx: float = 0.0,
    supertrend: str = "", dashboard_said: str = "",
    hold_time: str = "", lessons: str = "", notes: str = "",
    brokerage: float = DEFAULT_BROKERAGE,
) -> dict:
    now      = datetime.now()
    capital  = round(entry_price * lots * lot_size, 2)
    gross    = round((exit_price - entry_price) * lots * lot_size, 2) if exit_price > 0 else 0.0
    stt      = round(exit_price * lots * lot_size * DEFAULT_STT_PCT / 100, 2) if exit_price > 0 else 0.0
    other    = DEFAULT_OTHER if exit_price > 0 else 0.0
    net      = round(gross - brokerage - stt - other, 2) if exit_price > 0 else 0.0
    result   = "OPEN" if exit_price <= 0 else ("WIN" if net >= 0 else "LOSS")
    df       = load_trades()
    trade_num = 1 if df.empty else (pd.to_numeric(df["Trade #"], errors="coerce").max() + 1)

    row = {
        "Trade #":         int(trade_num),
        "Date":            now.strftime("%Y-%m-%d"),
        "Time":            now.strftime("%H:%M"),
        "Symbol":          symbol,
        "Option Type":     option_type,
        "Strike":          strike,
        "Expiry":          expiry,
        "Entry Price":     entry_price,
        "Exit Price":      exit_price if exit_price > 0 else "",
        "Lots":            lots,
        "Lot Size":        lot_size,
        "Capital Used":    capital,
        "Gross P&L":       gross      if exit_price > 0 else "",
        "Brokerage":       brokerage  if exit_price > 0 else "",
        "STT":             stt        if exit_price > 0 else "",
        "Other Charges":   other      if exit_price > 0 else "",
        "Net P&L":         net        if exit_price > 0 else "",
        "Result":          result,
        "Hold Time":       hold_time,
        "Entry RSI":       round(entry_rsi, 1) if entry_rsi else "",
        "Entry ADX":       round(entry_adx, 1) if entry_adx else "",
        "Supertrend":      supertrend,
        "Dashboard Said":  dashboard_said,
        "Lessons Learned": lessons,
        "Notes":           notes,
    }
    new_df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    _save_trades(new_df)

    # ── Auto-update capital when trade is closed ───────────────────────────────
    if result in ("WIN", "LOSS"):
        cap_df   = load_capital_history()
        current  = float(cap_df["Balance"].iloc[-1]) if not cap_df.empty else 40000.0
        new_bal  = round(current + net, 2)
        note_txt = "Trade #{} {} {} {} | Net P&L: Rs {:,.0f}".format(
            int(trade_num), result, symbol, option_type, net)
        cap_row  = pd.DataFrame([{
            "Date":    now.strftime("%Y-%m-%d"),
            "Balance": new_bal,
            "Note":    note_txt,
        }])
        _save_capital(pd.concat([cap_df, cap_row], ignore_index=True))

    return row


def delete_trade(trade_num: int) -> str:
    """Delete a trade by Trade # and reverse its capital impact. Returns status message."""
    df = load_trades()
    mask = pd.to_numeric(df["Trade #"], errors="coerce") == trade_num
    if not mask.any():
        return "Trade #{} not found.".format(trade_num)

    trade = df[mask].iloc[0]
    result = str(trade.get("Result", ""))
    net    = 0.0
    try:
        net = float(trade.get("Net P&L", 0) or 0)
    except Exception:
        net = 0.0

    # Remove the trade row
    new_df = df[~mask].reset_index(drop=True)
    _save_trades(new_df)

    # Reverse capital impact for closed trades
    if result in ("WIN", "LOSS") and net != 0.0:
        cap_df  = load_capital_history()
        current = float(cap_df["Balance"].iloc[-1]) if not cap_df.empty else 40000.0
        new_bal = round(current - net, 2)   # subtract what was added (or added back what was lost)
        cap_row = pd.DataFrame([{
            "Date":    datetime.now().strftime("%Y-%m-%d"),
            "Balance": new_bal,
            "Note":    "Deleted Trade #{} {} | Reversed Net P&L: Rs {:,.0f}".format(
                trade_num, result, net),
        }])
        _save_capital(pd.concat([cap_df, cap_row], ignore_index=True))
        return "deleted_with_capital"

    return "deleted"


# ── Capital ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_capital_history() -> pd.DataFrame:
    """Load capital history from Supabase."""
    if not _is_cloud():
        if "capital_df" not in st.session_state:
            st.session_state.capital_df = pd.DataFrame([
                {"Date": "2026-10-01", "Balance": 40000.0, "Note": "Initial capital"},
            ])
        return st.session_state.capital_df.copy()
    try:
        client   = _get_client()
        response = client.table("capital").select("*").order("date").execute()
        data     = response.data
        if not data:
            return pd.DataFrame(columns=CAPITAL_COLUMNS)
        df = pd.DataFrame(data)
        # Normalise column names (Supabase returns lowercase)
        df.columns = [c.capitalize() if c in ["date","balance","note"] else c for c in df.columns]
        for col in CAPITAL_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df[CAPITAL_COLUMNS]
    except Exception as e:
        st.warning("Could not load capital: {}".format(e))
        return pd.DataFrame(columns=CAPITAL_COLUMNS)


def _save_capital(df: pd.DataFrame) -> None:
    load_capital_history.clear()
    if not _is_cloud():
        st.session_state.capital_df = df.copy()
        return
    try:
        client = _get_client()
        # Full replace — delete all then insert clean rows
        client.table("capital").delete().neq("date", "1900-01-01").execute()
        rows = df.copy()
        rows.columns = [c.lower() for c in rows.columns]
        # Keep balance as a proper float, not a string
        rows["balance"] = pd.to_numeric(rows["balance"], errors="coerce")
        rows = rows.where(pd.notnull(rows), None)
        records = rows.to_dict("records")
        if records:
            client.table("capital").insert(records).execute()
    except Exception as e:
        st.error("Could not save capital: {}".format(e))


def reset_capital(initial_capital: float, start_date: str = "") -> None:
    """Reset capital history with a clean initial balance."""
    date_str = start_date if start_date else datetime.now().strftime("%Y-%m-%d")
    df = pd.DataFrame([{
        "Date":    date_str,
        "Balance": round(initial_capital, 2),
        "Note":    "Initial starting capital",
    }])
    _save_capital(df)


def update_capital(new_balance: float, note: str = "") -> None:
    """Append a row with an explicit absolute balance value."""
    df  = load_capital_history()
    row = pd.DataFrame([{
        "Date":    datetime.now().strftime("%Y-%m-%d"),
        "Balance": round(new_balance, 2),
        "Note":    note or "Manual update",
    }])
    _save_capital(pd.concat([df, row], ignore_index=True))


def add_capital_deposit(amount: float, note: str = "") -> float:
    """Add `amount` to current balance and save. Returns the new balance."""
    df      = load_capital_history()
    current = float(df["Balance"].iloc[-1]) if not df.empty else 40000.0
    new_bal = round(current + amount, 2)
    row = pd.DataFrame([{
        "Date":    datetime.now().strftime("%Y-%m-%d"),
        "Balance": new_bal,
        "Note":    note or "[DEPOSIT] Rs {:,.0f}".format(amount),
    }])
    _save_capital(pd.concat([df, row], ignore_index=True))
    return new_bal


def withdraw_capital(amount: float, note: str = "") -> float:
    """Subtract `amount` from current balance and save. Returns the new balance."""
    df      = load_capital_history()
    current = float(df["Balance"].iloc[-1]) if not df.empty else 40000.0
    new_bal = round(current - amount, 2)
    row = pd.DataFrame([{
        "Date":    datetime.now().strftime("%Y-%m-%d"),
        "Balance": new_bal,
        "Note":    note or "[WITHDRAWAL] Rs {:,.0f}".format(amount),
    }])
    _save_capital(pd.concat([df, row], ignore_index=True))
    return new_bal


def get_capital_stats() -> dict:
    df = load_capital_history()
    if df.empty:
        return {"initial": 40000.0, "current": 40000.0, "pnl": 0.0,
                "pnl_pct": 0.0, "days": 0, "history": []}
    df["Balance"] = pd.to_numeric(df["Balance"], errors="coerce")

    # Prefer the row explicitly marked as starting capital; fall back to first row
    init_mask = df["Note"].astype(str).str.contains("Initial starting capital", case=False, na=False)
    if init_mask.any():
        init_row = df[init_mask].iloc[0]
    else:
        init_row = df.iloc[0]

    initial = float(init_row["Balance"])
    current = float(df["Balance"].iloc[-1])
    pnl     = round(current - initial, 2)
    pct     = round((pnl / initial) * 100, 2) if initial else 0.0
    try:
        start = datetime.strptime(str(init_row["Date"]), "%Y-%m-%d")
        days  = max(0, (datetime.now() - start).days)
    except Exception:
        days = 0
    return {
        "initial": initial, "current": current,
        "pnl": pnl, "pnl_pct": pct, "days": days,
        "history": df.to_dict("records"),
    }


# ── Stats ──────────────────────────────────────────────────────────────────────

def get_stats(df: pd.DataFrame = None) -> dict:
    if df is None:
        df = load_trades()
    closed = df[df["Result"].isin(["WIN", "LOSS"])].copy()
    empty  = {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
              "total_pnl": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
              "avg_win": 0.0, "avg_loss": 0.0, "reward_risk": 0.0,
              "max_drawdown": 0.0, "total_invested": 0.0,
              "total_brokerage": 0.0, "total_charges": 0.0}
    if closed.empty:
        return empty
    pnl   = pd.to_numeric(closed["Net P&L"],      errors="coerce").fillna(0)
    brok  = pd.to_numeric(closed["Brokerage"],     errors="coerce").fillna(0)
    stt   = pd.to_numeric(closed["STT"],           errors="coerce").fillna(0)
    other = pd.to_numeric(closed["Other Charges"], errors="coerce").fillna(0)
    cap   = pd.to_numeric(closed["Capital Used"],  errors="coerce").fillna(0)
    wins  = closed[closed["Result"] == "WIN"]
    losses= closed[closed["Result"] == "LOSS"]
    equity= pnl.cumsum(); dd = (equity - equity.cummax()).min()
    aw = pd.to_numeric(wins["Net P&L"],   errors="coerce").mean() if not wins.empty   else 0.0
    al = pd.to_numeric(losses["Net P&L"], errors="coerce").mean() if not losses.empty else 0.0
    rr = round(aw / abs(al), 2) if al and al != 0 else 0.0
    return {
        "total_trades":    len(closed),
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        round(len(wins) / len(closed) * 100, 1),
        "total_pnl":       round(pnl.sum(), 2),
        "best_trade":      round(pnl.max(), 2),
        "worst_trade":     round(pnl.min(), 2),
        "avg_win":         round(aw, 2),
        "avg_loss":        round(al, 2),
        "reward_risk":     rr,
        "max_drawdown":    round(dd, 2),
        "total_invested":  round(cap.sum(), 2),
        "total_brokerage": round(brok.sum(), 2),
        "total_charges":   round((brok + stt + other).sum(), 2),
    }


# ── Excel export ───────────────────────────────────────────────────────────────

def build_excel_report(df: pd.DataFrame) -> bytes:
    from io import BytesIO
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Trades", index=False)
        closed = df[df["Result"].isin(["WIN", "LOSS"])].copy()
        if not closed.empty:
            closed["Month"] = pd.to_datetime(closed["Date"], errors="coerce").dt.strftime("%b %Y")
            monthly = closed.groupby("Month").agg(
                Trades=("Net P&L", "count"),
                Wins=("Result", lambda x: (x == "WIN").sum()),
                Net_PnL=("Net P&L", lambda x: pd.to_numeric(x, errors="coerce").sum()),
            ).reset_index().rename(columns={"Net_PnL": "Net P&L"})
            monthly["Win Rate %"] = round(monthly["Wins"] / monthly["Trades"] * 100, 1)
            monthly.to_excel(writer, sheet_name="Monthly Summary", index=False)
        stats = get_stats(df)
        perf  = pd.DataFrame([{"Metric": k, "Value": v} for k, v in stats.items()])
        perf.to_excel(writer, sheet_name="Performance", index=False)
    return buf.getvalue()
