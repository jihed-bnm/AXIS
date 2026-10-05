"""
LLM-based deal win-probability summary layer.

The LLM does NOT invent recommendations — it receives the deterministic
recommendation list and structured deal data, then writes a professional
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

_LABELS: dict[str, str] = {
    "value_tnd":                    "Deal Value (TND)",
    "days_to_close":                "Est. Days to Close",
    "probability":                  "CRM Probability",
    "client_age_days":              "Client Age (days)",
    "company_total_activities":     "Company Total Activities",
    "company_churn_signals":        "Company Churn Signals",
    "company_positive_signals":     "Company Positive Signals",
    "company_activity_frequency":   "Company Activity Frequency (per month)",
    "company_historical_win_rate":  "Company Historical Win Rate",
    "company_total_deals":          "Company Total Historical Deals",
    "company_avg_deal_value":       "Company Avg. Deal Value (TND)",
    "company_payment_rate":         "Company Payment Rate",
    "company_avg_payment_delay":    "Company Avg. Payment Delay (days)",
    "company_overdue_ratio":        "Company Overdue Invoice Ratio",
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
    deal_title: str,
    company: str,
    prob: float,
    outcome: str,
    recommendations: list[Recommendation],
) -> str:
    pct = f"{prob:.1%}"
    if recommendations:
        top = recommendations[0].action.rstrip(".")
        return (
            f"Deal '{deal_title}' for {company} has a {pct} win probability ({outcome}). "
            f"Top recommended action: {top}."
        )
    return (
        f"Deal '{deal_title}' for {company} has a {pct} win probability ({outcome}). "
        "Immediate sales review is advised."
    )


def summarize_deal(
    deal_title: str,
    company: str,
    prob: float,
    outcome: str,
    top_factors: list[dict],
    recommendations: list[Recommendation],
) -> str:
    """
    Ask the LLM to write a professional deal win-probability summary.

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
        "Summarise a deal win-probability assessment in 2–4 professional sentences.\n\n"
        "Hard rules:\n"
        "- Use only the data provided. Do not invent or assume any facts.\n"
        "- Do not add recommendations beyond those listed.\n"
        "- Do not use bullet points or headers — write flowing prose.\n"
        "- Do not open with 'Based on the analysis' or similar filler.\n"
        "- Be direct and action-oriented."
    )

    user = (
        f"Deal: {deal_title}\n"
        f"Company: {company}\n"
        f"Win Probability: {prob:.1%}\n"
        f"Outcome Prediction: {outcome}\n\n"
        f"Contributing Factors (from ML model):\n{factors_lines}\n\n"
        f"Sales Recommendations (deterministic):\n{recs_lines}\n\n"
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
        log.warning("deal_summarizer LLM call failed: %r — using fallback", exc)
        return _fallback(deal_title, company, prob, outcome, recommendations)
