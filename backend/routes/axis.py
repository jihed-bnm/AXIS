"""AXIS — Agentic eXecution & Intelligence System — backend routes."""
from __future__ import annotations

import asyncio
import os
import secrets
import smtplib
import subprocess
import sys
import threading
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import json
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text

from backend.models.database import engine
from backend.auth import (
    verify_password, hash_password, create_access_token,
    get_current_user, require_admin,
)

router = APIRouter()

# ── Activity log bootstrap ────────────────────────────────────────────────────

def _init_activity_log() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS public.axis_activity_log (
                    id          SERIAL PRIMARY KEY,
                    timestamp   TIMESTAMP DEFAULT NOW(),
                    action_type TEXT,
                    entity      TEXT,
                    details     TEXT,
                    status      TEXT
                )
            """))
            conn.execute(text("""
                ALTER TABLE public.axis_activity_log
                ADD COLUMN IF NOT EXISTS username TEXT
            """))
            conn.commit()
    except Exception as exc:
        print(f"[AXIS] axis_activity_log init warning: {exc}")


_init_activity_log()


def _init_charts_table() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS public.axis_charts (
                    chart_id    SERIAL PRIMARY KEY,
                    title       TEXT NOT NULL,
                    chart_type  TEXT NOT NULL,
                    config      TEXT NOT NULL,
                    query_used  TEXT,
                    created_at  TIMESTAMP DEFAULT NOW(),
                    session_id  TEXT
                )
            """))
            conn.commit()
    except Exception as exc:
        print(f"[AXIS] axis_charts init warning: {exc}")


_init_charts_table()


def _init_users() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS public.axis_users (
                    user_id       SERIAL PRIMARY KEY,
                    username      TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'user',
                    full_name     TEXT,
                    created_at    TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
            # Seed default users
            seeds = [
                ("admin",   "axis2024", "admin", "Administrator"),
                ("jihed",   "jbm2024",  "user",  "Jihed Ben Messaoud"),
                ("analyst", "axis2024", "user",  "Data Analyst"),
            ]
            for username, password, role, full_name in seeds:
                conn.execute(text("""
                    INSERT INTO public.axis_users (username, password_hash, role, full_name)
                    VALUES (:u, :h, :r, :f)
                    ON CONFLICT (username) DO NOTHING
                """), {"u": username, "h": hash_password(password), "r": role, "f": full_name})
            conn.commit()
    except Exception as exc:
        print(f"[AXIS] axis_users init warning: {exc}")


_init_users()


def _log(action_type: str, entity: str, details: str, status: str = "success",
         username: Optional[str] = None) -> None:
    try:
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO public.axis_activity_log
                        (action_type, entity, details, status, username)
                    VALUES (:a, :e, :d, :s, :u)
                """),
                {"a": action_type, "e": entity, "d": details, "s": status, "u": username},
            )
            conn.commit()
    except Exception:
        pass


# ── SQL helpers ───────────────────────────────────────────────────────────────

def _query(sql: str, params: dict | None = None) -> list[dict]:
    with engine.connect() as conn:
        res = conn.execute(text(sql), params or {})
        keys = list(res.keys())
        return [dict(zip(keys, row)) for row in res.fetchall()]


def _one(sql: str, params: dict | None = None) -> dict:
    rows = _query(sql, params)
    return rows[0] if rows else {}


# ── Email helper ─────────────────────────────────────────────────────────────

def _send_credentials_email(to_email: str, username: str, password: str, full_name: str) -> None:
    smtp_email    = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_APP_PASSWORD")
    if not smtp_email or not smtp_password:
        raise ValueError("SMTP credentials not configured in .env")

    msg = MIMEMultipart()
    msg["From"]    = smtp_email
    msg["To"]      = to_email
    msg["Subject"] = "Your AXIS Platform Credentials"

    body = f"""Hello {full_name},

Your account on the AXIS platform has been created.

Username: {username}
Password: {password}

Please log in at the platform URL and change your password after first login.

Best regards,
AXIS Administration"""

    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.send_message(msg)


# ── Admin user management ─────────────────────────────────────────────────────

class ProvisionUserRequest(BaseModel):
    email:     str
    full_name: str
    role:      str  # "user" or "admin"


@router.post("/api/admin/provision-user")
def provision_user(body: ProvisionUserRequest, admin: dict = Depends(require_admin)):
    email     = body.email.strip()
    full_name = body.full_name.strip()
    role      = body.role if body.role in ("user", "admin") else "user"

    # Derive username from email local-part
    base_username = email.split("@")[0]
    username = base_username
    existing = _one(
        "SELECT username FROM public.axis_users WHERE username = :u",
        {"u": username},
    )
    if existing:
        username = f"{base_username}{secrets.randbelow(900) + 100}"

    password = secrets.token_urlsafe(9)
    pw_hash  = hash_password(password)

    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO public.axis_users (username, password_hash, role, full_name)
                VALUES (:u, :h, :r, :f)
            """),
            {"u": username, "h": pw_hash, "r": role, "f": full_name},
        )
        conn.commit()

    admin_username = admin.get("username")
    _log("provision", "user", f"Created user {username} for {email}", username=admin_username)

    email_status = "sent"
    try:
        _send_credentials_email(email, username, password, full_name)
    except Exception as exc:
        email_status = "failed"
        _log("provision", "user", f"Email failed for {username}: {exc}", status="warning",
             username=admin_username)

    result: dict = {
        "username":  username,
        "email":     email,
        "role":      role,
        "full_name": full_name,
        "message":   "Credentials sent to email",
    }
    if email_status == "failed":
        result["email_status"] = "failed"
        result["password"]     = password  # expose so admin can relay manually
    return result


