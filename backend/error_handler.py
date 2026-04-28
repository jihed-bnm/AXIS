"""
Centralized Error Handling System
Standardized error types, responses, and retry logic for the ERP agent system.
"""
import functools
import time
import logging
from enum import Enum
from typing import Optional, Callable, Any
from datetime import datetime

logger = logging.getLogger("erp_agent")


# ── Error Types ───────────────────────────────────────────────────────────────
class ERPErrorType(Enum):
    # Tool errors
    TOOL_PARAM_INVALID      = "TOOL_PARAM_INVALID"       # wrong/missing parameters
    TOOL_EXECUTION_FAILED   = "TOOL_EXECUTION_FAILED"    # tool crashed
    TOOL_NOT_FOUND          = "TOOL_NOT_FOUND"           # agent couldn't find tool

    # Database errors
    DB_CONNECTION_FAILED    = "DB_CONNECTION_FAILED"     # can't connect to PostgreSQL
    DB_RECORD_NOT_FOUND     = "DB_RECORD_NOT_FOUND"      # queried record doesn't exist
    DB_CONSTRAINT_VIOLATED  = "DB_CONSTRAINT_VIOLATED"   # unique/FK constraint
    DB_TRANSACTION_FAILED   = "DB_TRANSACTION_FAILED"    # commit failed

    # Agent errors
    AGENT_TIMEOUT           = "AGENT_TIMEOUT"            # max iterations hit
    AGENT_ROUTING_FAILED    = "AGENT_ROUTING_FAILED"     # supervisor couldn't route
    AGENT_LLM_ERROR         = "AGENT_LLM_ERROR"          # LLM API error

    # Input errors
    INPUT_EMPTY             = "INPUT_EMPTY"              # empty user message
    INPUT_TOO_LONG          = "INPUT_TOO_LONG"           # message too long

    # General
    UNKNOWN                 = "UNKNOWN"


# ── Standardized Error Response ───────────────────────────────────────────────
class ERPError(Exception):
    def __init__(
        self,
        error_type: ERPErrorType,
        message: str,
        user_message: str,
        context: Optional[dict] = None,
        recoverable: bool = True
    ):
        self.error_type = error_type
        self.message = message                  # technical message for logs
        self.user_message = user_message        # friendly message for user
        self.context = context or {}
        self.recoverable = recoverable
        self.timestamp = datetime.utcnow().isoformat()
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error_type": self.error_type.value,
            "message": self.message,
            "user_message": self.user_message,
            "context": self.context,
            "recoverable": self.recoverable,
            "timestamp": self.timestamp
        }

    def __str__(self):
        return f"[{self.error_type.value}] {self.user_message}"


# ── User-Friendly Error Messages ──────────────────────────────────────────────
USER_MESSAGES = {
    ERPErrorType.DB_CONNECTION_FAILED:   "Database is temporarily unavailable. Please try again in a moment.",
    ERPErrorType.DB_RECORD_NOT_FOUND:    "The requested record was not found. Please check the name or ID and try again.",
    ERPErrorType.DB_CONSTRAINT_VIOLATED: "This operation violates a business rule (e.g. duplicate entry or missing required link).",
    ERPErrorType.DB_TRANSACTION_FAILED:  "The database operation failed. No changes were saved.",
    ERPErrorType.TOOL_PARAM_INVALID:     "I could not understand the parameters for this operation. Please rephrase your request.",
    ERPErrorType.TOOL_EXECUTION_FAILED:  "The operation failed during execution. Please try again.",
    ERPErrorType.AGENT_TIMEOUT:          "I could not complete this request in time. Please try a simpler or more specific query.",
    ERPErrorType.AGENT_ROUTING_FAILED:   "I could not determine which module handles your request. Please be more specific.",
    ERPErrorType.AGENT_LLM_ERROR:        "The AI service is temporarily unavailable. Please try again in a moment.",
    ERPErrorType.INPUT_EMPTY:            "Please enter a message.",
    ERPErrorType.INPUT_TOO_LONG:         "Your message is too long. Please shorten it and try again.",
    ERPErrorType.UNKNOWN:                "An unexpected error occurred. Please try again.",
}


