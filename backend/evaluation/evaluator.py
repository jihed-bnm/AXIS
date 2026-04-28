"""AXIS Evaluation Framework — LLM-as-Judge with warehouse ground truth."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import text

from backend.models.database import engine

# ── Test cases ────────────────────────────────────────────────────────────────

TEST_CASES: list[dict] = [
    # CRM Agent tests
    {
        "id": "CRM-01",
        "agent": "CRM",
        "question": "How many total deals do we have?",
        "ground_truth_sql": "SELECT COUNT(*) FROM warehouse.fact_deals",
        "ground_truth_label": "total deals count",
    },
    {
        "id": "CRM-02",
        "agent": "CRM",
        "question": "What is the overall win rate?",
        "ground_truth_sql": (
            "SELECT ROUND(COUNT(*) FILTER (WHERE status='won') * 100.0"
            " / NULLIF(COUNT(*),0), 1)"
            " FROM warehouse.fact_deals WHERE status IN ('won','lost')"
        ),
        "ground_truth_label": "win rate percentage",
    },
    {
        "id": "CRM-03",
        "agent": "CRM",
        "question": "How many companies do we have in the CRM?",
        "ground_truth_sql": "SELECT COUNT(*) FROM companies WHERE is_deleted = false",
        "ground_truth_label": "total companies count",
    },
    {
        "id": "CRM-04",
        "agent": "CRM",
        "question": "What is the total value of the active pipeline?",
        "ground_truth_sql": (
            "SELECT COALESCE(SUM(value_tnd),0)"
            " FROM warehouse.fact_deals WHERE status='open'"
        ),
        "ground_truth_label": "active pipeline value in TND",
    },
    {
        "id": "CRM-05",
        "agent": "CRM",
        "question": "How many deals are in the negotiation stage?",
        "ground_truth_sql": (
            "SELECT COUNT(*) FROM warehouse.fact_deals WHERE stage='Negotiation'"
        ),
        "ground_truth_label": "deals in negotiation stage",
    },
    # Finance Agent tests
    {
        "id": "FIN-01",
        "agent": "Finance",
        "question": "What is the total collected revenue from paid invoices?",
        "ground_truth_sql": (
            "SELECT COALESCE(SUM(total_amount),0)"
            " FROM warehouse.fact_revenue WHERE status='paid'"
        ),
        "ground_truth_label": "total collected revenue in TND",
    },
    {
        "id": "FIN-02",
        "agent": "Finance",
        "question": "What is the collection rate?",
        "ground_truth_sql": (
            "SELECT ROUND(COUNT(*) FILTER (WHERE status='paid') * 100.0"
            " / NULLIF(COUNT(*),0), 1)"
            " FROM warehouse.fact_revenue"
        ),
        "ground_truth_label": "collection rate percentage",
    },
    {
        "id": "FIN-03",
        "agent": "Finance",
        "question": "How many invoices are overdue?",
        "ground_truth_sql": (
            "SELECT COUNT(*) FROM warehouse.fact_revenue WHERE status='overdue'"
        ),
        "ground_truth_label": "number of overdue invoices",
    },
    {
        "id": "FIN-04",
        "agent": "Finance",
        "question": "What is the total pending invoice amount?",
        "ground_truth_sql": (
            "SELECT COALESCE(SUM(total_amount),0)"
            " FROM warehouse.fact_revenue WHERE status='pending'"
        ),
        "ground_truth_label": "total pending amount in TND",
    },
    {
        "id": "FIN-05",
        "agent": "Finance",
        "question": "How many total invoices do we have?",
        "ground_truth_sql": "SELECT COUNT(*) FROM warehouse.fact_revenue",
        "ground_truth_label": "total invoice count",
    },
    # Data Analyst Agent tests
    {
        "id": "DA-01",
        "agent": "Data Analyst",
        "question": "create a bar chart of deal count by stage from fact_deals",
        "ground_truth_sql": (
            "SELECT stage, COUNT(*) FROM warehouse.fact_deals"
            " GROUP BY stage ORDER BY count DESC"
        ),
        "ground_truth_label": "chart created successfully with deal stages",
    },
    {
        "id": "DA-02",
        "agent": "Data Analyst",
        "question": "create a pie chart of invoice status distribution from fact_revenue",
        "ground_truth_sql": (
            "SELECT status, COUNT(*) FROM warehouse.fact_revenue GROUP BY status"
        ),
        "ground_truth_label": "chart created successfully with invoice statuses",
    },
]

# ── Ground truth helper ───────────────────────────────────────────────────────

def _fetch_ground_truth(sql: str) -> str:
    """Execute the SQL and return a string representation of the result."""
    try:
        with engine.connect() as conn:
            res = conn.execute(text(sql))
            rows = res.fetchall()
            if not rows:
                return "no data"
            if len(rows) == 1 and len(rows[0]) == 1:
                return str(rows[0][0])
            # Multi-row or multi-column: return as list of tuples
            keys = list(res.keys())
            return json.dumps([dict(zip(keys, row)) for row in rows[:10]])
    except Exception as exc:
        return f"SQL error: {exc}"


# ── Judge call ────────────────────────────────────────────────────────────────

JUDGE_MODEL = "qwen2.5:7b"
OLLAMA_URL  = "http://localhost:11434/api/generate"

def _build_judge_prompt(question: str, ground_truth_value: str,
                        ground_truth_label: str, agent_response: str) -> str:
    return f"""You are an evaluation judge for an ERP AI assistant.