@router.get("/api/admin/users")
def list_users(admin: dict = Depends(require_admin)):
    rows = _query("""
        SELECT user_id, username, role, full_name, created_at
        FROM public.axis_users
        ORDER BY created_at ASC
    """)
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
    return rows


@router.delete("/api/admin/users/{user_id}")
def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    row = _one(
        "SELECT username FROM public.axis_users WHERE user_id = :uid",
        {"uid": user_id},
    )
    if not row:
        raise HTTPException(404, f"User {user_id} not found")
    if row["username"] == admin.get("username"):
        raise HTTPException(400, "Cannot delete your own account")
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM public.axis_users WHERE user_id = :uid"),
            {"uid": user_id},
        )
        conn.commit()
    _log("delete", "user", f"Deleted user {row['username']} (id={user_id})",
         username=admin.get("username"))
    return {"deleted": user_id}


# ── ETL state ─────────────────────────────────────────────────────────────────

_etl: dict = {"status": "idle", "last_run": None}

# ── Serve frontend ────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_axis():
    html_path = Path(__file__).resolve().parent.parent.parent / "static" / "axis.html"
    if not html_path.exists():
        raise HTTPException(404, "axis.html not found")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ── Auth endpoints ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/api/auth/login")
def auth_login(body: LoginRequest):
    row = _one(
        "SELECT username, password_hash, role, full_name FROM public.axis_users WHERE username = :u",
        {"u": body.username},
    )
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({
        "sub":       row["username"],
        "username":  row["username"],
        "role":      row["role"],
        "full_name": row["full_name"],
    })
    return {
        "token":     token,
        "username":  row["username"],
        "role":      row["role"],
        "full_name": row["full_name"],
    }


@router.get("/api/auth/me")
def auth_me(user: dict = Depends(get_current_user)):
    return {
        "username":  user.get("username"),
        "role":      user.get("role"),
        "full_name": user.get("full_name"),
    }


# ── CRM endpoints ─────────────────────────────────────────────────────────────

