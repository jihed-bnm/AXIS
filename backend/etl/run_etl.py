"""
Standalone ETL runner — no Airflow required.

Imports all pipeline functions from airflow/dags/etl_jbm_pipeline.py by
mocking the Airflow modules so the DAG file can be loaded without an
Airflow installation.

Run as:
    python -m backend.etl.run_etl
"""

from __future__ import annotations

import logging
import os
import sys
import time
import types
from pathlib import Path

# ── Resolve project paths ─────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
STAGING_DIR = DATA_DIR / "staging"
STAGING_DIR.mkdir(parents=True, exist_ok=True)

# ── Load .env before the DAG module is imported so DATABASE_URL etc. are set ─

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass  # rely on env vars being set externally

# ── Mock Airflow so etl_jbm_pipeline.py can be imported without Airflow ───────

class _Operator:
    """Minimal stand-in for Airflow operator objects."""

    def __init__(self, *args, **kwargs):
        pass

    def __rshift__(self, other):
        # operator >> other  (left side of >>)
        return other

    def __rrshift__(self, other):
        # list >> operator  (right side of >> when left has no __rshift__)
        return self

    def __lshift__(self, other):
        return other

    def __rlshift__(self, other):
        return self


class _DAG:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _make_airflow_mocks():
    stubs = {
        "airflow": {"DAG": _DAG},
        "airflow.operators": {},
        "airflow.operators.python": {"PythonOperator": _Operator},
        "airflow.operators.empty": {"EmptyOperator": _Operator},
    }
    for mod_name, attrs in stubs.items():
        mod = sys.modules.get(mod_name) or types.ModuleType(mod_name)
        for attr, val in attrs.items():
            setattr(mod, attr, val)
        sys.modules[mod_name] = mod


_make_airflow_mocks()

# ── Import the DAG module ─────────────────────────────────────────────────────

_DAG_DIR = PROJECT_ROOT / "airflow" / "dags"
sys.path.insert(0, str(_DAG_DIR))

import etl_jbm_pipeline as _etl  # noqa: E402  (must come after mocks)

# Override the Airflow-container paths with local paths
_etl.DATA_DIR = DATA_DIR
_etl.STAGING_DIR = STAGING_DIR

# If DATABASE_URL was set from .env, patch the module-level variable too
# (the module reads it once at import time; _engine() uses the module var)
_db_url = os.getenv("DATABASE_URL")
if _db_url:
    _etl.DATABASE_URL = _db_url

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Runner helpers ────────────────────────────────────────────────────────────

def _step(label: str, fn) -> float:
    """Run one pipeline step, print timing, return elapsed seconds."""
    print(f"\n{'─' * 62}")
    print(f"  {label}")
    print(f"{'─' * 62}")
    t0 = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - t0
    print(f"  ✔  Completed in {elapsed:.1f}s")
    return elapsed


# ── Main pipeline ─────────────────────────────────────────────────────────────

def main():
    print("=" * 62)
    print("  JBM Consulting — ETL Standalone Runner")
    print("=" * 62)
    print(f"  Data dir    : {DATA_DIR}")
    print(f"  Staging dir : {STAGING_DIR}")
    print(f"  Database    : {_etl.DATABASE_URL}")

    # Steps run in dependency order matching the Airflow DAG:
    #   extract → transform → load for each domain (parallel in Airflow,
    #   sequential here), then dim_date, then validate.
    pipeline: list[tuple[str, object]] = [
        (" 1/14  Extract  raw_clients.xlsx",      _etl.extract_clients),
        (" 2/14  Transform clients",              _etl.transform_clients),
        (" 3/14  Load     → warehouse.dim_client",_etl.load_clients),
        (" 4/14  Extract  raw_deals.xlsx",         _etl.extract_deals),
        (" 5/14  Transform deals",                _etl.transform_deals),
        (" 6/14  Load     → warehouse.fact_deals", _etl.load_deals),
        (" 7/14  Extract  raw_activities.xlsx",    _etl.extract_activities),
        (" 8/14  Transform activities (chunked)",  _etl.transform_activities),
        (" 9/14  Load     → warehouse.fact_activities", _etl.load_activities),
        ("10/14  Extract  raw_invoices.xlsx",      _etl.extract_invoices),
        ("11/14  Transform invoices",              _etl.transform_invoices),
        ("12/14  Load     → warehouse.fact_revenue", _etl.load_invoices),
        ("13/14  Populate warehouse.dim_date",     _etl.populate_dim_date),
        ("14/14  Validate warehouse",              _etl.validate_warehouse),
    ]

    t_total = time.perf_counter()
    timings: list[tuple[str, float]] = []

    for label, fn in pipeline:
        elapsed = _step(label, fn)
        timings.append((label.strip(), elapsed))

    total_elapsed = time.perf_counter() - t_total

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 62}")
    print("  TIMING SUMMARY")
    print(f"{'=' * 62}")
    for label, elapsed in timings:
        bar_len = int(elapsed / total_elapsed * 30)
        bar = "█" * bar_len
        print(f"  {elapsed:6.1f}s  {bar:<30}  {label}")
    print(f"{'─' * 62}")
    print(f"  {'TOTAL':>6}   {total_elapsed:.1f}s")
    print(f"{'=' * 62}")
    print("  Pipeline finished successfully.")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    main()
