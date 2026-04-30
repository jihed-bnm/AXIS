"""Chart Generation Tools — AXIS dashboard chart creation from warehouse data."""
from langchain.tools import tool
from sqlalchemy import text
from typing import Optional
import json
import re

from backend.models.database import engine


VALID_CHART_TYPES = {'bar', 'line', 'scatter', 'pie', 'donut', 'funnel', 'area'}
VALID_DATA_SOURCES = {'fact_deals', 'fact_revenue', 'fact_activities', 'dim_client'}
VALID_AGGREGATIONS = {'sum', 'count', 'avg', 'max', 'min'}
VALID_TRUNCATIONS = {'month', 'year', 'week', 'quarter', 'day'}

# Maps x_truncation period → PostgreSQL TO_CHAR format string
_TRUNCATION_FORMAT: dict = {
    'month':   "YYYY-MM",
    'year':    "YYYY",
    'week':    "IYYY-IW",
    'quarter': 'YYYY-"Q"Q',
    'day':     "YYYY-MM-DD",
}

PLOTLY_BASE_LAYOUT = {
    'paper_bgcolor': 'transparent',
    'plot_bgcolor': 'transparent',
    'font': {'color': '#F0F0F0', 'family': 'Inter, sans-serif', 'size': 11},
    'margin': {'l': 60, 'r': 30, 't': 40, 'b': 60},
    'xaxis': {'gridcolor': '#1E1E1E', 'linecolor': '#1E1E1E'},
    'yaxis': {'gridcolor': '#1E1E1E', 'linecolor': '#1E1E1E'},
}

PALETTE = ['#6C63FF', '#3ECF8E', '#00D4FF', '#FF4D4D', '#FF9F43', '#A29BFE', '#55EFC4', '#FD79A8']

_SAFE_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _safe(name: str) -> bool:
    return bool(_SAFE_IDENT.match(name))


