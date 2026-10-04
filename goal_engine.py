"""
goal_engine.py — Compounding & Goal Tracking Engine (Cloud & Local Compatible).
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta

def _get_default_goal():
    return {
        "goal_name": "Roadmap to ₹10 Lakh",
        "initial_capital": 50000.0,
        "target_capital": 1000000.0,
        "start_date": datetime.today().strftime("%Y-%m-%d"),
        "target_date": (datetime.today() + timedelta(days=180)).strftime("%Y-%m-%d"),
        "target_months": 6,
        "trading_days_per_month": 20,
        "risk_per_trade_pct": 1.5,
        "risk_reward_ratio": 2.0,
        "max_daily_loss_pct": 3.0,
        "active": True,
        "completed": False,
        "history": []
    }


def load_goal_cloud(cap_data: dict = None) -> dict:
    """Load goal settings from capital data dict or session state or defaults."""
    import streamlit as st
    if "trading_goal" in st.session_state:
        return st.session_state["trading_goal"]
    
    if cap_data and "goal" in cap_data:
        g = cap_data["goal"]
        defaults = _get_default_goal()
        for k, v in defaults.items():
            if k not in g:
                g[k] = v
        st.session_state["trading_goal"] = g
        return g

    defaults = _get_default_goal()
    st.session_state["trading_goal"] = defaults
    return defaults


def save_goal_cloud(goal_data: dict, save_cap_fn=None, cap_data: dict = None) -> bool:
    """Save goal to st.session_state and optionally to Google Sheets via cap_data."""
    import streamlit as st
    st.session_state["trading_goal"] = goal_data
    if save_cap_fn and cap_data is not None:
        cap_data["goal"] = goal_data
        save_cap_fn(cap_data)
    return True


def calculate_compounding_schedule(initial_capital: float, target_capital: float, total_trading_days: int) -> dict:
    if initial_capital <= 0 or target_capital <= initial_capital or total_trading_days <= 0:
        return {
            "daily_rate_pct": 0.0,
            "monthly_rate_pct": 0.0,
            "feasibility": "Invalid inputs",
            "feasibility_color": "gray",
            "schedule_df": pd.DataFrame(),
            "milestones": []
        }

    daily_rate = (target_capital / initial_capital) ** (1.0 / total_trading_days) - 1.0
    daily_rate_pct = daily_rate * 100.0

    monthly_rate = ((1.0 + daily_rate) ** 20) - 1.0
    monthly_rate_pct = monthly_rate * 100.0

    if daily_rate_pct <= 0.8:
        feasibility = "Realistic & Sustainable (Pro Level: ~0.5% - 0.8%/day)"
        feasibility_color = "#10b981"
    elif daily_rate_pct <= 1.5:
        feasibility = "Moderate to Aggressive (~0.8% - 1.5%/day)"
        feasibility_color = "#f59e0b"
    elif daily_rate_pct <= 2.5:
        feasibility = "High Risk / Very Aggressive (~1.5% - 2.5%/day)"
        feasibility_color = "#ef4444"
    else:
        feasibility = "Extremely Aggressive (> 2.5%/day) - High Risk of Drawdown"
        feasibility_color = "#b91c1c"

    days = list(range(0, total_trading_days + 1))
    trajectory = [initial_capital * ((1.0 + daily_rate) ** d) for d in days]
    
    milestones = []
    ratios = [0.1, 0.25, 0.5, 0.75, 1.0]
    span = target_capital - initial_capital
    for idx, r in enumerate(ratios, 1):
        target_val = initial_capital + span * r
        cross_day = int(np.ceil(np.log(target_val / initial_capital) / np.log(1.0 + daily_rate))) if daily_rate > 0 else 0
        milestones.append({
            "level": f"Level {idx}",
            "target_amount": round(target_val, 2),
            "target_day": cross_day,
            "percentage": int(r * 100)
        })

    schedule_df = pd.DataFrame({
        "Day": days,
        "Target_Capital": [round(x, 2) for x in trajectory]
    })

    return {
        "daily_rate": daily_rate,
        "daily_rate_pct": round(daily_rate_pct, 3),
        "monthly_rate_pct": round(monthly_rate_pct, 2),
        "feasibility": feasibility,
        "feasibility_color": feasibility_color,
        "milestones": milestones,
        "schedule_df": schedule_df
    }


def evaluate_goal_progress(goal_data: dict, current_capital: float) -> dict:
    initial = float(goal_data.get("initial_capital", 50000.0))
    target = float(goal_data.get("target_capital", 1000000.0))
    start_str = goal_data.get("start_date", datetime.today().strftime("%Y-%m-%d"))
    target_str = goal_data.get("target_date", (datetime.today() + timedelta(days=180)).strftime("%Y-%m-%d"))

    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
    except Exception:
        start_date = datetime.today().date()
    try:
        target_date = datetime.strptime(target_str, "%Y-%m-%d").date()
    except Exception:
        target_date = (datetime.today() + timedelta(days=180)).date()

    today = datetime.today().date()
    total_calendar_days = max(1, (target_date - start_date).days)
    days_elapsed = max(0, (today - start_date).days)
    days_remaining = max(0, (target_date - today).days)

    total_trading_days = max(1, int(total_calendar_days * (5 / 7)))
    trading_days_elapsed = min(total_trading_days, int(days_elapsed * (5 / 7)))
    trading_days_remaining = max(1, total_trading_days - trading_days_elapsed)

    comp_info = calculate_compounding_schedule(initial, target, total_trading_days)
    daily_rate = comp_info.get("daily_rate", 0.01)

    expected_capital_today = initial * ((1.0 + daily_rate) ** trading_days_elapsed)
    expected_capital_today = min(target, expected_capital_today)

    progress_pct = max(0.0, min(100.0, ((current_capital - initial) / max(1.0, (target - initial))) * 100.0))
    is_goal_achieved = current_capital >= target

    diff = current_capital - expected_capital_today

    if diff >= (0.02 * current_capital):
        pace = "Ahead of Pace 🚀"
        pace_color = "#10b981"
        pace_advice = "Capital is ahead of target trajectory. Protect profits, stick to A+ setups and avoid increasing risk unnecessarily."
    elif diff >= -(0.02 * current_capital):
        pace = "On Track 🎯"
        pace_color = "#3b82f6"
        pace_advice = "Trading right on benchmark compounding trajectory. Keep executing with disciplined risk-to-reward."
    else:
        pace = "Behind Pace ⚠️"
        pace_color = "#f59e0b"
        pace_advice = "Behind schedule. Do NOT revenge trade or oversized lots. Stick strictly to 1:2 R:R trades to recover systematically."

    risk_pct = float(goal_data.get("risk_per_trade_pct", 1.5))
    max_loss_pct = float(goal_data.get("max_daily_loss_pct", 3.0))

    today_target_pnl = current_capital * daily_rate
    today_max_risk = current_capital * (risk_pct / 100.0)
    today_max_daily_loss = current_capital * (max_loss_pct / 100.0)

    current_level = "Level 1"
    next_milestone_target = target
    for m in comp_info.get("milestones", []):
        if current_capital >= m["target_amount"]:
            current_level = f"{m['level']} (Completed)"
        else:
            next_milestone_target = m["target_amount"]
            current_level = f"{m['level']} Target"
            break

    return {
        "initial_capital": initial,
        "target_capital": target,
        "current_capital": current_capital,
        "expected_capital_today": round(expected_capital_today, 2),
        "total_trading_days": total_trading_days,
        "trading_days_elapsed": trading_days_elapsed,
        "trading_days_remaining": trading_days_remaining,
        "days_remaining_cal": days_remaining,
        "progress_pct": round(progress_pct, 1),
        "is_achieved": is_goal_achieved,
        "pace": pace,
        "pace_color": pace_color,
        "pace_advice": pace_advice,
        "diff_amount": round(diff, 2),
        "daily_rate_pct": comp_info.get("daily_rate_pct", 0.0),
        "monthly_rate_pct": comp_info.get("monthly_rate_pct", 0.0),
        "feasibility": comp_info.get("feasibility", ""),
        "feasibility_color": comp_info.get("feasibility_color", ""),
        "today_target_pnl": round(today_target_pnl, 2),
        "today_max_risk": round(today_max_risk, 2),
        "today_max_daily_loss": round(today_max_daily_loss, 2),
        "current_level": current_level,
        "next_milestone_target": round(next_milestone_target, 2),
        "milestones": comp_info.get("milestones", []),
        "schedule_df": comp_info.get("schedule_df", pd.DataFrame())
    }
