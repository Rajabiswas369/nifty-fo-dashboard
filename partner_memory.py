"""
AI Trading Partner helpers
==========================
- Persistent partner memory (Supabase table `partner_memory`, session fallback)
- Live candlestick chart for the Partner page
- Compact OHLC text so Gemini can "read" the candles
- Gemini call helper (model fallback)

Supabase table (run once in the Supabase SQL editor):

    create table if not exists partner_memory (
        id         bigint generated always as identity primary key,
        created_at timestamptz not null default now(),
        kind       text not null,      -- 'lesson' | 'note' | 'playbook'
        content    text not null
    );
"""

from datetime import datetime

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

MEMORY_TABLE = "partner_memory"
VALID_KINDS = ("lesson", "note", "playbook")
MAX_CONTENT_CHARS = 4000


# ── Memory ────────────────────────────────────────────────────────────────────
def load_memories(client, local: list, limit: int = 60):
    """Return (memories newest-first, error string). Uses `local` if no client."""
    if client is None:
        return list(reversed(local))[:limit], ""
    try:
        rows = (
            client.table(MEMORY_TABLE)
            .select("id,created_at,kind,content")
            .order("id", desc=True)
            .limit(limit)
            .execute()
            .data
        )
        return rows or [], ""
    except Exception:
        return list(reversed(local))[:limit], "memory_table_unavailable"


def save_memory(client, local: list, kind: str, content: str) -> str:
    """Persist one memory entry. Returns an error code ('' on success)."""
    content = (content or "").strip()[:MAX_CONTENT_CHARS]
    if kind not in VALID_KINDS or not content:
        return "invalid_memory"
    entry = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "content": content,
    }
    if client is not None:
        try:
            client.table(MEMORY_TABLE).insert({"kind": kind, "content": content}).execute()
            return ""
        except Exception:
            local.append(entry)  # keep it for this session at least
            return "memory_table_unavailable"
    local.append(entry)
    return ""


def memory_context(memories: list, max_recent: int = 15) -> str:
    """Latest playbook + everything newer than it (capped) as prompt text."""
    if not memories:
        return "No memory yet. Start discussing and press 'End session & learn'."
    playbook = next((m for m in memories if m.get("kind") == "playbook"), None)
    recent = [
        m for m in memories
        if m.get("kind") != "playbook"
        and (playbook is None or str(m.get("created_at", "")) >= str(playbook.get("created_at", "")))
    ][:max_recent]
    lines = []
    if playbook:
        lines.append("PLAYBOOK (consolidated rules, {}):\n{}".format(
            str(playbook.get("created_at", ""))[:10], playbook["content"]))
    for m in reversed(recent):
        lines.append("[{} {}] {}".format(
            str(m.get("created_at", ""))[:10], m.get("kind", "note"), m["content"]))
    return "\n".join(lines) if lines else "No memory yet."


# ── Candle text ───────────────────────────────────────────────────────────────
def candles_to_text(df, n: int = 30) -> str:
    """Last n candles as compact one-line-per-candle text for the LLM."""
    rows = []
    for ts, r in df.tail(n).iterrows():
        o, h, lo, c = (float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]))
        body = (c - o) / o * 100 if o else 0.0
        rows.append("{} O{:.1f} H{:.1f} L{:.1f} C{:.1f} {} {:+.2f}% RSI{:.0f}".format(
            ts.strftime("%d%b %H:%M"), o, h, lo, c,
            "G" if c >= o else "R", body, float(r.get("RSI", 50.0))))
    return "\n".join(rows)


# ── Chart ─────────────────────────────────────────────────────────────────────
def build_partner_chart(df, title: str, n: int = 90):
    """Candlestick + EMA9/21 + VWAP + Supertrend, with RSI panel."""
    d = df.tail(n)
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.75, 0.25], vertical_spacing=0.03,
    )
    fig.add_trace(go.Candlestick(
        x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
        name="Price", increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d["EMA_9"], name="EMA 9",
                             line=dict(color="#38bdf8", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d["EMA_21"], name="EMA 21",
                             line=dict(color="#f59e0b", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d["VWAP"], name="VWAP",
                             line=dict(color="#a78bfa", width=1, dash="dot")), row=1, col=1)
    up = d["ST_value"].where(d["ST_trend"] == 1, np.nan)
    dn = d["ST_value"].where(d["ST_trend"] == -1, np.nan)
    fig.add_trace(go.Scatter(x=d.index, y=up, name="Supertrend ▲",
                             line=dict(color="#4ade80", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=dn, name="Supertrend ▼",
                             line=dict(color="#f87171", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d["RSI"], name="RSI",
                             line=dict(color="#e2e8f0", width=1)), row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#dc2626", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#16a34a", row=2, col=1)
    fig.update_xaxes(rangebreaks=[
        dict(bounds=["sat", "mon"]),
        dict(bounds=[15.5, 9.25], pattern="hour"),
    ])
    fig.update_layout(
        title=title, template="plotly_dark", height=620,
        xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=1.04),
    )
    fig.update_yaxes(range=[0, 100], row=2, col=1)
    return fig


# ── Gemini ────────────────────────────────────────────────────────────────────
def gemini_reply(api_key: str, system_prompt: str, history: list, message: str):
    """Return (reply, error). `history` = [{'role': 'user'|'model', 'parts': [str]}]."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        names = []
        try:
            for m in genai.list_models():
                if "generateContent" in getattr(m, "supported_generation_methods", []):
                    names.append(m.name)
        except Exception:
            pass
        candidates = names or ["gemini-2.5-flash", "gemini-1.5-flash",
                               "gemini-1.5-pro", "gemini-pro"]
        candidates.sort(key=lambda n: (0 if "flash" in n.lower() else 1))

        last_err = ""
        for name in candidates:
            try:
                model = genai.GenerativeModel(
                    model_name=name.replace("models/", ""),
                    system_instruction=system_prompt,
                )
                chat = model.start_chat(history=history)
                return chat.send_message(message).text, ""
            except Exception as exc:
                last_err = type(exc).__name__
        return None, last_err or "no_model_available"
    except Exception as exc:
        return None, type(exc).__name__
