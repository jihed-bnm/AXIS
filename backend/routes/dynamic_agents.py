"""REST endpoints for managing dynamic (LLM-generated) agents — DISABLED."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

# All route handlers disabled — dynamic agents feature removed.
# Two decorators share a single handler so every sub-path returns 503.

@router.api_route("/dynamic-agents", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@router.api_route("/dynamic-agents/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def _dynamic_agents_disabled(rest: str = "") -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Dynamic agents are disabled"})


# ── Original implementation (commented out) ───────────────────────────────────
#
# from datetime import datetime
# from typing import Optional
#
# from fastapi import Depends, HTTPException, Query
#
# from backend.auth import get_current_user, require_admin
# from backend.models.database import get_session
# from backend.models.dynamic_agent_models import DynamicAgent
#
#
# def _iso(dt: Optional[datetime]) -> Optional[str]:
#     return dt.isoformat() if dt else None
#
#
# def _agent_summary(agent: DynamicAgent) -> dict:
#     test_results = agent.test_results or {}
#     return {
#         "id":          agent.id,
#         "name":        agent.name,
#         "description": agent.description,
#         "status":      agent.status,
#         "created_at":  _iso(agent.created_at),
#         "tool_count":  len(agent.tools),
#         "all_valid":   bool(test_results.get("all_tools_passed", False)),
#     }
#
#
# def _agent_detail(agent: DynamicAgent) -> dict:
#     test_results = agent.test_results or {}
#     tools = [
#         {
#             "id":                    t.id,
#             "tool_name":             t.tool_name,
#             "description":           t.description,
#             "code_template":         t.code_template,
#             "parameters_schema":     t.parameters_schema,
#             "ast_validation_passed": t.ast_validation_passed,
#             "sandbox_test_passed":   t.sandbox_test_passed,
#             "test_log":              t.test_log,
#             "created_at":            _iso(t.created_at),
#         }
#         for t in agent.tools
#     ]
#     return {
#         "id":            agent.id,
#         "name":          agent.name,
#         "description":   agent.description,
#         "system_prompt": agent.system_prompt,
#         "keyword_rules": agent.keyword_rules,
#         "status":        agent.status,
#         "created_at":    _iso(agent.created_at),
#         "created_by":    agent.created_by,
#         "activated_at":  _iso(agent.activated_at),
#         "activated_by":  agent.activated_by,
#         "test_results":  test_results,
#         "all_valid":     bool(test_results.get("all_tools_passed", False)),
#         "tools":         tools,
#     }
#
#
# @router.get("/dynamic-agents")
# def list_dynamic_agents(
#     status: Optional[str] = Query(default=None),
#     user: dict = Depends(get_current_user),
# ):
#     db = get_session()
#     try:
#         q = db.query(DynamicAgent)
#         if status:
#             q = q.filter(DynamicAgent.status == status)
#         agents = q.order_by(DynamicAgent.created_at.desc()).all()
#         return {"agents": [_agent_summary(a) for a in agents]}
#     finally:
#         db.close()
#
#
# @router.get("/dynamic-agents/{agent_id}")
# def get_dynamic_agent(agent_id: int, user: dict = Depends(get_current_user)):
#     db = get_session()
#     try:
#         agent = db.query(DynamicAgent).filter(DynamicAgent.id == agent_id).first()
#         if not agent:
#             raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
#         return _agent_detail(agent)
#     finally:
#         db.close()
#
#
# @router.post("/dynamic-agents/{agent_id}/activate")
# def activate_dynamic_agent(agent_id: int, admin: dict = Depends(require_admin)):
#     db = get_session()
#     try:
#         agent = db.query(DynamicAgent).filter(DynamicAgent.id == agent_id).first()
#         if not agent:
#             raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
#         if agent.status == "active":
#             raise HTTPException(status_code=400, detail="Agent is already active.")
#         test_results = agent.test_results or {}
#         if not test_results.get("all_tools_passed", False):
#             raise HTTPException(
#                 status_code=400,
#                 detail=(
#                     "Cannot activate: not all tools passed validation. "
#                     "Review test_results before activating."
#                 ),
#             )
#         agent.status = "active"
#         agent.activated_at = datetime.utcnow()
#         agent.activated_by = None
#         db.commit()
#         db.refresh(agent)
#         from backend.agents.dynamic_loader import reload_dynamic_agents
#         reload_dynamic_agents()
#         return {
#             "status": "success",
#             "agent": {
#                 "id":           agent.id,
#                 "name":         agent.name,
#                 "status":       agent.status,
#                 "activated_at": _iso(agent.activated_at),
#                 "activated_by": agent.activated_by,
#             },
#         }
#     except HTTPException:
#         raise
#     except Exception as exc:
#         db.rollback()
#         raise HTTPException(status_code=500, detail=str(exc))
#     finally:
#         db.close()
#
#
# @router.post("/dynamic-agents/{agent_id}/disable")
# def disable_dynamic_agent(agent_id: int, admin: dict = Depends(require_admin)):
#     db = get_session()
#     try:
#         agent = db.query(DynamicAgent).filter(DynamicAgent.id == agent_id).first()
#         if not agent:
#             raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
#         if agent.status == "disabled":
#             raise HTTPException(status_code=400, detail="Agent is already disabled.")
#         agent.status = "disabled"
#         db.commit()
#         db.refresh(agent)
#         from backend.agents.dynamic_loader import reload_dynamic_agents
#         reload_dynamic_agents()
#         return {
#             "status": "success",
#             "agent": {
#                 "id":     agent.id,
#                 "name":   agent.name,
#                 "status": agent.status,
#             },
#         }
#     except HTTPException:
#         raise
#     except Exception as exc:
#         db.rollback()
#         raise HTTPException(status_code=500, detail=str(exc))
#     finally:
#         db.close()
