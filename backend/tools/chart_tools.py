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
    'plot_bgcolor':  'transparent',
    'font':    {'color': '#0A1733', 'family': 'Inter, sans-serif', 'size': 11},
    'margin':  {'l': 60, 'r': 30, 't': 40, 'b': 60},
    'xaxis':   {'gridcolor': '#E0E6ED', 'linecolor': '#C2D4E8', 'zerolinecolor': '#E0E6ED'},
    'yaxis':   {'gridcolor': '#E0E6ED', 'linecolor': '#C2D4E8', 'zerolinecolor': '#E0E6ED'},
    'hoverlabel': {'bgcolor': '#FFFFFF', 'bordercolor': '#D8E4F0', 'font': {'color': '#0A1733', 'size': 12, 'family': 'Inter, sans-serif'}},
    'hovermode': 'x unified',
}

PALETTE = ['#6C63FF', '#3ECF8E', '#00D4FF', '#FF4D4D', '#FF9F43', '#A29BFE', '#55EFC4', '#FD79A8']

_SAFE_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_YEAR_RE    = re.compile(r'^(19|20)\d{2}$')


def _safe(name: str) -> bool:
    return bool(_SAFE_IDENT.match(name))


def _is_date_col(col: str) -> bool:
    lc = col.lower()
    return any(k in lc for k in ('date', 'time', '_at'))


_TND_KEYWORDS = ('amount', 'value', 'revenue', 'total', 'subtotal', 'paid')

def _x_label(col: str, truncation: Optional[str]) -> str:
    label = col.replace('_', ' ').title()
    if truncation:
        label += f' (by {truncation.title()})'
    return label

def _y_label(col: str, agg: str) -> str:
    if col == 'count':
        return 'Count'
    label = col.replace('_', ' ').title()
    if agg and agg != 'sum':
        label = f'{agg.title()} {label}'
    if any(k in col.lower() for k in _TND_KEYWORDS):
        label += ' (TND)'
    return label


def _build_where(
    filter_column: Optional[str],
    filter_value: Optional[str],
    filter_column2: Optional[str],
    filter_value2: Optional[str],
    params: dict,
) -> str:
    """Return a WHERE clause (with leading space) for up to two filters.
    Year values (e.g. '2024') on date columns use EXTRACT(year FROM col) = year
    instead of equality, so they work correctly against TIMESTAMP columns."""
    clauses = []

    def _clause(col: Optional[str], val: Optional[str], key: str) -> None:
        if not col or val is None:
            return
        if _YEAR_RE.match(str(val)) and _is_date_col(col):
            clauses.append(f'EXTRACT(year FROM "{col}") = :{key}')
            params[key] = int(val)
        else:
            clauses.append(f'"{col}" = :{key}')
            params[key] = val

    _clause(filter_column,  filter_value,  'fv1')
    _clause(filter_column2, filter_value2, 'fv2')
    return (' WHERE ' + ' AND '.join(clauses)) if clauses else ''


