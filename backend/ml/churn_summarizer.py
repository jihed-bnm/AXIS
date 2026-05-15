"""
LLM-based churn summary layer.

The LLM does NOT invent recommendations — it receives the deterministic
recommendation list and the structured churn data, then writes a professional
2–4 sentence business summary.

If the LLM call fails for any reason, a template-based fallback is returned.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.llm import get_llm
from backend.ml.recommendation_engine import Recommendation

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# ── Human-readable feature labels (mirrors frontend FEATURE_LABEL_MAP) ────────

_LABELS: dict[str, str] = {
    "total_activities":          "Total Activities",
    "days_since_last_activity":  "Days Since Last Activity",
    "churn_signal_count":        "Churn Signal Count",
    "positive_signal_count":     "Positive Signal Count",
    "activity_frequency":        "Activity Frequency (per month)",
    "churn_signal_ratio":        "Churn Signal Ratio",
    "act_appel":                 "Phone Calls",
    "act_email":                 "Emails",
    "act_reunion":               "Meetings Held",
    "act_task":                  "Tasks",
    "total_deals":               "Total Deals",
    "won_deals":                 "Won Deals",
    "lost_deals":                "Lost Deals",
    "open_deals":                "Open Deals",
    "win_rate":                  "Win Rate",
    "avg_deal_value":            "Avg. Deal Value (TND)",
    "total_deal_value":          "Total Deal Value (TND)",
    "avg_days_to_close":         "Avg. Days to Close",
    "total_invoiced":            "Total Invoiced (TND)",
    "total_paid":                "Total Paid (TND)",
    "avg_payment_delay":         "Avg. Payment Delay (days)",
    "overdue_count":             "Overdue Invoice Count",
    "overdue_ratio":             "Overdue Invoice Ratio",
    "payment_rate":              "Payment Rate",
    "total_invoices":            "Total Invoices",
    "client_age_days":           "Client Age (days)",
}


def _label(feature: str) -> str:
    return _LABELS.get(feature, feature.replace("_", " ").title())


def _fmt_value(value: float) -> str:
    if value == 0:
        return "0"
    if 0 < value < 1:
        return f"{value*100:.0f}%"
    return f"{value:.1f}"


def _fallback(
    company: str,
    prob: float,
    risk_level: str,
    recommendations: list[Recommendation],
) -> str:
    pct = f"{prob:.1%}"
    if recommendations:
        top = recommendations[0].action.rstrip(".")
        return (
            f"{company} carries a {risk_level.lower()} churn risk ({pct}). "
            f"The top recommended action is: {top}."
        )
    return f"{company} carries a {risk_level.lower()} churn risk ({pct}). Immediate account review is advised."


def summarize_churn(
    company: str,
    prob: float,
    risk_level: str,
    top_factors: list[dict],
    recommendations: list[Recommendation],
) -> str:
    """
    Ask the LLM to write a professional churn-risk summary.

    The LLM receives fully structured data and is constrained to:
    - Not invent new recommendations
    - Not add facts beyond what is provided
    - Produce 2–4 plain-English sentences

    Falls back to a template string if the LLM call fails.
    """
    factors_lines = "\n".join(
        f"  - {_label(f['feature'])}: {_fmt_value(f['value'])} (model weight: {f['importance']*100:.1f}%)"
        for f in top_factors
    )
    recs_lines = "\n".join(
        f"  [{r.priority}] {r.category}: {r.action}"
        for r in recommendations
    ) or "  No specific recommendations generated."

    system = (
        "You are a concise business intelligence assistant for a B2B ERP platform.\n"
        "Summarise a client churn risk assessment in 2–4 professional sentences.\n\n"
        "Hard rules:\n"
        "- Use only the data provided. Do not invent or assume any facts.\n"
        "- Do not add recommendations beyond those listed.\n"
        "- Do not use bullet points or headers — write flowing prose.\n"
        "- Do not open with 'Based on the analysis' or similar filler.\n"
        "- Be direct and action-oriented."
    )

    user = (
        f"Client: {company}\n"
        f"Churn Probability: {prob:.1%}\n"
        f"Risk Level: {risk_level}\n\n"
        f"Contributing Factors (from ML model):\n{factors_lines}\n\n"
        f"Retention Recommendations (deterministic):\n{recs_lines}\n\n"
        "Write the 2–4 sentence business summary now."
    )

    try:
        llm = get_llm(temperature=0.3)
        response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        text = response.content.strip()
        if len(text) < 20:
            raise ValueError("LLM returned empty response")
        return text
    except Exception as exc:
        log.warning("churn_summarizer LLM call failed: %r — using fallback", exc)
        return _fallback(company, prob, risk_level, recommendations)
