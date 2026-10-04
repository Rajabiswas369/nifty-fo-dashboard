"""
goal_engine.py — Compounding & Goal Tracking Engine.
Goal settings are persisted permanently in Supabase `settings` table.
Falls back to session_state if Supabase is not configured.

Supabase table required (run once in Supabase SQL editor):
  CREATE TABLE IF NOT EXISTS settings (
      key   TEXT PRIMARY KEY,
      value TEXT
  );
  ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "allow_all" ON settings FOR ALL USING (true) WITH CHECK (true);
"""

import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

GOAL_KEY = "trading_goal"


def _get_default_goal():
    return {
        "goal_name":              "Roadmap to ₹10 Lakh",
        "initial_capital":        50000.0,
        "target_capital":         1000000.0,
        "start_date":             datetime.today().strftime("%Y-%m-%d"),
        "target_date":            (datetime.today() + timedelta(days=180)).strftime("%Y-%m-%d"),
        "target_months":          6,
        "trading_days_per_month": 20,
        "risk_per_trade_pct":     1.5,
        "risk_reward_ratio":      2.0,
        "max_daily_loss_pct":     3.0,
        "active":                 True,
        "completed":              False,
        "history":                [],
    }


def _is_supabase() -> bool:
    try:
        import streamlit as st
        return "supabase_url" in st.secrets and "supabase_key" in st.secrets
    except Exception:
        return False


def _get_client():
    import streamlit as st
    from supabase import create_client
    return create_client(st.secrets["supabase_url"], st.secrets["supabase_key"])


def load_goal_cloud(cap_data: dict = None) -> dict:
    """Load goal from Supabase settings table → session_state → defaults."""
    import streamlit as st

    # 1. Already in session this run — use it
    if "trading_goal" in st.session_state:
        return st.session_state["trading_goal"]

    # 2. Try Supabase
    if _is_supabase():
        try:
            client = _get_client()
            resp = client.table("settings").select("value").eq("key", GOAL_KEY).execute()
            if resp.data:
                g = json.loads(resp.data[0]["value"])
                defaults = _get_default_goal()
                for k, v in defaults.items():
                    if k not in g:
                        g[k] = v
                st.session_state["trading_goal"] = g
                return g
        except Exception:
            pass

    # 3. Fall back to defaults
    defaults = _get_default_goal()
    st.session_state["trading_goal"] = defaults
    return defaults


def save_goal_cloud(goal_data: dict, _unused_fn=None, _unused_cap=None) -> bool:
    """Save goal to Supabase settings table and session_state."""
    import streamlit as st
    st.session_state["trading_goal"] = goal_data

    if _is_supabase():
        try:
            client = _get_client()
            client.table("settings").upsert({
                "key":   GOAL_KEY,
                "value": json.dumps(goal_data),
            }).execute()
        except Exception as e:
            st.warning("Could not save goal to Supabase: {}".format(e))
    return True


# ── Maths ──────────────────────────────────────────────────────────────────────

def calculate_compounding_schedule(
    initial_capital: float,
    target_capital: float,
    total_trading_days: int,
) -> dict:
    if initial_capital <= 0 or target_capital <= initial_capital or total_trading_days <= 0:
        return {
            "daily_rate":       0.0,
            "daily_rate_pct":   0.0,
            "monthly_rate_pct": 0.0,
            "feasibility":      "Invalid inputs",
            "feasibility_color":"gray",
            "schedule_df":      pd.DataFrame(),
            "milestones":       [],
        }

    daily_rate     = (target_capital / initial_capital) ** (1.0 / total_trading_days) - 1.0
    daily_rate_pct = daily_rate * 100.0
    monthly_rate   = ((1.0 + daily_rate) ** 20) - 1.0

    if daily_rate_pct <= 0.8:
        feasibility       = "Realistic & Sustainable (~0.5%–0.8%/day)"
        feasibility_color = "#10b981"
    elif daily_rate_pct <= 1.5:
        feasibility       = "Moderate to Aggressive (~0.8%–1.5%/day)"
        feasibility_color = "#f59e0b"
    elif daily_rate_pct <= 2.5:
        feasibility       = "High Risk / Very Aggressive (~1.5%–2.5%/day)"
        feasibility_color = "#ef4444"
    else:
        feasibility       = "Extremely Aggressive (>2.5%/day) — High Drawdown Risk"
        feasibility_color = "#b91c1c"

    days       = list(range(0, total_trading_days + 1))
    trajectory = [initial_capital * ((1.0 + daily_rate) ** d) for d in days]

    milestones = []
    for idx, r in enumerate([0.1, 0.25, 0.5, 0.75, 1.0], 1):
        target_val = initial_capital + (target_capital - initial_capital) * r
        cross_day  = int(np.ceil(
            np.log(target_val / initial_capital) / np.log(1.0 + daily_rate)
        )) if daily_rate > 0 else 0
        milestones.append({
            "level":         "Level {}".format(idx),
            "target_amount": round(target_val, 2),
            "target_day":    cross_day,
            "percentage":    int(r * 100),
        })

    return {
        "daily_rate":       daily_rate,
        "daily_rate_pct":   round(daily_rate_pct, 3),
        "monthly_rate_pct": round(monthly_rate * 100.0, 2),
        "feasibility":      feasibility,
        "feasibility_color":feasibility_color,
        "milestones":       milestones,
        "schedule_df":      pd.DataFrame({"Day": days, "Target_Capital": [round(x, 2) for x in trajectory]}),
    }