Question asked: {question}
Ground truth value: {ground_truth_value} ({ground_truth_label})
Agent response: {agent_response}

Score the agent response from 0 to 100 based on:
- Factual correctness: Does the response contain the correct value?
- Completeness: Does it answer the question fully?
- Relevance: Is the response relevant to the question?

For Data Analyst agent: a score of 80+ if chart was created successfully.

Respond ONLY with valid JSON in this exact format:
{{"score": <0-100>, "verdict": "PASS|PARTIAL|FAIL", "reasoning": "<one sentence>"}}

PASS = score >= 70
PARTIAL = score 40-69
FAIL = score < 40"""


async def _call_judge(prompt: str) -> dict:
    """Call Ollama judge and return parsed JSON result."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={"model": JUDGE_MODEL, "prompt": prompt, "stream": False, "format": "json"},
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "{}")
            # Strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
            parsed = json.loads(raw)
            score   = int(parsed.get("score",   0))
            verdict = str(parsed.get("verdict", "FAIL")).upper()
            if verdict not in ("PASS", "PARTIAL", "FAIL"):
                verdict = "PASS" if score >= 70 else ("PARTIAL" if score >= 40 else "FAIL")
            return {
                "score":     score,
                "verdict":   verdict,
                "reasoning": str(parsed.get("reasoning", "")),
            }
    except Exception as exc:
        return {"score": 0, "verdict": "FAIL", "reasoning": f"Judge error: {exc}"}


# ── Single test runner ────────────────────────────────────────────────────────

async def run_single_test(test_case: dict, base_url: str) -> dict:
    """Run one test case and return a scored result dict."""
    test_id = test_case["id"]

    # 1. Ground truth from DB
    ground_truth_value = _fetch_ground_truth(test_case["ground_truth_sql"])

    # 2. Call the agent
    agent_response = ""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base_url}/chat",
                json={"message": test_case["question"],
                      "session_id": f"eval-session-{test_id}"},
            )
            resp.raise_for_status()
            data = resp.json()
            agent_response = data.get("response") or data.get("message") or str(data)
    except Exception as exc:
        agent_response = f"Agent call failed: {exc}"

    # 3. Judge scoring
    prompt = _build_judge_prompt(
        question=test_case["question"],
        ground_truth_value=ground_truth_value,
        ground_truth_label=test_case["ground_truth_label"],
        agent_response=agent_response,
    )
    judgment = await _call_judge(prompt)

    return {
        "test_id":        test_id,
        "agent":          test_case["agent"],
        "question":       test_case["question"],
        "ground_truth":   ground_truth_value,
        "agent_response": agent_response,
        "score":          judgment["score"],
        "verdict":        judgment["verdict"],
        "reasoning":      judgment["reasoning"],
    }


# ── Full evaluation runner ────────────────────────────────────────────────────

async def run_full_evaluation(base_url: str = "http://localhost:8000") -> dict:
    """Run all test cases and return aggregated results."""
    start = time.monotonic()
    results: list[dict] = []

    for tc in TEST_CASES:
        result = await run_single_test(tc, base_url)
        results.append(result)

    duration = round(time.monotonic() - start, 2)

    # ── Aggregate summary ──
    total   = len(results)
    passed  = sum(1 for r in results if r["verdict"] == "PASS")
    partial = sum(1 for r in results if r["verdict"] == "PARTIAL")
    failed  = sum(1 for r in results if r["verdict"] == "FAIL")
    overall_score = round(sum(r["score"] for r in results) / total, 1) if total else 0.0

    agents = ["CRM", "Finance", "Data Analyst"]
    by_agent: dict[str, Any] = {}
    for agent in agents:
        ag_results = [r for r in results if r["agent"] == agent]
        ag_total   = len(ag_results)
        ag_passed  = sum(1 for r in ag_results if r["verdict"] == "PASS")
        ag_partial = sum(1 for r in ag_results if r["verdict"] == "PARTIAL")
        ag_failed  = sum(1 for r in ag_results if r["verdict"] == "FAIL")
        ag_score   = round(sum(r["score"] for r in ag_results) / ag_total, 1) if ag_total else 0.0
        by_agent[agent] = {
            "total":   ag_total,
            "passed":  ag_passed,
            "partial": ag_partial,
            "failed":  ag_failed,
            "score":   ag_score,
        }

    return {
        "results": results,
        "summary": {
            "total":         total,
            "passed":        passed,
            "partial":       partial,
            "failed":        failed,
            "overall_score": overall_score,
            "by_agent":      by_agent,
        },
        "run_at":            datetime.now(timezone.utc).isoformat(),
        "duration_seconds":  duration,
    }
