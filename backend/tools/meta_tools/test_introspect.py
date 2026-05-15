"""
Standalone test for introspect_schema.

Run from the repo root:
    python -m backend.tools.meta_tools.test_introspect

Calls the tool directly (no agent involved) and pretty-prints the result.
"""
import json
import sys
import os

# Ensure repo root is on sys.path when run as __main__
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
))))

from dotenv import load_dotenv
load_dotenv()

from backend.tools.meta_tools.introspect_schema import introspect_schema


def main() -> None:
    print("Calling introspect_schema tool...\n")

    # invoke() is the standard LangChain way to call a @tool directly.
    result_str: str = introspect_schema.invoke({})

    try:
        data = json.loads(result_str)
    except json.JSONDecodeError as exc:
        print(f"ERROR: tool returned non-JSON: {exc}")
        print(result_str)
        sys.exit(1)

    if "error" in data:
        print(f"Tool returned an error: {data['error']}")
        sys.exit(1)

    table_count = data.get("table_count", 0)
    tables = data.get("tables", {})

    print(f"Found {table_count} tables in public schema:\n")

    for table_name, info in tables.items():
        cols = info["columns"]
        fks  = info["foreign_keys"]
        pk_cols = [c["name"] for c in cols if c["primary_key"]]
        print(f"  {table_name}  ({len(cols)} columns, {len(fks)} FK(s), PK: {pk_cols})")

    print("\n--- Full schema (JSON) ---\n")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