@router.get("/api/crm/kpis")
def crm_kpis(user: dict = Depends(get_current_user)):
    try:
        rev = _one(
            "SELECT COALESCE(SUM(total_amount),0) AS v "
            "FROM warehouse.fact_revenue WHERE status='paid'"
        )
        deals = _one("SELECT COUNT(*) AS v FROM warehouse.fact_deals")
        wl = _one("""
            SELECT
                COUNT(*) FILTER (WHERE status='won')                   AS won,
                COUNT(*) FILTER (WHERE status IN ('won','lost'))        AS closed
            FROM warehouse.fact_deals
        """)
        pip = _one(
            "SELECT COALESCE(SUM(value_tnd),0) AS v "
            "FROM warehouse.fact_deals WHERE status='open'"
        )
        won    = int(wl.get("won")    or 0)
        closed = int(wl.get("closed") or 0)
        return {
            "total_revenue":   float(rev.get("v")  or 0),
            "total_deals":     int(deals.get("v")   or 0),
            "win_rate":        round(won / closed * 100, 1) if closed else 0.0,
            "active_pipeline": float(pip.get("v")  or 0),
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/crm/revenue-trend")
def crm_revenue_trend(user: dict = Depends(get_current_user)):
    try:
        rows = _query("""
            SELECT EXTRACT(year  FROM invoice_date)::int AS yr,
                   EXTRACT(month FROM invoice_date)::int AS mo,
                   SUM(total_amount)                     AS revenue
            FROM warehouse.fact_revenue
            WHERE status='paid'
              AND invoice_date IS NOT NULL
              AND invoice_date <= CURRENT_DATE
            GROUP BY 1,2 ORDER BY 1,2
        """)
        for r in rows:
            r["date"]    = f"{r.pop('yr')}-{int(r.pop('mo')):02d}-01"
            r["revenue"] = float(r["revenue"] or 0)
        return rows
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/crm/win-rate")
def crm_win_rate(user: dict = Depends(get_current_user)):
    try:
        rows = _query("""
            SELECT quarter,
                   ROUND(
                       COUNT(*) FILTER (WHERE status='won') * 100.0
                       / NULLIF(COUNT(*), 0),
                   1) AS win_rate
            FROM warehouse.fact_deals
            WHERE status IN ('won','lost')
            GROUP BY quarter
            ORDER BY MIN(created_date)
        """)
        for r in rows:
            r["win_rate"] = float(r["win_rate"] or 0)
        return rows
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/crm/pipeline-stage")
def crm_pipeline_stage(user: dict = Depends(get_current_user)):
    try:
        return _query("""
            SELECT stage, COUNT(DISTINCT deal_ref) AS deal_count
            FROM warehouse.fact_deals
            WHERE stage IS NOT NULL
            GROUP BY stage ORDER BY deal_count DESC
        """)
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/crm/top-clients")
def crm_top_clients(user: dict = Depends(get_current_user)):
    try:
        rows = _query("""
            SELECT UPPER(TRIM(company_name)) AS company_name,
                   SUM(value_tnd)            AS total_value
            FROM warehouse.fact_deals
            WHERE status='won'
              AND company_name IS NOT NULL
              AND value_tnd    IS NOT NULL
            GROUP BY UPPER(TRIM(company_name))
            ORDER BY total_value DESC
            LIMIT 10
        """)
        for r in rows:
            r["total_value"] = float(r["total_value"] or 0)
        return rows
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/crm/new-vs-closed")
def crm_new_vs_closed(user: dict = Depends(get_current_user)):
    try:
        new_rows = _query("""
            SELECT DATE_TRUNC('month', created_date)::date AS month,
                   COUNT(*) AS count
            FROM warehouse.fact_deals
            WHERE created_date <= CURRENT_DATE
            GROUP BY 1 ORDER BY 1
        """)
        closed_rows = _query("""
            SELECT DATE_TRUNC('month', closed_date)::date AS month,
                   COUNT(*) AS count
            FROM warehouse.fact_deals
            WHERE status IN ('won', 'lost') AND closed_date IS NOT NULL
              AND closed_date <= CURRENT_DATE
            GROUP BY 1 ORDER BY 1
        """)
        return {
            "new_deals":    [{"month": str(r["month"]), "count": int(r["count"])} for r in new_rows],
            "closed_deals": [{"month": str(r["month"]), "count": int(r["count"])} for r in closed_rows],
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/crm/deal-size")
def crm_deal_size(user: dict = Depends(get_current_user)):
    try:
        return _query("""
            SELECT deal_size_category, COUNT(*) AS deal_count
            FROM warehouse.fact_deals
            WHERE deal_size_category IS NOT NULL
            GROUP BY deal_size_category ORDER BY deal_count DESC
        """)
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Finance endpoints ─────────────────────────────────────────────────────────

@router.get("/api/finance/kpis")
def finance_kpis(user: dict = Depends(get_current_user)):
    try:
        r = _one("""
            SELECT
                COALESCE(SUM(CASE WHEN status='paid'    THEN total_amount END),0) AS collected,
                COALESCE(SUM(CASE WHEN status='pending' THEN total_amount END),0) AS pending,
                COALESCE(SUM(CASE WHEN status='overdue' THEN total_amount END),0) AS overdue,
                COUNT(*)                                                           AS total_count,
                COUNT(CASE WHEN status='paid' THEN 1 END)                         AS paid_count
            FROM warehouse.fact_revenue
        """)
        tc = int(r.get("total_count") or 0)
        pc = int(r.get("paid_count")  or 0)
        return {
            "collected":       float(r.get("collected") or 0),
            "pending":         float(r.get("pending")   or 0),
            "overdue":         float(r.get("overdue")   or 0),
            "collection_rate": round(pc / tc * 100, 1) if tc else 0.0,
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/finance/revenue-year")
def finance_revenue_year(user: dict = Depends(get_current_user)):
    try:
        rows = _query("""
            SELECT EXTRACT(year FROM invoice_date)::int AS year,
                   COALESCE(SUM(CASE WHEN status='paid'    THEN total_amount END),0) AS collected,
                   COALESCE(SUM(CASE WHEN status='pending' THEN total_amount END),0) AS pending,
                   COALESCE(SUM(CASE WHEN status='overdue' THEN total_amount END),0) AS overdue
            FROM warehouse.fact_revenue
            WHERE invoice_date IS NOT NULL AND invoice_date <= CURRENT_DATE
            GROUP BY 1 ORDER BY 1
        """)
        for r in rows:
            r["year"]      = int(r["year"])
            r["collected"] = float(r["collected"] or 0)
            r["pending"]   = float(r["pending"]   or 0)
            r["overdue"]   = float(r["overdue"]   or 0)
        return rows
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/finance/cumulative")
def finance_cumulative(user: dict = Depends(get_current_user)):
    try:
        rows = _query("""
            SELECT EXTRACT(year  FROM invoice_date)::int AS yr,
                   EXTRACT(month FROM invoice_date)::int AS mo,
                   SUM(total_amount) AS monthly_revenue
            FROM warehouse.fact_revenue
            WHERE status='paid'
              AND invoice_date IS NOT NULL
              AND invoice_date <= CURRENT_DATE
            GROUP BY 1,2 ORDER BY 1,2
        """)
        cum, result = 0.0, []
        for r in rows:
            cum += float(r["monthly_revenue"] or 0)
            result.append({
                "date":       f"{r['yr']}-{int(r['mo']):02d}-01",
                "cumulative": round(cum, 2),
            })
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/finance/payment-delay")
def finance_payment_delay(user: dict = Depends(get_current_user)):
    try:
        rows = _query("""
            SELECT
                CASE
                    WHEN payment_delay_days <= 0  THEN 'On Time'
                    WHEN payment_delay_days <= 30 THEN 'Late 1-30 days'
                    WHEN payment_delay_days <= 60 THEN 'Late 31-60 days'
                    ELSE                               'Late 60+ days'
                END AS delay_category,
                COUNT(*) AS count
            FROM warehouse.fact_revenue
            WHERE status='paid' AND payment_delay_days IS NOT NULL
            GROUP BY delay_category
        """)
        for r in rows:
            r["count"] = int(r["count"] or 0)
        return rows
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/finance/status-dist")
def finance_status_dist(user: dict = Depends(get_current_user)):
    try:
        return _query("""
            SELECT status, COUNT(*) AS invoice_count
            FROM warehouse.fact_revenue
            WHERE status IS NOT NULL AND invoice_date <= CURRENT_DATE
            GROUP BY status ORDER BY invoice_count DESC
        """)
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/finance/top-clients")
def finance_top_clients(user: dict = Depends(get_current_user)):
    try:
        rows = _query("""
            SELECT UPPER(TRIM(company_name)) AS company_name,
                   SUM(total_amount)         AS total_invoiced
            FROM warehouse.fact_revenue
            WHERE company_name IS NOT NULL
              AND total_amount  IS NOT NULL
              AND invoice_date <= CURRENT_DATE
            GROUP BY UPPER(TRIM(company_name))
            ORDER BY total_invoiced DESC
            LIMIT 10
        """)
        for r in rows:
            r["total_invoiced"] = float(r["total_invoiced"] or 0)
        return rows
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/finance/monthly")
def finance_monthly(user: dict = Depends(get_current_user)):
    try:
        rows = _query("""
            SELECT EXTRACT(year FROM invoice_date)::int AS year,
                   EXTRACT(month FROM invoice_date)::int AS month,
                   COUNT(*) AS issued,
                   COUNT(*) FILTER (WHERE status = 'paid') AS paid,
                   COUNT(*) FILTER (WHERE status = 'overdue' OR is_overdue = true) AS overdue
            FROM warehouse.fact_revenue
            WHERE invoice_date IS NOT NULL AND invoice_date <= CURRENT_DATE
            GROUP BY 1, 2 ORDER BY 1, 2
        """)
        for r in rows:
            r["year"]    = int(r["year"])
            r["month"]   = int(r["month"])
            r["issued"]  = int(r["issued"]  or 0)
            r["paid"]    = int(r["paid"]    or 0)
            r["overdue"] = int(r["overdue"] or 0)
        return rows
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Activity feed ─────────────────────────────────────────────────────────────

@router.get("/api/activity/feed")
def activity_feed(user: dict = Depends(get_current_user)):
    try:
        if user.get("role") == "admin":
            rows = _query("""
                SELECT id, timestamp, action_type, entity, details, status, username
                FROM public.axis_activity_log
                ORDER BY timestamp DESC
                LIMIT 50
            """)
        else:
            rows = _query("""
                SELECT id, timestamp, action_type, entity, details, status, username
                FROM public.axis_activity_log
                WHERE username = :u
                ORDER BY timestamp DESC
                LIMIT 50
            """, {"u": user.get("username")})
        for r in rows:
            if r.get("timestamp"):
                r["timestamp"] = r["timestamp"].isoformat()
        return rows
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Charts endpoints ──────────────────────────────────────────────────────────

@router.get("/api/charts")
def list_charts(user: dict = Depends(get_current_user)):
    try:
        rows = _query("""
            SELECT chart_id, title, chart_type, config, created_at, session_id
            FROM public.axis_charts
            ORDER BY created_at DESC
        """)
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("config") and isinstance(r["config"], str):
                try:
                    r["config"] = json.loads(r["config"])
                except Exception:
                    pass
        return rows
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.delete("/api/charts/{chart_id}")
def delete_chart(chart_id: int, user: dict = Depends(get_current_user)):
    try:
        row = _one(
            "SELECT chart_id FROM public.axis_charts WHERE chart_id = :cid",
            {"cid": chart_id},
        )
        if not row:
            raise HTTPException(404, f"Chart {chart_id} not found")
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM public.axis_charts WHERE chart_id = :cid"),
                {"cid": chart_id},
            )
            conn.commit()
        return {"deleted": chart_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── ETL trigger & status ──────────────────────────────────────────────────────

@router.post("/api/etl/trigger")
def etl_trigger(user: dict = Depends(require_admin)):
    global _etl
    if _etl["status"] == "running":
        return {"status": "already_running"}

    _etl["status"] = "running"
    _log("etl", "system", "ETL pipeline triggered via AXIS", username=user.get("username"))

    root = Path(__file__).resolve().parent.parent.parent

    def _run() -> None:
        global _etl
        try:
            res = subprocess.run(
                [sys.executable, "-m", "backend.etl.run_etl"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=600,
            )
            if res.returncode == 0:
                _etl["status"] = "success"
                _log("etl", "system", "ETL pipeline completed successfully")
            else:
                _etl["status"] = "failed"
                _log("etl", "system", f"ETL failed: {res.stderr[:200]}", "error")
        except Exception as exc:
            _etl["status"] = "failed"
            _log("etl", "system", f"ETL error: {exc}", "error")
        _etl["last_run"] = datetime.utcnow().isoformat()

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "running"}


@router.get("/api/etl/status")
def etl_status(user: dict = Depends(get_current_user)):
    return _etl


# ── Evaluation table bootstrap ────────────────────────────────────────────────

def _init_evaluations_table() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS public.axis_evaluations (
                    eval_id          SERIAL PRIMARY KEY,
                    run_at           TIMESTAMP DEFAULT NOW(),
                    summary          JSONB,
                    results          JSONB,
                    duration_seconds NUMERIC(6,2),
                    triggered_by     TEXT DEFAULT 'admin'
                )
            """))
            conn.commit()
    except Exception as exc:
        print(f"[AXIS] axis_evaluations init warning: {exc}")


_init_evaluations_table()


# ── Evaluation endpoints ──────────────────────────────────────────────────────

@router.get("/api/evaluation/stream")
async def stream_evaluation(token: Optional[str] = Query(default=None)):
    from backend.auth import decode_token as _decode
    # Manual token auth (EventSource cannot send headers)
    try:
        user = _decode(token or "")
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    async def generate():
        from backend.evaluation.evaluator import TEST_CASES, run_single_test
        import time

        start_time = time.time()
        results: list[dict] = []
        passed = partial = failed = 0
        overall = 0.0
        by_agent: dict = {}
        agent_summary: dict = {}

        yield f"data: {json.dumps({'type': 'start', 'total': len(TEST_CASES)})}\n\n"

        for i, test_case in enumerate(TEST_CASES):
            yield f"data: {json.dumps({'type': 'progress', 'current': i + 1, 'total': len(TEST_CASES), 'test_id': test_case['id']})}\n\n"

            result = await run_single_test(test_case, "http://localhost:8000")
            results.append(result)

            scores  = [r["score"] for r in results]
            overall = round(sum(scores) / len(scores), 1)
            passed  = sum(1 for r in results if r["verdict"] == "PASS")
            partial = sum(1 for r in results if r["verdict"] == "PARTIAL")
            failed  = sum(1 for r in results if r["verdict"] == "FAIL")

            for r in results:
                a = r["agent"]
                if a not in by_agent:
                    by_agent[a] = {"scores": [], "passed": 0, "partial": 0, "failed": 0}
            by_agent[result["agent"]]["scores"].append(result["score"])
            by_agent[result["agent"]][result["verdict"].lower()] += 1

            agent_summary = {
                a: {
                    "score":   round(sum(v["scores"]) / len(v["scores"]), 1),
                    "passed":  v["passed"],
                    "partial": v["partial"],
                    "failed":  v["failed"],
                    "total":   len(v["scores"]),
                }
                for a, v in by_agent.items()
            }

            running = {
                "overall_score": overall,
                "passed":        passed,
                "partial":       partial,
                "failed":        failed,
                "completed":     i + 1,
                "total":         len(TEST_CASES),
                "by_agent":      agent_summary,
            }
            yield f"data: {json.dumps({'type': 'result', 'result': result, 'running_summary': running})}\n\n"

            await asyncio.sleep(0.1)

        # Persist to DB
        duration = round(time.time() - start_time, 2)
        summary = {
            "total":         len(TEST_CASES),
            "passed":        passed,
            "partial":       partial,
            "failed":        failed,
            "overall_score": overall,
            "by_agent":      agent_summary,
        }
        try:
            with engine.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO public.axis_evaluations
                            (summary, results, duration_seconds, triggered_by)
                        VALUES (:s, :r, :d, :u)
                    """),
                    {
                        "s": json.dumps(summary),
                        "r": json.dumps(results),
                        "d": duration,
                        "u": user.get("username", "admin"),
                    },
                )
                conn.commit()
        except Exception as db_exc:
            print(f"[AXIS] eval persist error: {db_exc}")

        yield f"data: {json.dumps({'type': 'done', 'summary': summary, 'duration': duration})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":       "keep-alive",
        },
    )


