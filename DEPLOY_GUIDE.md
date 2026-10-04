# Nifty F&O Unified Cloud Dashboard — Deploy Guide

## What is this?

One single Streamlit Cloud app that gives you **everything in one place**:

| Page | What it does |
|------|-------------|
| 📈 Signal Dashboard | Live Nifty signals — RSI, ADX, Supertrend, MACD, VWAP, Trade Decision |
| 📰 Market News & Verdict | Should I trade today? Live headlines + event calendar |
| 📊 My Records Dashboard | P&L overview, equity curve, win/loss ratio |
| 💰 My Capital | Capital tracker and balance history |
| 📓 Log Trade | Manual trade entry → saved to Google Sheets |
| 🔄 Angel One Sync | Auto-fetch executed trades from Angel One |
| 📋 All Trades | View, filter, search all your trades |
| 📅 Monthly Report | P&L statement per month |
| 📈 Performance | Win rate, RR ratio, signal accuracy by type |
| 💸 Expenses | Brokerage / STT breakdown |
| ⬇️ Export | Download all trades as CSV |

---

## STEP 1 — Google Sheets setup

1. Open [Google Sheets](https://sheets.google.com) → Create a new blank spreadsheet
2. Rename it: **Nifty Trading Records**
3. Create two sheets inside it:
   - Sheet 1: rename to **Trades**
   - Sheet 2: rename to **Capital**
4. Copy the spreadsheet URL from your browser bar
5. **Share it** → Anyone with the link → **Editor** access

---

## STEP 2 — Push to GitHub

1. Create a new **public** GitHub repository (e.g. `nifty-fo-dashboard`)
2. Upload these files from this folder (`nifty_cloud_app/`):
   - `app.py`
   - `angel_sync.py`
   - `requirements.txt`
   - `.streamlit/config.toml`
3. Make sure the folder structure is:
   ```
   repo/
     app.py
     angel_sync.py
     requirements.txt
     .streamlit/
       config.toml
   ```

---

## STEP 3 — Deploy on Streamlit Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Click **New app**
3. Connect your GitHub repo
4. Set **Main file path**: `app.py`
5. Click **Deploy**

---

## STEP 4 — Add Secrets (IMPORTANT)

After the app deploys:

1. Click **⋮** (three dots) next to your app → **Settings** → **Secrets**
2. Delete everything in the box
3. Paste **exactly** this (no leading spaces on any line):

```toml
[connections.gsheets]
spreadsheet = "YOUR_GOOGLE_SHEET_URL_HERE"
type = "public"

angel_api_key = "eLVJlyTE"
angel_client_id = "R464897"
angel_mpin = "0303"
angel_totp_key = "LJQ2UJX3ZG56KDZTXKYMMZTLDA"
```

4. Replace `YOUR_GOOGLE_SHEET_URL_HERE` with your actual Google Sheet URL
5. Click **Save**
6. Click **⋮** → **Reboot app**
7. Wait 1–2 minutes → refresh the page

---

## STEP 5 — First time setup in the app

1. Open your deployed app
2. Go to **💰 My Capital** → Update your starting capital
3. Go to **📓 Log Trade** → Log your first trade
4. Go to **🔄 Angel One Sync** → Test the sync

---

## Troubleshooting

### "Google Sheets not connected" warning
- Check that the secrets are saved with **no leading spaces** on any line
- Make sure `[connections.gsheets]` is the first line
- Reboot the app after saving secrets

### "Angel One Sync failed"
- Secrets must be at the **root level** (not inside `[connections.gsheets]`)
- The `angel_api_key`, `angel_client_id`, `angel_mpin`, `angel_totp_key` lines must be **outside** the `[connections.gsheets]` block

### Correct secrets format (copy exactly):
```
[connections.gsheets]
spreadsheet = "https://docs.google.com/spreadsheets/d/YOUR_ID/edit"
type = "public"

angel_api_key = "eLVJlyTE"
angel_client_id = "R464897"
angel_mpin = "0303"
angel_totp_key = "LJQ2UJX3ZG56KDZTXKYMMZTLDA"
```

---

## Files in this folder

```
nifty_cloud_app/
  app.py              ← Main Streamlit app (all 11 pages)
  angel_sync.py       ← Angel One API integration
  requirements.txt    ← Python package dependencies
  .streamlit/
    config.toml       ← Dark theme + server settings
  DEPLOY_GUIDE.md     ← This file
```

---

*For educational use only. Not financial advice.*
