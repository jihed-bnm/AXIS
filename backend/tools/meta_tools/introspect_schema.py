"""
Schema introspection tool for the meta-agent architect.

Returns the full public-schema structure of the PostgreSQL database as a
JSON string.  The meta-agent feeds this context to the LLM when generating
new tool templates, so the LLM knows real table names, column types, and
join paths without hallucinating them.

Return shape (as a JSON-encoded string):
{
  "tables": {
    "<table_name>": {
      "columns": [
        {
          "name":        str,
          "type":        str,   # postgres data type, e.g. "integer", "varchar", "text"
          "nullable":    bool,
          "primary_key": bool,
          "default":     str | null
        },
        ...
      ],
      "foreign_keys": [
        {
          "column":     str,   # column in this table
          "references": str    # "<foreign_table>.<foreign_column>"
        },
        ...
      ]
    },
    ...
  },
  "table_count": int
}

On any error the returned JSON has the shape:
  {"error": "<message>", "tables": {}, "table_count": 0}
"""
from __future__ import annotations

import json
from langchain_core.tools import tool
from sqlalchemy import text

from backend.models.database import get_session

# Tables that are never useful to the meta-agent.
_EXCLUDED_TABLES = frozenset({
    "alembic_version",
})

# Prefixes that indicate system/internal tables.
_EXCLUDED_PREFIXES = ("pg_", "sql_")


def _is_excluded(table_name: str) -> bool:
    return (
        table_name in _EXCLUDED_TABLES
        or any(table_name.startswith(p) for p in _EXCLUDED_PREFIXES)
    )


# ── Queries ───────────────────────────────────────────────────────────────────

_Q_TABLES = text("""
    SELECT table_name
    FROM   information_schema.tables
    WHERE  table_schema = 'public'
      AND  table_type   = 'BASE TABLE'
    ORDER  BY table_name
""")

_Q_COLUMNS = text("""
    SELECT
        table_name,
        column_name,
        data_type,
        is_nullable,
        column_default
    FROM   information_schema.columns
    WHERE  table_schema = 'public'
    ORDER  BY table_name, ordinal_position
""")

_Q_PRIMARY_KEYS = text("""
    SELECT
        tc.table_name,
        kcu.column_name
    FROM   information_schema.table_constraints  tc
    JOIN   information_schema.key_column_usage   kcu
           ON  kcu.constraint_name = tc.constraint_name
           AND kcu.table_schema    = tc.table_schema
    WHERE  tc.constraint_type = 'PRIMARY KEY'
      AND  tc.table_schema    = 'public'
""")

_Q_FOREIGN_KEYS = text("""
    SELECT
        tc.table_name          AS src_table,
        kcu.column_name        AS src_column,
        ccu.table_name         AS ref_table,
        ccu.column_name        AS ref_column
    FROM   information_schema.table_constraints         tc
    JOIN   information_schema.key_column_usage          kcu
           ON  kcu.constraint_name = tc.constraint_name
           AND kcu.table_schema    = tc.table_schema
    JOIN   information_schema.constraint_column_usage   ccu
           ON  ccu.constraint_name = tc.constraint_name
           AND ccu.table_schema    = tc.table_schema
    WHERE  tc.constraint_type = 'FOREIGN KEY'
      AND  tc.table_schema    = 'public'
    ORDER  BY tc.table_name, kcu.column_name
""")


# ── Tool ──────────────────────────────────────────────────────────────────────

@tool
def introspect_schema() -> str:
    """Read the live PostgreSQL schema and return it as a JSON string.

    Queries information_schema (no application tables are written to).
    Returns table names, column names/types/nullability, primary keys, and
    foreign-key relationships for every table in the public schema.

    Use this tool first whenever you need to generate SQL or define new tools —
    it gives you the ground truth schema so you never hallucinate table or
    column names.

    Returns a JSON string.  Parse it with json.loads() to work with the data.
    System tables (pg_*, alembic_version) are excluded from the output.
    """
    db = get_session()
    try:
        # ── 1. All public tables ──────────────────────────────────────────────
        raw_tables = db.execute(_Q_TABLES).fetchall()
        table_names = [
            row[0] for row in raw_tables if not _is_excluded(row[0])
        ]

        if not table_names:
            return json.dumps({"tables": {}, "table_count": 0,
                               "warning": "No tables found in public schema."})

        table_set = set(table_names)

        # ── 2. Columns (all tables in one query) ──────────────────────────────
        columns_by_table: dict[str, list[dict]] = {t: [] for t in table_names}
        for row in db.execute(_Q_COLUMNS).fetchall():
            tbl, col, dtype, nullable, default = row
            if tbl not in table_set:
                continue
            columns_by_table[tbl].append({
                "name":        col,
                "type":        dtype,
                "nullable":    nullable == "YES",
                "primary_key": False,   # filled in step 3
                "default":     default,
            })

        # ── 3. Primary keys ───────────────────────────────────────────────────
        pk_set: set[tuple[str, str]] = set()
        for row in db.execute(_Q_PRIMARY_KEYS).fetchall():
            tbl, col = row
            if tbl in table_set:
                pk_set.add((tbl, col))

        for tbl, cols in columns_by_table.items():
            for col_info in cols:
                if (tbl, col_info["name"]) in pk_set:
                    col_info["primary_key"] = True

        # ── 4. Foreign keys ───────────────────────────────────────────────────
        fk_by_table: dict[str, list[dict]] = {t: [] for t in table_names}
        for row in db.execute(_Q_FOREIGN_KEYS).fetchall():
            src_table, src_col, ref_table, ref_col = row
            if src_table not in table_set:
                continue
            fk_by_table[src_table].append({
                "column":     src_col,
                "references": f"{ref_table}.{ref_col}",
            })

        # ── 5. Assemble result ────────────────────────────────────────────────
        schema: dict = {"tables": {}, "table_count": len(table_names)}
        for tbl in table_names:
            schema["tables"][tbl] = {
                "columns":      columns_by_table[tbl],
                "foreign_keys": fk_by_table[tbl],
            }

        return json.dumps(schema, default=str)

    except Exception as exc:
        return json.dumps({
            "error":       str(exc),
            "tables":      {},
            "table_count": 0,
        })
    finally:
        db.close()
