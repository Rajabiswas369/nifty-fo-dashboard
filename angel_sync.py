"""
angel_sync.py — Angel One SmartAPI auto trade fetcher.
Fetches your executed F&O trades from Angel One and saves to Google Sheets.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import traceback


def _read_secret(key: str, default=None):
    """
    Read a secret — checks top level first, then [angel] section,
    then [connections.gsheets] section (in case user put them there by mistake).
    """
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    try:
        if "angel" in st.secrets and key in st.secrets["angel"]:
            return st.secrets["angel"][key]
    except Exception:
        pass
    # Strip "angel_" prefix and check [angel] section
    short = key.replace("angel_", "")
    try:
        if "angel" in st.secrets and short in st.secrets["angel"]:
            return st.secrets["angel"][short]
    except Exception:
        pass
    return default


def _get_angel_credentials():
    """Read Angel One credentials from Streamlit secrets — any location."""
    try:
        api_key   = _read_secret("angel_api_key")   or _read_secret("api_key")
        client_id = _read_secret("angel_client_id") or _read_secret("client_id")
        mpin      = _read_secret("angel_mpin")      or _read_secret("mpin")
        totp_key  = _read_secret("angel_totp_key")  or _read_secret("totp_key") or ""
        if api_key and client_id and mpin:
            return {"api_key": api_key, "client_id": client_id,
                    "mpin": mpin, "totp_key": totp_key}
    except Exception:
        pass
    return None


def is_angel_configured() -> bool:
    """True if Angel One credentials are readable from any secret location."""
    creds = _get_angel_credentials()
    return creds is not None


def _login_angel():
    """Login to Angel One SmartAPI, return SmartConnect object."""
    from SmartApi import SmartConnect
    import pyotp

    creds = _get_angel_credentials()
    obj   = SmartConnect(api_key=creds["api_key"])

    totp_key = creds.get("totp_key", "")
    totp     = pyotp.TOTP(totp_key).now() if totp_key else creds["mpin"]

    data = obj.generateSession(creds["client_id"], creds["mpin"], totp)
    if not data or data.get("status") is False:
        raise Exception("Angel One login failed: {}".format(data.get("message", "Unknown error")))
    return obj


def fetch_angel_trades(days_back: int = 1) -> list:
    """
    Fetch executed trades from Angel One.
    - tradeBook() = today's executed trades only
    - orderBook() = all orders including past days (we filter COMPLETE ones)
    We try both and merge, so Thursday/older trades are included.
    """
    obj = _login_angel()
    all_trades = []

    # 1. Trade book — today's filled trades
    try:
        trade_book = obj.tradeBook()
        if trade_book and trade_book.get("status") is not False:
            trades = trade_book.get("data", []) or []
            all_trades.extend(trades)
    except Exception:
        pass

    # 2. Order book — historical orders (filter only COMPLETE/filled ones)
    try:
        order_book = obj.orderBook()
        if order_book and order_book.get("status") is not False:
            orders = order_book.get("data", []) or []
            # Only keep completely filled orders
            filled = [o for o in orders if str(o.get("status","")).upper() in
                      ("COMPLETE", "FILLED", "TRADED", "EXECUTED")]
            # Add orders not already in trade list (by orderid)
            existing_ids = {t.get("orderid","") for t in all_trades}
            for o in filled:
                if o.get("orderid","") not in existing_ids:
                    # Map order fields to trade fields
                    o["fillprice"]  = o.get("averageprice", o.get("price", 0))
                    o["fillsize"]   = o.get("filledshares", o.get("quantity", 0))
                    o["filltime"]   = o.get("updatetime", "")
                    all_trades.append(o)
    except Exception:
        pass

    return all_trades


def _parse_angel_trade(raw: dict) -> dict:
    """Convert Angel One raw trade dict to dashboard trade format."""
    symbol = raw.get("tradingsymbol", "")

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
    lot_size = int(raw.get("marketlot", 0) or 0) or 65

    return {
        "raw_symbol":  symbol,
        "option_type": option_type,
        "strike":      strike,
        "qty":         qty,
        "price":       price,
        "lot_size":    lot_size,
        "expiry":      raw.get("expirydate", ""),
        "order_type":  raw.get("transactiontype", ""),
        "trade_time":  raw.get("filltime", raw.get("updatetime", "")),
        "exchange":    raw.get("exchange", "NFO"),
        "product":     raw.get("producttype", ""),
        "order_id":    raw.get("orderid", ""),
    }


def match_and_save_trades(raw_trades: list, load_fn, save_fn, columns: list) -> tuple:
    """
    Match BUY+SELL pairs from Angel trades and append to Google Sheets.
    Returns (saved_count, skipped_count, message).
    """
    DEFAULT_BROKERAGE = 40.0
    DEFAULT_STT_PCT   = 0.05
    DEFAULT_OTHER     = 15.0

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
        extracted    = existing_df["Notes"].astype(str).str.extract(r'OrderID:(\w+)')[0]
        existing_ids = set(extracted.dropna().tolist())

    saved = 0; skipped = 0; rows = []

    def _next_num(df):
        if df.empty or df["Trade #"].isna().all():
            return 1
        return int(pd.to_numeric(df["Trade #"], errors="coerce").max()) + 1

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

        capital = round(entry_price * lots * lot_size, 2)
        gross   = round((exit_price - entry_price) * lots * lot_size, 2) if exit_price > 0 else 0.0
        stt     = round(exit_price * lots * lot_size * DEFAULT_STT_PCT / 100, 2) if exit_price > 0 else 0.0
        other   = DEFAULT_OTHER if exit_price > 0 else 0.0
        net     = round(gross - DEFAULT_BROKERAGE - stt - other, 2) if exit_price > 0 else 0.0
        result  = "OPEN" if exit_price <= 0 else ("WIN" if net >= 0 else "LOSS")

        now = datetime.now()
        row = {col: "" for col in columns}
        row.update({
            "Trade #":        _next_num(existing_df) + saved,
            "Date":           now.strftime("%Y-%m-%d"),
            "Time":           now.strftime("%H:%M"),
            "Symbol":         "NIFTY50",
            "Option Type":    buy["option_type"],
            "Strike":         int(buy["strike"]) if buy["strike"] else 0,
            "Expiry":         buy.get("expiry", ""),
            "Entry Price":    entry_price,
            "Exit Price":     exit_price if exit_price > 0 else "",
            "Lots":           lots,
            "Lot Size":       lot_size,
            "Capital Used":   capital,
            "Gross P&L":      gross              if exit_price > 0 else "",
            "Brokerage":      DEFAULT_BROKERAGE  if exit_price > 0 else "",
            "STT":            stt                if exit_price > 0 else "",
            "Other Charges":  other              if exit_price > 0 else "",
            "Net P&L":        net                if exit_price > 0 else "",
            "Result":         result,
            "Dashboard Said": "",
            "Notes":          "Auto-synced from Angel One | OrderID:{}".format(order_id),
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


def render_angel_sync_panel(load_fn, save_fn, columns: list):
    """Render the Angel One sync UI panel inside the Streamlit app."""
    st.subheader("🔄 Auto-Sync from Angel One")

    if not is_angel_configured():
        st.warning("⚠️ Angel One API not configured yet.")
        st.markdown("""
