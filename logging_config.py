"""Centralized logging configuration for AXIS backend."""
import logging
import logging.handlers
import os

try:
    import colorlog
    _HAS_COLORLOG = True
except ImportError:
    _HAS_COLORLOG = False

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """
    Configure root logger with a colored console handler (INFO+) and a rotating
    file handler at logs/axis.log (DEBUG+, 10 MB, 5 backups).

    Idempotent — safe to call multiple times; exits early if handlers already exist.
    Does not replace uvicorn's own logger — it sets propagate=False on uvicorn
    loggers so their records are handled exclusively by uvicorn's own handlers.
    """
    root = logging.getLogger()
    if root.handlers:
        return  # Already configured — avoid duplicate handlers

    root.setLevel(logging.DEBUG)

    # ── Console handler (INFO+) ───────────────────────────────────────────────
    if _HAS_COLORLOG:
        console_fmt = colorlog.ColoredFormatter(
            "%(log_color)s" + _LOG_FORMAT,
            datefmt=_DATE_FORMAT,
            log_colors={
                "DEBUG":    "cyan",
                "INFO":     "green",
                "WARNING":  "yellow",
                "ERROR":    "red",
                "CRITICAL": "bold_red",
            },
        )
        console_handler = colorlog.StreamHandler()
        console_handler.setFormatter(console_fmt)
    else:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    console_handler.setLevel(logging.INFO)
    root.addHandler(console_handler)

    # ── Rotating file handler (DEBUG+) ────────────────────────────────────────
    os.makedirs("logs", exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        "logs/axis.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    # Prevent uvicorn log records from propagating to our root handlers;
    # uvicorn manages its own console output via its own handlers.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).propagate = False


def log_tool_call(
    logger: logging.Logger,
    tool_name: str,
    input_args,
    output: str,
    elapsed_ms: float,
) -> None:
    """Log a single tool invocation at INFO level with truncated args and output."""
    args_str = str(input_args)[:200]
    out_str = str(output)[:200]
    logger.info(f"[Tool] {tool_name} | args={args_str} | out={out_str!r} | {elapsed_ms:.1f}ms")