@router.get("/api/evaluation/conversations")
async def evaluation_conversations(user: dict = Depends(require_admin), response: Response = None):
    """Return recent real chat sessions with their human/assistant exchange pairs."""
    if response is not None:
        response.headers["Cache-Control"] = "no-cache, no-store"
    try:
        rows = _query("""
            SELECT id, updated_at, messages
            FROM sessions
            WHERE id NOT LIKE 'eval-session-%%'
              AND updated_at > NOW() - INTERVAL '7 days'
            ORDER BY updated_at DESC
            LIMIT 10
        """)
        result = []
        for row in rows:
            msgs = row.get("messages") or []
            if isinstance(msgs, str):
                try:
                    msgs = json.loads(msgs)
                except Exception:
                    msgs = []
            # Build human→assistant pairs
            exchanges = []
            i = 0
            while i < len(msgs) - 1:
                m = msgs[i]
                nxt = msgs[i + 1]
                if m.get("role") == "human" and nxt.get("role") == "assistant":
                    exchanges.append({
                        "exchange_id": f"{row['id']}_{len(exchanges)}",
                        "question":    m.get("content", ""),
                        "response":    nxt.get("content", ""),
                        "timestamp":   row["updated_at"].isoformat() if row.get("updated_at") else None,
                    })
                    i += 2
                else:
                    i += 1
            if not exchanges:
                continue
            result.append({
                "session_id": row["id"],
                "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
                "exchanges":  exchanges[-5:],   # last 5 per session
            })
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc))