@tool
def generate_chart(
    chart_type: str,
    x_column: str,
    y_column: str,
    data_source: str,
    title: str,
    filter_column: Optional[str] = None,
    filter_value: Optional[str] = None,
    aggregation: str = 'sum',
    limit: int = 20,
    session_id: str = 'default',
    x_truncation: Optional[str] = None,
) -> str:
    """Generate a Plotly chart from warehouse data and save it to axis_charts table.
    Returns the chart_id and confirmation message.
    chart_type: bar, line, scatter, pie, donut, funnel, area
    data_source: fact_deals, fact_revenue, fact_activities, dim_client
    y_column: column name or 'count'
    aggregation: sum, count, avg, max, min
    x_truncation (optional): truncate a date x_column before grouping.
      Values: month, year, quarter, week, day.
      Example: x_column='invoice_date', x_truncation='month' groups revenue by calendar month.
      Produces clean x-axis labels (e.g. '2024-01', '2024-Q2'). Rows sort chronologically ASC.
    """
    if chart_type not in VALID_CHART_TYPES:
        return f"Invalid chart_type '{chart_type}'. Choose from: {', '.join(sorted(VALID_CHART_TYPES))}"
    if data_source not in VALID_DATA_SOURCES:
        return f"Invalid data_source '{data_source}'. Choose from: {', '.join(sorted(VALID_DATA_SOURCES))}"
    if aggregation not in VALID_AGGREGATIONS:
        return f"Invalid aggregation '{aggregation}'. Choose from: {', '.join(VALID_AGGREGATIONS)}"
    if not _safe(x_column):
        return f"Invalid x_column name: '{x_column}'. Only alphanumeric and underscores allowed."
    if y_column != 'count' and not _safe(y_column):
        return f"Invalid y_column name: '{y_column}'. Use a valid column name or 'count'."
    if filter_column and not _safe(filter_column):
        return f"Invalid filter_column name: '{filter_column}'."
    if x_truncation and x_truncation not in VALID_TRUNCATIONS:
        return f"Invalid x_truncation '{x_truncation}'. Choose from: {', '.join(sorted(VALID_TRUNCATIONS))}"

    params: dict = {}

    if x_truncation:
        # Time-series path: DATE_TRUNC for grouping (ensures chronological ORDER BY),
        # TO_CHAR for readable x-axis labels.
        fmt = _TRUNCATION_FORMAT[x_truncation]
        trunc_expr  = f"DATE_TRUNC('{x_truncation}', \"{x_column}\")"
        label_expr  = f"TO_CHAR({trunc_expr}, '{fmt}')"
        if y_column == 'count':
            select_part = f'{label_expr}, COUNT(*) AS value'
        else:
            select_part = f'{label_expr}, {aggregation.upper()}("{y_column}") AS value'
        sql = f'SELECT {select_part} FROM warehouse.{data_source}'
        if filter_column and filter_value is not None:
            sql += f' WHERE "{filter_column}" = :filter_value'
            params['filter_value'] = filter_value
        # GROUP BY both: truncated date (for sort key) and formatted label (for SELECT)
        sql += (
            f' GROUP BY {trunc_expr}, {label_expr}'
            f' ORDER BY {trunc_expr} ASC'
            f' LIMIT {int(min(limit, 100))}'
        )
    else:
        # Standard path: group by x_column verbatim, order by value descending
        if y_column == 'count':
            select_part = f'"{x_column}", COUNT(*) AS value'
        else:
            select_part = f'"{x_column}", {aggregation.upper()}("{y_column}") AS value'
        sql = f'SELECT {select_part} FROM warehouse.{data_source}'
        if filter_column and filter_value is not None:
            sql += f' WHERE "{filter_column}" = :filter_value'
            params['filter_value'] = filter_value
        sql += f' GROUP BY "{x_column}" ORDER BY value DESC LIMIT {int(min(limit, 100))}'

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            rows = result.fetchall()
    except Exception as e:
        return f"Error querying data: {str(e)}"

    if not rows:
        return "No data returned for this query. Try different filters or columns."

    x_values = [str(r[0]) if r[0] is not None else 'N/A' for r in rows]
    y_values = [float(r[1]) if r[1] is not None else 0.0 for r in rows]

    # Build Plotly trace
    if chart_type == 'bar':
        trace = {
            'type': 'bar', 'x': x_values, 'y': y_values, 'name': title,
            'marker': {'color': '#6C63FF'},
        }
    elif chart_type == 'line':
        trace = {
            'type': 'scatter', 'mode': 'lines', 'x': x_values, 'y': y_values,
            'name': title, 'line': {'color': '#6C63FF', 'width': 2.5},
        }
    elif chart_type == 'area':
        trace = {
            'type': 'scatter', 'mode': 'lines', 'x': x_values, 'y': y_values,
            'name': title, 'line': {'color': '#6C63FF', 'width': 2.5},
            'fill': 'tozeroy', 'fillcolor': 'rgba(108,99,255,0.1)',
        }
    elif chart_type == 'scatter':
        trace = {
            'type': 'scatter', 'mode': 'markers', 'x': x_values, 'y': y_values,
            'name': title, 'marker': {'color': '#6C63FF'},
        }
    elif chart_type in ('pie', 'donut'):
        trace = {
            'type': 'pie',
            'labels': x_values, 'values': y_values,
            'hole': 0.38 if chart_type == 'donut' else 0,
            'name': title, 'marker': {'colors': PALETTE},
            'textinfo': 'percent+label',
            'textfont': {'color': '#F0F0F0'},
        }
    elif chart_type == 'funnel':
        trace = {
            'type': 'funnel', 'y': x_values, 'x': y_values, 'name': title,
            'marker': {'color': '#6C63FF'},
            'connector': {'line': {'color': '#1E1E1E', 'width': 1}},
        }
    else:
        trace = {
            'type': 'bar', 'x': x_values, 'y': y_values, 'name': title,
            'marker': {'color': '#6C63FF'},
        }

    layout = dict(PLOTLY_BASE_LAYOUT)
    if chart_type in ('pie', 'donut'):
        layout['margin'] = {'l': 16, 'r': 16, 't': 40, 'b': 16}
        layout['legend'] = {'bgcolor': 'transparent', 'orientation': 'h', 'y': -0.1}

    config_json = json.dumps({'data': [trace], 'layout': layout})

    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO public.axis_charts
                        (title, chart_type, config, query_used, session_id)
                    VALUES
                        (:title, :chart_type, :config, :query_used, :session_id)
                    RETURNING chart_id
                """),
                {
                    'title': title,
                    'chart_type': chart_type,
                    'config': config_json,
                    'query_used': sql,
                    'session_id': session_id,
                },
            )
            chart_id = result.fetchone()[0]
            conn.commit()
    except Exception as e:
        return f"Error saving chart: {str(e)}"

    return (
        f"Chart '{title}' created successfully. Chart ID: {chart_id}. "
        f"It is now available in the My Charts tab."
    )


@tool
def list_saved_charts(session_id: Optional[str] = None) -> str:
    """List all saved charts with their IDs and titles."""
    try:
        with engine.connect() as conn:
            if session_id:
                result = conn.execute(
                    text("""
                        SELECT chart_id, title, chart_type, created_at
                        FROM public.axis_charts
                        WHERE session_id = :sid
                        ORDER BY created_at DESC
                    """),
                    {'sid': session_id},
                )
            else:
                result = conn.execute(
                    text("""
                        SELECT chart_id, title, chart_type, created_at
                        FROM public.axis_charts
                        ORDER BY created_at DESC
                    """)
                )
            rows = result.fetchall()

        if not rows:
            return "No saved charts found. Ask me to create one!"

        lines = [f"Saved Charts ({len(rows)} total):"]
        for r in rows:
            created = str(r[3])[:16] if r[3] else 'N/A'
            lines.append(f"  [ID: {r[0]}] {r[1]} | Type: {r[2]} | Created: {created}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing charts: {str(e)}"


@tool
def delete_chart(chart_id: int, confirmed: bool = False) -> str:
    """Delete a saved chart by ID.
    Call with confirmed=False first for preview, then confirmed=True to apply."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT chart_id, title, chart_type FROM public.axis_charts WHERE chart_id = :cid"),
                {'cid': chart_id},
            ).fetchone()

        if not row:
            return f"Chart ID {chart_id} not found."

        if not confirmed:
            return (
                f"WARNING: About to DELETE chart:\n"
                f"  ID: {row[0]}\n"
                f"  Title: {row[1]}\n"
                f"  Type: {row[2]}\n\n"
                f"Call again with confirmed=True to delete."
            )

        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM public.axis_charts WHERE chart_id = :cid"),
                {'cid': chart_id},
            )
            conn.commit()

        return f"OK: Chart '{row[1]}' (ID: {chart_id}) deleted successfully."
    except Exception as e:
        return f"Error deleting chart: {str(e)}"


ALL_CHART_TOOLS = [
    generate_chart,
    list_saved_charts,
    delete_chart,
]