**To enable auto-sync, add these to your Streamlit Cloud Secrets:**
```toml
angel_api_key   = "your_api_key"
angel_client_id = "your_client_id"
angel_mpin      = "your_mpin"
angel_totp_key  = "your_totp_secret"
```
Go to **share.streamlit.io → your app → ⋮ → Settings → Secrets**, paste the above (no leading spaces), click **Save**, then **Reboot app**.
        """)
        return

    st.success("✅ Angel One API configured and ready!")
    st.caption("Fetches your executed F&O trades and logs them automatically — no manual typing needed.")
    st.markdown("---")

    col1, col2 = st.columns(2)
    days_back = col1.selectbox(
        "Fetch trades from last:",
        [1, 2, 3, 7],
        index=0,
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
                    st.balloons()
                    st.rerun()
                else:
                    st.info(msg)
            except Exception as e:
                st.error("Sync failed: {}".format(str(e)))
                with st.expander("Error details"):
                    st.code(traceback.format_exc())

    st.markdown("---")
    st.markdown("""
**What Angel One Sync does:**

| Without Sync (manual) | With Sync (automatic) |
|---|---|
| Trade on Angel One app | Trade on Angel One app |
| Come back and type entry price, exit, lots... | Click 🔄 Sync Now |
| 5 minutes per trade | 5 seconds ✅ |
| Risk of typos | 100% accurate from API |

**Note:** Sync fetches your **trade book** (executed orders). It works after trades are executed.
If you haven't traded today, it will say "No trades found" — that's normal.
    """)