@tool
def generate_chart(
    chart_type: str,
    x_column: str,
    y_column: str,
    data_source: str,
    title: str,
    filter_column: Optional[str] = None,
    filter_value: Optional[str] = None,
    filter_column2: Optional[str] = None,
    filter_value2: Optional[str] = None,
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
    filter_column / filter_value: first WHERE condition (e.g. status='won').
    filter_column2 / filter_value2: optional second WHERE condition (e.g. created_date='2024').
      Year values (4 digits) on date columns automatically use EXTRACT(year FROM col) = year.
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
    if filter_column2 and not _safe(filter_column2):
        return f"Invalid filter_column2 name: '{filter_column2}'."
    if x_truncation and x_truncation not in VALID_TRUNCATIONS:
        return f"Invalid x_truncation '{x_truncation}'. Choose from: {', '.join(sorted(VALID_TRUNCATIONS))}"

    params: dict = {}
    where = _build_where(filter_column, filter_value, filter_column2, filter_value2, params)

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
        sql = (
            f'SELECT {select_part} FROM warehouse.{data_source}'
            f'{where}'
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
        sql = (
            f'SELECT {select_part} FROM warehouse.{data_source}'
            f'{where}'
            f' GROUP BY "{x_column}" ORDER BY value DESC LIMIT {int(min(limit, 100))}'
        )

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

    is_currency = any(k in y_column.lower() for k in _TND_KEYWORDS) and y_column != 'count'
    y_fmt = ':,.0f} TND' if is_currency else ':,}'

    # Build Plotly trace
    if chart_type == 'bar':
        trace = {
            'type': 'bar', 'x': x_values, 'y': y_values, 'name': title,
            'marker': {'color': '#6C63FF'},
            'hovertemplate': f'<b>%{{x}}</b><br>{_y_label(y_column, aggregation)}: %{{y{y_fmt}<extra></extra>',
        }
    elif chart_type == 'line':
        trace = {
            'type': 'scatter', 'mode': 'lines', 'x': x_values, 'y': y_values,
            'name': title, 'line': {'color': '#6C63FF', 'width': 2.5},
            'hovertemplate': f'<b>%{{x}}</b><br>{_y_label(y_column, aggregation)}: %{{y{y_fmt}<extra></extra>',
        }
    elif chart_type == 'area':
        trace = {
            'type': 'scatter', 'mode': 'lines', 'x': x_values, 'y': y_values,
            'name': title, 'line': {'color': '#6C63FF', 'width': 2.5},
            'fill': 'tozeroy', 'fillcolor': 'rgba(108,99,255,0.1)',
            'hovertemplate': f'<b>%{{x}}</b><br>{_y_label(y_column, aggregation)}: %{{y{y_fmt}<extra></extra>',
        }
    elif chart_type == 'scatter':
        trace = {
            'type': 'scatter', 'mode': 'markers', 'x': x_values, 'y': y_values,
            'name': title, 'marker': {'color': '#6C63FF'},
            'hovertemplate': f'<b>%{{x}}</b><br>{_y_label(y_column, aggregation)}: %{{y{y_fmt}<extra></extra>',
        }
    elif chart_type in ('pie', 'donut'):
        value_label = _y_label(y_column, aggregation)
        trace = {
            'type': 'pie',
            'labels': x_values, 'values': y_values,
            'hole': 0.38 if chart_type == 'donut' else 0,
            'name': title, 'marker': {'colors': PALETTE},
            'textinfo': 'percent+label',
            'textfont': {'color': '#1E2D3D', 'size': 11},
            'hovertemplate': f'<b>%{{label}}</b><br>{value_label}: %{{value{y_fmt}<br>%{{percent}}<extra></extra>',
        }
    elif chart_type == 'funnel':
        trace = {
            'type': 'funnel', 'y': x_values, 'x': y_values, 'name': title,
            'marker': {'color': '#6C63FF'},
            'connector': {'line': {'color': '#D8E4F0', 'width': 1}},
            'textinfo': 'value+percent initial',
            'hovertemplate': f'<b>%{{label}}</b><br>{_y_label(y_column, aggregation)}: %{{value{y_fmt}<extra></extra>',
        }
    else:
        trace = {
            'type': 'bar', 'x': x_values, 'y': y_values, 'name': title,
            'marker': {'color': '#6C63FF'},
            'hovertemplate': f'<b>%{{x}}</b><br>{_y_label(y_column, aggregation)}: %{{y{y_fmt}<extra></extra>',
        }

    layout = dict(PLOTLY_BASE_LAYOUT)
    if chart_type in ('pie', 'donut'):
        layout['margin']    = {'l': 16, 'r': 16, 't': 40, 'b': 16}
        layout['legend']    = {'bgcolor': 'transparent', 'orientation': 'h', 'y': -0.1}
        layout['hovermode'] = 'closest'
    else:
        layout['xaxis'] = dict(layout.get('xaxis', {}))
        layout['xaxis']['title'] = {'text': _x_label(x_column, x_truncation)}
        layout['yaxis'] = dict(layout.get('yaxis', {}))
        layout['yaxis']['title'] = {'text': _y_label(y_column, aggregation)}

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