# ── Retry Decorator ───────────────────────────────────────────────────────────
def with_retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0,
               retry_on: tuple = (Exception,), reraise: bool = True):
    """
    Retry decorator with exponential backoff.
    max_attempts: total attempts including first try
    delay: initial wait in seconds
    backoff: multiplier for each retry
    retry_on: exception types to retry on
    reraise: if True, raise the last exception after all attempts
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            current_delay = delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retry_on as e:
                    last_exception = e
                    if attempt < max_attempts:
                        logger.warning(
                            f"[Retry] {func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                            f"Retrying in {current_delay:.1f}s..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"[Retry] {func.__name__} failed after {max_attempts} attempts: {e}"
                        )
            if reraise and last_exception:
                raise last_exception
        return wrapper
    return decorator


# ── Database Error Handler ────────────────────────────────────────────────────
def handle_db_error(e: Exception, operation: str = "database operation") -> ERPError:
    """Convert raw SQLAlchemy/psycopg2 errors into ERPError."""
    error_str = str(e).lower()

    if "connection" in error_str or "could not connect" in error_str:
        return ERPError(
            ERPErrorType.DB_CONNECTION_FAILED,
            f"DB connection failed during {operation}: {e}",
            USER_MESSAGES[ERPErrorType.DB_CONNECTION_FAILED],
            recoverable=True
        )
    elif "unique" in error_str or "duplicate" in error_str:
        return ERPError(
            ERPErrorType.DB_CONSTRAINT_VIOLATED,
            f"Unique constraint violated during {operation}: {e}",
            USER_MESSAGES[ERPErrorType.DB_CONSTRAINT_VIOLATED],
            recoverable=False
        )
    elif "foreign key" in error_str or "violates" in error_str:
        return ERPError(
            ERPErrorType.DB_CONSTRAINT_VIOLATED,
            f"FK constraint violated during {operation}: {e}",
            USER_MESSAGES[ERPErrorType.DB_CONSTRAINT_VIOLATED],
            recoverable=False
        )
    else:
        return ERPError(
            ERPErrorType.DB_TRANSACTION_FAILED,
            f"DB transaction failed during {operation}: {e}",
            USER_MESSAGES[ERPErrorType.DB_TRANSACTION_FAILED],
            recoverable=True
        )


# ── Tool Error Handler ────────────────────────────────────────────────────────
def handle_tool_error(e: Exception, tool_name: str, params: dict = None) -> str:
    """
    Wrap tool exceptions into clean user-facing strings.
    Returns a string because tools must return strings.
    """
    from sqlalchemy.exc import SQLAlchemyError, OperationalError

    logger.error(f"[Tool Error] {tool_name} failed with params {params}: {e}", exc_info=True)

    if isinstance(e, OperationalError):
        return USER_MESSAGES[ERPErrorType.DB_CONNECTION_FAILED]
    elif isinstance(e, SQLAlchemyError):
        erp_error = handle_db_error(e, tool_name)
        return erp_error.user_message
    elif isinstance(e, (ValueError, TypeError, KeyError, IndexError)):
        return f"Invalid parameters for {tool_name}. Please check your input and try again."
    else:
        return f"{tool_name} encountered an unexpected error. Please try again."


# ── Input Validator ───────────────────────────────────────────────────────────
def validate_user_input(message: str) -> Optional[ERPError]:
    """
    Validate user input before passing to agent.
    Returns ERPError if invalid, None if valid.
    """
    if not message or not message.strip():
        return ERPError(
            ERPErrorType.INPUT_EMPTY,
            "Empty user input received",
            USER_MESSAGES[ERPErrorType.INPUT_EMPTY],
            recoverable=False
        )
    if len(message) > 2000:
        return ERPError(
            ERPErrorType.INPUT_TOO_LONG,
            f"Input too long: {len(message)} chars",
            USER_MESSAGES[ERPErrorType.INPUT_TOO_LONG],
            recoverable=False
        )
    return None


# ── Agent Error Handler ───────────────────────────────────────────────────────
def handle_agent_error(e: Exception, module: str = "unknown") -> str:
    """
    Handle errors from agent execution.
    Returns user-friendly string.
    """
    error_str = str(e).lower()
    logger.error(f"[Agent Error] Module={module}: {e}", exc_info=True)

    if "max iterations" in error_str or "agent stopped" in error_str:
        return USER_MESSAGES[ERPErrorType.AGENT_TIMEOUT]
    elif "rate limit" in error_str or "429" in error_str:
        return "AI service rate limit reached. Please wait a moment and try again."
    elif "api" in error_str or "groq" in error_str or "connection" in error_str:
        return USER_MESSAGES[ERPErrorType.AGENT_LLM_ERROR]
    else:
        return USER_MESSAGES[ERPErrorType.UNKNOWN]
