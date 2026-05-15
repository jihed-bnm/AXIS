from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON,
)
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base
from backend.models.crm_models import User  # noqa: F401 — required for SQLAlchemy to resolve 'User' in relationships


class DynamicAgent(Base):
    __tablename__ = "dynamic_agents"

    id           = Column(Integer, primary_key=True, index=True)
    name         = Column(String(100), unique=True, nullable=False, index=True)
    description  = Column(Text, nullable=False)
    system_prompt = Column(Text, nullable=False)
    keyword_rules = Column(JSON, nullable=False, default=list)   # list[str]
    status       = Column(String(20), nullable=False, default="draft")  # draft | active | disabled
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by   = Column(Integer, ForeignKey("users.id"), nullable=True)
    test_results  = Column(JSON, nullable=True)                  # validation outcomes
    activated_at  = Column(DateTime, nullable=True)
    activated_by  = Column(Integer, ForeignKey("users.id"), nullable=True)

    tools = relationship(
        "GeneratedTool",
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    creator   = relationship("User", foreign_keys=[created_by])
    activator = relationship("User", foreign_keys=[activated_by])


class GeneratedTool(Base):
    __tablename__ = "generated_tools"

    id            = Column(Integer, primary_key=True, index=True)
    agent_id      = Column(Integer, ForeignKey("dynamic_agents.id", ondelete="CASCADE"), nullable=False)
    tool_name     = Column(String(100), nullable=False)
    description   = Column(Text, nullable=False)
    code_template = Column(Text, nullable=False)                 # Python function source as string
    parameters_schema      = Column(JSON, nullable=False, default=dict)  # {param: {type, description, required}}
    ast_validation_passed  = Column(Boolean, nullable=False, default=False)
    sandbox_test_passed    = Column(Boolean, nullable=False, default=False)
    test_log      = Column(Text, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)

    agent = relationship("DynamicAgent", back_populates="tools")
