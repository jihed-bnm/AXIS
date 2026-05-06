"""
FastAPI main app — AXIS backend
"""
import logging

# Configure logging BEFORE any backend module is imported so that all
# subsequent getLogger() calls inherit our handlers.
from logging_config import setup_logging
setup_logging()

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import json
import uuid
import os
import re
from datetime import datetime

from backend.models.database import create_tables, get_session
from backend.models.crm_models import Session as ChatSession
from backend.agents.supervisor import run_agent, _is_positive_confirmation, _is_negative_confirmation, _WRITE_PREVIEW_PATTERNS
from backend.agents.context import (
    get_pending_action, clear_pending_action,
    get_rag_context, clear_rag_context,
    get_tool_calls, clear_tool_calls,
)
from backend.agents.tool_interceptor import _find_tool
from backend.routes.axis import router as axis_router, _log
from backend.auth import decode_token

app = FastAPI(
    title="AXIS API",
    description="Natural language interface for the AXIS operational management platform",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(axis_router)


@app.on_event("startup")
def startup():
    create_tables()
    # Add pending_action column if it doesn't exist yet (zero-downtime migration)
    from sqlalchemy import text
    db = get_session()
    try:
        db.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS pending_action JSON"
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"[Startup] pending_action migration skipped: {e}")
    for col_def in ("tool_calls TEXT", "rag_context TEXT"):
        try:
            db.execute(text(
                f"ALTER TABLE sessions ADD COLUMN IF NOT EXISTS {col_def}"
            ))
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"[Startup] {col_def.split()[0]} migration skipped: {e}")
    db.close()
    logger.info("database tables ready")


# ─── Schemas ─────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None  # If None, a new session is created


class ChatResponse(BaseModel):
    session_id: str
    message: str
    requires_confirmation: bool
    module: str
    timestamp: str


_MODULE_TAG_MAP = {
    "crm": "Sales Intelligence",
    "invoicing": "Finance",
    "data analyst": "Data Analyst",
}


def _response_module(text: str) -> str:
    m = re.match(r'^\[([^\]]+)\]', text.strip())
    if not m:
        return "Orchestrator"
    return _MODULE_TAG_MAP.get(m.group(1).lower(), "Orchestrator")


# ─── Chat endpoint ────────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request):
    """
    Main chat endpoint. Accepts a natural language message and returns the agent's response.
    Maintains conversation history per session.
    """
    # Extract username from JWT if present
    username: Optional[str] = None
    auth_header = http_request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            payload = decode_token(auth_header[7:])
            username = payload.get("username")
        except Exception:
            pass

    db = get_session()
    try:
        # Get or create session
        session_id = request.session_id or str(uuid.uuid4())
        db.expire_all()
        session = db.query(ChatSession).filter(ChatSession.id == session_id).with_for_update().first()

        if not session:
            session = ChatSession(id=session_id, messages=[])
            db.add(session)
            db.commit()
            db.expire_all()
            session = db.query(ChatSession).filter(ChatSession.id == session_id).first()

        # Force fresh load from DB
        db.refresh(session)
        history = list(session.messages or [])

        # Pending-action fast path: if a write tool preview is stored from the
        # last turn, and the user confirms, execute it directly without LLM.
        from sqlalchemy.orm.attributes import flag_modified
        pending = session.pending_action
        # TTL check — expire pending actions older than 5 minutes
        if pending and isinstance(pending, dict) and pending.get("stored_at"):
            try:
                age = datetime.utcnow() - datetime.fromisoformat(pending["stored_at"])
                if age.total_seconds() > 300:
                    session.pending_action = None
                    flag_modified(session, "pending_action")
                    db.commit()
                    pending = None
            except (ValueError, TypeError):
                pass  # malformed stored_at — leave pending intact
        response_text = None
        if pending and isinstance(pending, dict):
            tool_name = pending.get("tool")
            tool_params = dict(pending.get("params") or {})

            if _is_negative_confirmation(request.message):
                # User cancelled — clear pending action and acknowledge
                session.pending_action = None
                response_text = "[AXIS]\nOperation cancelled."

            elif _is_positive_confirmation(request.message):
                # Deterministic execution — bypass LLM entirely
                from backend.tools.crm_tools import ALL_CRM_TOOLS
                from backend.tools.invoice_tools import ALL_INVOICE_TOOLS
                from backend.tools.chart_tools import ALL_CHART_TOOLS
                all_tools = ALL_CRM_TOOLS + ALL_INVOICE_TOOLS + ALL_CHART_TOOLS
                tool = _find_tool(tool_name, all_tools)
                if tool:
                    tool_params["confirmed"] = True
                    try:
                        tool_result = str(tool.invoke(tool_params))
                        response_text = f"[AXIS]\n{tool_result}"
                    except Exception as te:
                        logger.error(f"[Main] Pending action tool '{tool_name}' failed: {te}", exc_info=True)
                        response_text = f"[Error]\nTool '{tool_name}' failed: {te}"
                    session.pending_action = None

        captured_tool_calls: list = []
        captured_rag_context: str = ""
        if response_text is None:
            clear_pending_action()
            clear_tool_calls()
            clear_rag_context()
            response_text = run_agent(request.message, history)
            # Capture any new pending action set during this agent run
            new_pending = get_pending_action()
            if new_pending:
                new_pending["stored_at"] = datetime.utcnow().isoformat()
                session.pending_action = new_pending
                flag_modified(session, "pending_action")
            else:
                session.pending_action = None
            captured_tool_calls = get_tool_calls()
            captured_rag_context = get_rag_context()

        # Log the agent interaction with username
        _log("agent", "chat", request.message[:200], username=username)

        # Update session history — embed tool_calls/rag_context in assistant message
        history.append({"role": "human", "content": request.message})
        history.append({
            "role": "assistant",
            "content": response_text,
            "tool_calls": json.dumps(captured_tool_calls),
            "rag_context": captured_rag_context,
        })

        # Also store last-exchange data as session columns for quick lookup
        session.tool_calls = json.dumps(captured_tool_calls)
        session.rag_context = captured_rag_context

        # Keep last 20 messages to avoid token overflow
        if len(history) > 20:
            history = history[-20:]

        session.messages = history
        flag_modified(session, "messages")
        session.updated_at = datetime.utcnow()
        db.commit()

        return ChatResponse(
            session_id=session_id,
            message=response_text,
            requires_confirmation=any(
                p in response_text for p in _WRITE_PREVIEW_PATTERNS
            ),
            module=_response_module(response_text),
            timestamp=datetime.utcnow().isoformat()
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.get("/session/{session_id}/history")
async def get_history(session_id: str):
    """Get full conversation history for a session."""
    db = get_session()
    try:
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"session_id": session_id, "messages": session.messages}
    finally:
        db.close()


@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """Clear conversation history for a session."""
    db = get_session()
    try:
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session:
            session.messages = []
            db.commit()
        return {"message": "Session cleared"}
    finally:
        db.close()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "AXIS"}
