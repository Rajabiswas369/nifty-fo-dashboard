"""
angel_sync.py — Angel One SmartAPI auto trade fetcher.
Fetches your executed F&O trades from Angel One and saves to Google Sheets.
No static IP needed for trade history fetching.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import traceback


# ── Angel One connection ───────────────────────────────────────────────────────

def _get_angel_credentials():
    """Get Angel One credentials from Streamlit secrets (supporting both top-level and [angel] table)."""
    try:
        angel_sec = st.secrets.get("angel", {})
        api_key = angel_sec.get("api_key") or st.secrets.get("angel_api_key") or st.secrets.get("api_key")
        client_id = angel_sec.get("client_id") or st.secrets.get("angel_client_id") or st.secrets.get("client_id")
        mpin = angel_sec.get("mpin") or st.secrets.get("angel_mpin") or st.secrets.get("mpin")
        totp_key = angel_sec.get("totp_key") or st.secrets.get("angel_totp_key") or st.secrets.get("totp_key", "")
        
        if api_key and client_id and mpin:
            return {
                "api_key": str(api_key),
                "client_id": str(client_id),
                "mpin": str(mpin),
                "totp_key": str(totp_key) if totp_key else "",
            }
        return None
    except Exception:
        return None


def is_angel_configured() -> bool:
    """True if Angel One credentials are in secrets."""
    return _get_angel_credentials() is not None


def _login_angel():
    """Login to Angel One SmartAPI and return SmartConnect object."""
    from SmartApi import SmartConnect
    import pyotp

    creds = _get_angel_credentials()
    obj   = SmartConnect(api_key=creds["api_key"])

    totp_key = creds.get("totp_key", "")
    if totp_key:
        totp = pyotp.TOTP(totp_key).now()
    else:
        totp = creds["mpin"]

    data = obj.generateSession(
        creds["client_id"],
        creds["mpin"],
        totp,
    )
    if not data or data.get("status") is False:
        raise Exception("Angel One login failed: {}".format(data.get("message", "Unknown error")))
    return obj


# ── Fetch trades from Angel One ────────────────────────────────────────────────

def fetch_angel_trades(days_back: int = 1) -> list:
    """
    Fetch executed trades from Angel One for last N days.
    Returns list of raw trade dicts from Angel API.
    """
    obj = _login_angel()

    today     = datetime.now()
    from_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M")
    to_date   = today.strftime("%Y-%m-%d %H:%M")

    trade_book = obj.tradeBook()
    if not trade_book or trade_book.get("status") is False:
        return []

    trades = trade_book.get("data", []) or []
    return trades


def _parse_angel_trade(raw: dict) -> dict:
    """
    Convert Angel One raw trade dict to dashboard trade format.
    Uses exact field names from Angel One tradeBook API.
    """
    symbol      = raw.get("tradingsymbol", "")

    option_type = raw.get("optiontype", "")
    if option_type == "PE":
        option_type = "PUT"
    elif option_type == "CE":
        option_type = "CALL"
    else:
        option_type = "CALL" if "CE" in symbol else ("PUT" if "PE" in symbol else "")

    strike   = str(int(float(raw.get("strikeprice", 0) or 0)))
    price    = float(raw.get("fillprice", 0) or 0)
    qty      = int(raw.get("fillsize", 0) or 0)
    lot_size = int(raw.get("marketlot", 0) or 0)
    if lot_size == 0:
        lot_size = 65

    expiry_raw  = raw.get("expirydate", "")
    order_type  = raw.get("transactiontype", "")
    trade_time  = raw.get("filltime", raw.get("updatetime", ""))

    return {
        "raw_symbol":  symbol,
        "option_type": option_type,
        "strike":      strike,
        "qty":         qty,
        "price":       price,
        "lot_size":    lot_size,
        "expiry":      expiry_raw,
        "order_type":  order_type,
        "trade_time":  trade_time,
        "exchange":    raw.get("exchange", "NFO"),
        "product":     raw.get("producttype", ""),
        "order_id":    raw.get("orderid", ""),
    }


def match_and_save_trades(raw_trades: list, load_fn, save_fn, columns: list) -> tuple:
    """
    Match BUY+SELL pairs from Angel trades and append to Google Sheets.
    Returns (saved_count, skipped_count, message).
    """
    if not raw_trades:
        return 0, 0, "No trades found in Angel One today."

    parsed   = [_parse_angel_trade(t) for t in raw_trades]
    fo_trades = [t for t in parsed if t["option_type"] in ["CALL", "PUT"]]
    if not fo_trades:
        return 0, 0, "No F&O (CE/PE) trades found today."

    from collections import defaultdict
    by_symbol = defaultdict(list)
    for t in fo_trades:
        by_symbol[t["raw_symbol"]].append(t)

    existing_df  = load_fn()
    existing_ids = set()
    if not existing_df.empty and "Notes" in existing_df.columns:
        extracted = existing_df["Notes"].astype(str).str.extract(r'OrderID:(\w+)')[0]
        existing_ids = set(extracted.dropna().tolist())

    saved   = 0
    skipped = 0
    rows    = []

    def _next_num(df):
        if df.empty or df["Trade #"].isna().all():
            return 1
        return int(pd.to_numeric(df["Trade #"], errors="coerce").max()) + 1

    DEFAULT_BROKERAGE = 40.0
    DEFAULT_STT_PCT   = 0.05
    DEFAULT_OTHER     = 15.0

    for symbol, trades in by_symbol.items():
        buys  = [t for t in trades if t["order_type"] == "BUY"]
        sells = [t for t in trades if t["order_type"] == "SELL"]

        if not buys:
            skipped += 1
            continue

        buy      = buys[0]
        sell     = sells[0] if sells else None
        order_id = buy["order_id"]

        if order_id in existing_ids:
            skipped += 1
            continue

        entry_price = buy["price"]
        exit_price  = sell["price"] if sell else 0.0
        lot_size    = buy.get("lot_size", 65) or 65
        lots        = max(1, buy["qty"] // lot_size) if lot_size > 0 else 1
        expiry      = buy.get("expiry", "")

        capital = round(entry_price * lots * lot_size, 2)
        gross   = round((exit_price - entry_price) * lots * lot_size, 2) if exit_price > 0 else 0.0
        stt     = round(exit_price * lots * lot_size * DEFAULT_STT_PCT / 100, 2) if exit_price > 0 else 0.0
        other   = DEFAULT_OTHER if exit_price > 0 else 0.0
        net     = round(gross - DEFAULT_BROKERAGE - stt - other, 2) if exit_price > 0 else 0.0
        result  = "OPEN" if exit_price <= 0 else ("WIN" if net >= 0 else "LOSS")

        now = datetime.now()
        row = {col: "" for col in columns}
        row.update({
            "Trade #":         _next_num(existing_df) + saved,
            "Date":            now.strftime("%Y-%m-%d"),
            "Time":            now.strftime("%H:%M"),
            "Symbol":          "NIFTY50",
            "Option Type":     buy["option_type"],
            "Strike":          int(buy["strike"]) if buy["strike"] else 0,
            "Expiry":          expiry,
            "Entry Price":     entry_price,
            "Exit Price":      exit_price if exit_price > 0 else "",
            "Lots":            lots,
            "Lot Size":        lot_size,
            "Capital Used":    capital,
            "Gross P&L":       gross  if exit_price > 0 else "",
            "Brokerage":       DEFAULT_BROKERAGE if exit_price > 0 else "",
            "STT":             stt    if exit_price > 0 else "",
            "Other Charges":   other  if exit_price > 0 else "",
            "Net P&L":         net    if exit_price > 0 else "",
            "Result":          result,
            "Dashboard Said":  "",
            "Notes":           "Auto-synced from Angel One | OrderID:{}".format(order_id),
        })
        rows.append(row)
        saved += 1

    if rows:
        new_df = pd.concat([existing_df, pd.DataFrame(rows)], ignore_index=True)
        save_fn(new_df)

    msg = "✅ {} new trade(s) synced from Angel One!".format(saved)
    if skipped:
        msg += " ({} already existed or incomplete)".format(skipped)
    return saved, skipped, msg


# ── Streamlit UI component ─────────────────────────────────────────────────────

def render_angel_sync_panel(load_fn=None, save_fn=None, columns=None, *args, **kwargs):
    """Render the Angel One sync panel inside the Streamlit app."""
    st.subheader("🔄 Auto-Sync from Angel One")

    if not is_angel_configured():
        st.warning("Angel One API not configured yet.")
        st.markdown("""