def _init_exchange_evaluations_table() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS public.axis_exchange_evaluations (
                    eval_id      SERIAL PRIMARY KEY,
                    exchange_id  TEXT NOT NULL,
                    session_id   TEXT,
                    question     TEXT,
                    response     TEXT,
                    score        INTEGER,
                    verdict      TEXT,
                    reasoning    TEXT,
                    evaluated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
    except Exception as exc:
        print(f"[AXIS] axis_exchange_evaluations init warning: {exc}")


_init_exchange_evaluations_table()


class ExchangeEvalRequest(BaseModel):
    exchange_id: str
    session_id:  Optional[str] = None
    question:    str
    response:    str


async def _judge_exchange(question: str, response: str) -> dict:
    import httpx, re
    prompt = f"""You are a strict evaluator for an ERP AI assistant.
You must be critical and accurate in your scoring.

User question: {question}
Agent response: {response}

Scoring rules — be strict:
- If the response says "I cannot", "I don't know", "error", or fails to answer → score 0-30, FAIL
- If the response is vague, generic, or gives no specific data → score 30-50, FAIL or PARTIAL
- If the response partially answers but misses key information → score 50-69, PARTIAL
- If the response directly answers with specific correct data → score 70-85, PASS
- If the response is complete, accurate, and includes relevant details → score 86-100, PASS

Be especially critical if:
- A factual question gets a non-factual answer
- The agent lists companies/deals instead of giving a count when count was asked
- The response is in the wrong language (question was in English, response in French = -20 points)
- The response asks clarifying questions instead of answering

Respond ONLY with this exact JSON format, nothing else:
{{"score": <integer 0-100>, "verdict": "<PASS|PARTIAL|FAIL>", "reasoning": "<one specific sentence about what was correct or wrong>"}}"""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "http://localhost:11434/api/generate",
                json={"model": "qwen2.5:7b", "prompt": prompt, "stream": False, "format": "json"},
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "{}")
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
            parsed  = json.loads(raw)
            score   = max(0, min(100, int(parsed.get("score", 0))))
            verdict = str(parsed.get("verdict", "FAIL")).upper()
            if verdict not in ("PASS", "PARTIAL", "FAIL"):
                verdict = "PASS" if score >= 70 else ("PARTIAL" if score >= 40 else "FAIL")
            return {"score": score, "verdict": verdict, "reasoning": str(parsed.get("reasoning", ""))}
    except Exception as exc:
        return {"score": 0, "verdict": "FAIL", "reasoning": f"Judge error: {exc}"}


