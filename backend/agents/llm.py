"""
Central LLM factory — single source of truth for the model used across all agents.

All agent code must import get_llm() from here. Do not construct ChatOllama directly.
To swap the model project-wide, change ERP_MODEL below.
"""
from langchain_ollama import ChatOllama

ERP_MODEL = "qwen2.5:7b"


def get_llm(temperature: float = 0) -> ChatOllama:
    return ChatOllama(model=ERP_MODEL, temperature=temperature)
