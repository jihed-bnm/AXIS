"""
Deterministic churn recommendation engine.

Architecture:
  RULES registry → evaluate conditions against feature dict → ranked Recommendation list

Each rule is a dict with:
  id          — unique identifier
  condition   — callable(feature_dict) → bool
  priority    — "Critical" | "High" | "Medium" | "Low"
  category    — "Finance" | "Engagement" | "Sales" | "Customer Success" | "Executive"
  action      — short, business-facing sentence
  rationale   — callable(feature_dict) → str  OR  static str
  trigger     — feature key that fired this rule (for explainability)

Adding a new rule: append to RULES. No other file needs to change.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Union

# ── Priority ordering ──────────────────────────────────────────────────────────

_PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


# ── Safe value getter ──────────────────────────────────────────────────────────

def _v(d: dict, key: str, default: float = 0.0) -> float:
    """Return numeric value from dict, substituting default for None / NaN."""
    val = d.get(key, default)
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


# ── Recommendation dataclass ───────────────────────────────────────────────────

@dataclass
class Recommendation:
    priority: str        # Critical / High / Medium / Low
    category: str        # Finance / Engagement / Sales / Customer Success / Executive
    action: str          # One-sentence business action
    rationale: str       # Why this rule fired (human-readable)
    trigger: str         # Feature that triggered this rule


# ── Rule helpers ───────────────────────────────────────────────────────────────

def _rule(
    id: str,
    condition: Callable[[dict], bool],
    priority: Union[str, Callable[[dict], str]],
    category: str,
    action: str,
    rationale: Union[str, Callable[[dict], str]],
    trigger: str,
) -> dict:
    return dict(
        id=id,
        condition=condition,
        priority=priority,
        category=category,
        action=action,
        rationale=rationale,
        trigger=trigger,
    )


# ── Rule registry ──────────────────────────────────────────────────────────────
# Order matters only for documentation; final ranking is by priority value.

RULES: list[dict] = [

    # ── Finance ───────────────────────────────────────────────────────────────

    _rule(
        id="payment_delay_critical",
        condition=lambda f: _v(f, "avg_payment_delay") > 60,
        priority="Critical",
        category="Finance",
        action="Initiate an urgent financial review — propose payment restructuring or instalment plan before next invoice cycle",
        rationale=lambda f: f"Average payment delay is {_v(f,'avg_payment_delay'):.0f} days (critical threshold: 60)",
        trigger="avg_payment_delay",
    ),
    _rule(
        id="payment_delay_high",
        condition=lambda f: 30 < _v(f, "avg_payment_delay") <= 60,
        priority="High",
        category="Finance",
        action="Contact the finance contact to review payment terms and schedule a follow-up before the next due date",
        rationale=lambda f: f"Average payment delay is {_v(f,'avg_payment_delay'):.0f} days (high threshold: 30)",
        trigger="avg_payment_delay",
    ),
    _rule(
        id="overdue_ratio_high",
        condition=lambda f: _v(f, "overdue_ratio") > 0.40,
        priority="High",
        category="Finance",
        action="Escalate overdue invoices to the account manager — offer a structured resolution meeting with the finance team",
        rationale=lambda f: f"{_v(f,'overdue_ratio')*100:.0f}% of invoices are overdue (threshold: 40%)",
        trigger="overdue_ratio",
    ),
    _rule(
        id="low_payment_rate",
        condition=lambda f: _v(f, "payment_rate", 1.0) < 0.60,
        priority="High",
        category="Finance",
        action="Review invoicing process — consider partial-payment milestones or revised credit terms to reduce collection friction",
        rationale=lambda f: f"Payment rate is {_v(f,'payment_rate',1.0)*100:.0f}% (threshold: 60%)",
        trigger="payment_rate",
    ),

    # ── Engagement / Activities ───────────────────────────────────────────────

    _rule(
        id="inactivity_critical",
        condition=lambda f: _v(f, "days_since_last_activity", 9999) > 90,
        priority="Critical",
        category="Customer Success",
        action="Assign a dedicated customer success manager and schedule an account health check-in this week",
        rationale=lambda f: f"No activity recorded for {_v(f,'days_since_last_activity',9999):.0f} days (critical threshold: 90)",
        trigger="days_since_last_activity",
    ),
    _rule(
        id="inactivity_moderate",
        condition=lambda f: 45 < _v(f, "days_since_last_activity", 0) <= 90,
        priority="Medium",
        category="Engagement",
        action="Schedule a touchpoint call or send a personalised check-in email from the account manager",
        rationale=lambda f: f"No activity recorded for {_v(f,'days_since_last_activity',0):.0f} days (threshold: 45)",
        trigger="days_since_last_activity",
    ),
    _rule(
        id="high_churn_signals",
        condition=lambda f: _v(f, "churn_signal_ratio") > 0.30,
        priority="High",
        category="Customer Success",
        action="Review recent activity notes for specific complaints — address root causes directly with the client within 5 business days",
        rationale=lambda f: f"{_v(f,'churn_signal_ratio')*100:.0f}% of interactions contain negative signals (threshold: 30%)",
        trigger="churn_signal_ratio",
    ),
    _rule(
        id="zero_meetings",
        condition=lambda f: _v(f, "act_reunion") == 0 and _v(f, "total_activities") >= 3,
        priority="Medium",
        category="Engagement",
        action="Request an in-person or video meeting — face-to-face visibility is below baseline for this account",
        rationale="Zero meetings recorded despite ongoing account activity",
        trigger="act_reunion",
    ),
    _rule(
        id="no_positive_signals",
        condition=lambda f: _v(f, "positive_signal_count") == 0 and _v(f, "total_activities") >= 5,
        priority="Medium",
        category="Engagement",
        action="Send an NPS or satisfaction survey — gather structured feedback to identify unmet needs",
        rationale="No positive engagement signals recorded across an extended interaction history",
        trigger="positive_signal_count",
    ),
    _rule(
        id="low_activity_frequency",
        condition=lambda f: 0 < _v(f, "activity_frequency") < 0.5 and _v(f, "client_age_days") > 180,
        priority="Low",
        category="Engagement",
        action="Increase contact cadence — recommend monthly check-in rhythm to rebuild engagement",
        rationale=lambda f: f"Activity frequency is {_v(f,'activity_frequency'):.2f} interactions/month (below 0.5)",
        trigger="activity_frequency",
    ),

    # ── Sales / Deals ─────────────────────────────────────────────────────────

    _rule(
        id="zero_win_rate",
        condition=lambda f: (
            not math.isnan(f.get("win_rate") or float("nan"))
            and _v(f, "win_rate", -1) == 0.0
            and _v(f, "total_deals") >= 2
        ),
        priority="High",
        category="Sales",
        action="Initiate a sales re-engagement review — audit lost deals for pricing, fit, or scope issues and update the value proposition",
        rationale=lambda f: f"Win rate is 0% across {_v(f,'total_deals'):.0f} deals",
        trigger="win_rate",
    ),
    _rule(
        id="low_win_rate",
        condition=lambda f: (
            not math.isnan(f.get("win_rate") or float("nan"))
            and 0 < _v(f, "win_rate", 1) < 0.25
            and _v(f, "total_deals") >= 2
        ),
        priority="Medium",
        category="Sales",
        action="Conduct a deal review session with the sales team — identify blockers and refresh the competitive positioning",
        rationale=lambda f: f"Win rate is {_v(f,'win_rate',1)*100:.0f}% (threshold: 25%)",
        trigger="win_rate",
    ),
    _rule(
        id="many_open_stalled_deals",
        condition=lambda f: _v(f, "open_deals") >= 3 and _v(f, "win_rate", 1) < 0.30,
        priority="Medium",
        category="Sales",
        action="Review stalled pipeline deals with the account executive — prioritise or formally close dormant opportunities",
        rationale=lambda f: f"{_v(f,'open_deals'):.0f} open deals with {_v(f,'win_rate',1)*100:.0f}% win rate",
        trigger="open_deals",
    ),

    # ── Strategic / Account size ──────────────────────────────────────────────

    _rule(
        id="high_value_account",
        condition=lambda f: _v(f, "total_invoiced") > 50_000,
        priority="High",
        category="Executive",
        action="Escalate to account director — strategic account requires proactive executive-level engagement and a formal retention plan",
        rationale=lambda f: f"High-value account: {_v(f,'total_invoiced'):,.0f} TND invoiced",
        trigger="total_invoiced",
    ),
    _rule(
        id="new_client_low_engagement",
        condition=lambda f: _v(f, "client_age_days", 999) < 180 and _v(f, "total_activities") < 3,
        priority="High",
        category="Customer Success",
        action="Accelerate onboarding programme — new client shows insufficient engagement and is at early-churn risk",
        rationale=lambda f: f"Client is {_v(f,'client_age_days',0):.0f} days old with only {_v(f,'total_activities'):.0f} recorded activities",
        trigger="client_age_days",
    ),
]


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_recommendations(
    feature_dict: dict,
    risk_level: str,
    max_results: int = 5,
) -> list[Recommendation]:
    """
    Evaluate all rules against the feature dict and return up to max_results
    Recommendation objects sorted by priority (Critical first).

    Args:
        feature_dict: raw feature values for one company (from build_single_company_features)
        risk_level:   "High" | "Medium" | "Low" (from ML model)
        max_results:  cap on number of recommendations returned
    """
    fired: list[Recommendation] = []
    seen_categories: dict[str, int] = {}  # category → count

    for rule in RULES:
        try:
            if not rule["condition"](feature_dict):
                continue
        except Exception:
            continue

        # Limit to 2 recommendations per category to avoid flooding
        cat = rule["category"]
        if seen_categories.get(cat, 0) >= 2:
            continue
        seen_categories[cat] = seen_categories.get(cat, 0) + 1

        prio = rule["priority"]
        rat = rule["rationale"]
        rationale_str = rat(feature_dict) if callable(rat) else rat

        fired.append(Recommendation(
            priority=prio,
            category=cat,
            action=rule["action"],
            rationale=rationale_str,
            trigger=rule["trigger"],
        ))

    fired.sort(key=lambda r: _PRIORITY_RANK.get(r.priority, 99))
    return fired[:max_results]