@router.post("/api/evaluation/evaluate-exchange")
async def evaluate_exchange(body: ExchangeEvalRequest, user: dict = Depends(require_admin)):
    # Return cached result if already evaluated
    cached = _one(
        "SELECT score, verdict, reasoning FROM public.axis_exchange_evaluations WHERE exchange_id = :eid",
        {"eid": body.exchange_id},
    )
    if cached:
        return {"exchange_id": body.exchange_id, **cached}

    judgment = await _judge_exchange(body.question, body.response)
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO public.axis_exchange_evaluations
                    (exchange_id, session_id, question, response, score, verdict, reasoning)
                VALUES (:eid, :sid, :q, :r, :sc, :v, :rs)
            """),
            {
                "eid": body.exchange_id,
                "sid": body.session_id,
                "q":   body.question[:2000],
                "r":   body.response[:4000],
                "sc":  judgment["score"],
                "v":   judgment["verdict"],
                "rs":  judgment["reasoning"],
            },
        )
        conn.commit()
    return {"exchange_id": body.exchange_id, **judgment}


class SessionEvalRequest(BaseModel):
    session_id: str


@router.post("/api/evaluation/evaluate-session")
async def evaluate_session(body: SessionEvalRequest, user: dict = Depends(require_admin)):
    # Rebuild exchanges for this session
    row = _one(
        "SELECT id, updated_at, messages FROM sessions WHERE id = :sid",
        {"sid": body.session_id},
    )
    if not row:
        raise HTTPException(404, "Session not found")

    msgs = row.get("messages") or []
    if isinstance(msgs, str):
        try:
            msgs = json.loads(msgs)
        except Exception:
            msgs = []

    exchanges, i = [], 0
    while i < len(msgs) - 1:
        m, nxt = msgs[i], msgs[i + 1]
        if m.get("role") == "human" and nxt.get("role") == "assistant":
            exchanges.append({
                "exchange_id": f"{body.session_id}_{len(exchanges)}",
                "session_id":  body.session_id,
                "question":    m.get("content", ""),
                "response":    nxt.get("content", ""),
            })
            i += 2
        else:
            i += 1

    results = []
    for ex in exchanges[-5:]:
        cached = _one(
            "SELECT score, verdict, reasoning FROM public.axis_exchange_evaluations WHERE exchange_id = :eid",
            {"eid": ex["exchange_id"]},
        )
        if cached:
            results.append({"exchange_id": ex["exchange_id"], **cached})
            continue
        judgment = await _judge_exchange(ex["question"], ex["response"])
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO public.axis_exchange_evaluations
                        (exchange_id, session_id, question, response, score, verdict, reasoning)
                    VALUES (:eid, :sid, :q, :r, :sc, :v, :rs)
                """),
                {
                    "eid": ex["exchange_id"],
                    "sid": body.session_id,
                    "q":   ex["question"][:2000],
                    "r":   ex["response"][:4000],
                    "sc":  judgment["score"],
                    "v":   judgment["verdict"],
                    "rs":  judgment["reasoning"],
                },
            )
            conn.commit()
        results.append({"exchange_id": ex["exchange_id"], **judgment})

    scores = [r["score"] for r in results]
    avg    = round(sum(scores) / len(scores), 1) if scores else 0.0
    return {"session_id": body.session_id, "results": results, "average_score": avg}