def evaluate_goal_progress(goal_data: dict, current_capital: float) -> dict:
    initial    = float(goal_data.get("initial_capital",  50000.0))
    target     = float(goal_data.get("target_capital",  1000000.0))
    start_str  = goal_data.get("start_date",  datetime.today().strftime("%Y-%m-%d"))
    target_str = goal_data.get("target_date", (datetime.today() + timedelta(days=180)).strftime("%Y-%m-%d"))

    try:
        start_date = datetime.strptime(start_str,  "%Y-%m-%d").date()
    except Exception:
        start_date = datetime.today().date()
    try:
        target_date = datetime.strptime(target_str, "%Y-%m-%d").date()
    except Exception:
        target_date = (datetime.today() + timedelta(days=180)).date()

    today                 = datetime.today().date()
    total_calendar_days   = max(1, (target_date - start_date).days)
    days_elapsed          = max(0, (today - start_date).days)
    days_remaining        = max(0, (target_date - today).days)
    total_trading_days    = max(1, int(total_calendar_days * 5 / 7))
    trading_days_elapsed  = min(total_trading_days, int(days_elapsed * 5 / 7))
    trading_days_remaining= max(1, total_trading_days - trading_days_elapsed)

    comp     = calculate_compounding_schedule(initial, target, total_trading_days)
    daily_rate = comp.get("daily_rate", 0.01)

    expected_today = min(target, initial * ((1.0 + daily_rate) ** trading_days_elapsed))
    progress_pct   = max(0.0, min(100.0, (current_capital - initial) / max(1.0, target - initial) * 100.0))
    diff           = current_capital - expected_today

    if diff >= 0.02 * current_capital:
        pace, pace_color = "Ahead of Pace 🚀", "#10b981"
        pace_advice = "Capital is ahead of trajectory. Protect profits — stick to A+ setups only."
    elif diff >= -(0.02 * current_capital):
        pace, pace_color = "On Track 🎯", "#3b82f6"
        pace_advice = "Right on benchmark. Keep executing with disciplined risk-to-reward."
    else:
        pace, pace_color = "Behind Pace ⚠️", "#f59e0b"
        pace_advice = "Behind schedule. Do NOT revenge-trade. Stick strictly to 1:2 R:R to recover."

    risk_pct     = float(goal_data.get("risk_per_trade_pct", 1.5))
    max_loss_pct = float(goal_data.get("max_daily_loss_pct", 3.0))

    current_level       = "Level 1 Target"
    next_milestone_target = target
    for m in comp.get("milestones", []):
        if current_capital >= m["target_amount"]:
            current_level = "{} (Completed)".format(m["level"])
        else:
            next_milestone_target = m["target_amount"]
            current_level         = "{} Target".format(m["level"])
            break

    return {
        "initial_capital":          initial,
        "target_capital":           target,
        "current_capital":          current_capital,
        "expected_capital_today":   round(expected_today, 2),
        "total_trading_days":       total_trading_days,
        "trading_days_elapsed":     trading_days_elapsed,
        "trading_days_remaining":   trading_days_remaining,
        "days_remaining_cal":       days_remaining,
        "progress_pct":             round(progress_pct, 1),
        "is_achieved":              current_capital >= target,
        "pace":                     pace,
        "pace_color":               pace_color,
        "pace_advice":              pace_advice,
        "diff_amount":              round(diff, 2),
        "daily_rate_pct":           comp.get("daily_rate_pct",   0.0),
        "monthly_rate_pct":         comp.get("monthly_rate_pct", 0.0),
        "feasibility":              comp.get("feasibility",      ""),
        "feasibility_color":        comp.get("feasibility_color",""),
        "today_target_pnl":         round(current_capital * daily_rate, 2),
        "today_max_risk":           round(current_capital * risk_pct / 100.0, 2),
        "today_max_daily_loss":     round(current_capital * max_loss_pct / 100.0, 2),
        "current_level":            current_level,
        "next_milestone_target":    round(next_milestone_target, 2),
        "milestones":               comp.get("milestones",   []),
        "schedule_df":              comp.get("schedule_df",  pd.DataFrame()),
    }