**To enable auto-sync, add these to your Streamlit Cloud Secrets:**
```toml
angel_api_key   = "your_api_key"
angel_client_id = "your_client_id"
angel_mpin      = "your_mpin"
angel_totp_key  = "your_totp_secret"
```
Go to **share.streamlit.io → your app → ⋮ → Settings → Secrets**, paste the above, then click **Save**.
        """)
        return

    st.success("✅ Angel One API configured!")
    st.caption("Fetches your executed F&O trades and logs them automatically.")

    col1, col2 = st.columns(2)
    days_back = col1.selectbox(
        "Fetch trades from last:",
        [1, 2, 3, 7], index=0,
        format_func=lambda x: "{} day{}".format(x, "s" if x > 1 else ""),
    )

    if col2.button("🔄 Sync Now", use_container_width=True, type="primary"):
        with st.spinner("Connecting to Angel One..."):
            try:
                raw = fetch_angel_trades(days_back=days_back)
                if raw:
                    with st.expander("🔍 Raw API data (first trade)", expanded=False):
                        st.json(raw[0])
                saved, skipped, msg = match_and_save_trades(raw, load_fn, save_fn, columns)
                if saved > 0:
                    st.success(msg)
                    st.rerun()
                else:
                    st.info(msg)
            except Exception as e:
                st.error("Sync failed: {}".format(str(e)))
                with st.expander("Error details"):
                    st.code(traceback.format_exc())