@router.get("/api/evaluation/results")
def evaluation_results(user: dict = Depends(require_admin)):
    try:
        rows = _query("""
            SELECT eval_id, exchange_id, session_id, question, response,
                   score, verdict, reasoning, evaluated_at
            FROM public.axis_exchange_evaluations
            ORDER BY evaluated_at DESC
            LIMIT 50
        """)
        for r in rows:
            if r.get("evaluated_at"):
                r["evaluated_at"] = r["evaluated_at"].isoformat()
        return rows
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/evaluation/history")
def evaluation_history(user: dict = Depends(require_admin)):
    try:
        rows = _query("""
            SELECT eval_id, run_at, summary, duration_seconds, triggered_by
            FROM public.axis_evaluations
            ORDER BY run_at DESC
            LIMIT 10
        """)
        for r in rows:
            if r.get("run_at"):
                r["run_at"] = r["run_at"].isoformat()
            if r.get("summary") and isinstance(r["summary"], str):
                try:
                    r["summary"] = json.loads(r["summary"])
                except Exception:
                    pass
        return rows
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/evaluation/latest")
def evaluation_latest(user: dict = Depends(require_admin)):
    try:
        rows = _query("""
            SELECT eval_id, run_at, summary, results, duration_seconds, triggered_by
            FROM public.axis_evaluations
            ORDER BY run_at DESC
            LIMIT 1
        """)
        if not rows:
            return None
        r = rows[0]
        if r.get("run_at"):
            r["run_at"] = r["run_at"].isoformat()
        for field in ("summary", "results"):
            if r.get(field) and isinstance(r[field], str):
                try:
                    r[field] = json.loads(r[field])
                except Exception:
                    pass
        return r
    except Exception as exc:
        raise HTTPException(500, str(exc))
