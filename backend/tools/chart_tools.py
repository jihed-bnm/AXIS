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
) -> str:
    """Generate a Plotly chart from warehouse data and save it to axis_charts table.
    Returns the chart_id and confirmation message.
    chart_type: bar, line, scatter, pie, donut, funnel, area
    data_source: fact_deals, fact_revenue, fact_activities, dim_client
    y_column: column name or 'count'
    aggregation: sum, count, avg, max, min
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

    # Build SQL — column names are validated above, data_source is whitelisted
    if y_column == 'count':
        select_part = f'"{x_column}", COUNT(*) AS value'
    else:
        select_part = f'"{x_column}", {aggregation.upper()}("{y_column}") AS value'

    sql = f'SELECT {select_part} FROM warehouse.{data_source}'
    params: dict = {}
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


_RISK_COLORS = {"High": "#FF4D4D", "Medium": "#FF9F43", "Low": "#3ECF8E"}
_OUTCOME_COLORS = {
    "Likely Win": "#3ECF8E",
    "Uncertain": "#FF9F43",
    "Likely Loss": "#FF4D4D",
    "Already Won": "#6C63FF",
    "Already Lost": "#A29BFE",
}


@tool
def generate_churn_risk_chart(
    chart_type: str = "bar",
    top_n: int = 10,
    min_probability: float = 0.0,
    max_probability: float = 1.0,
    session_id: str = "default",
) -> str:
    """Generate a predictive churn risk chart for all clients using the ML model.
    Supports filtering by probability range.
    chart_type: 'bar' (top N at-risk clients), 'pie' (risk level distribution), 'histogram' (probability distribution)
    top_n: number of clients to show in bar chart (default 10)
    """
    if chart_type not in {"bar", "pie", "histogram"}:
        return f"Invalid chart_type '{chart_type}'. Choose from: bar, pie, histogram"

    from backend.tools.prediction_charts import get_all_churn_predictions
    data = get_all_churn_predictions()
    if not data:
        return "No churn prediction data available. Ensure ETL has been run and ML model artifacts exist."

    if chart_type == "bar":
        filtered = [r for r in data if min_probability <= r["churn_probability"] <= max_probability]
        if not filtered:
            return f"No clients found with churn probability between {min_probability:.0%} and {max_probability:.0%}."
        subset = filtered[:max(1, int(top_n))]
        companies = [r["company"] for r in subset]
        probs = [r["churn_probability"] for r in subset]
        colors = [_RISK_COLORS.get(r["risk_level"], "#6C63FF") for r in subset]
        title = f"Top {len(subset)} Churn Risk Clients"
        trace = {
            "type": "bar",
            "x": companies,
            "y": probs,
            "name": title,
            "marker": {"color": colors},
        }
        layout = dict(PLOTLY_BASE_LAYOUT)
        layout["yaxis"] = {**PLOTLY_BASE_LAYOUT["yaxis"], "title": "Churn Probability", "tickformat": ".0%"}

    elif chart_type == "pie":
        from collections import Counter
        counts = Counter(r["risk_level"] for r in data)
        labels = [k for k in ("High", "Medium", "Low") if k in counts]
        values = [counts[k] for k in labels]
        colors = [_RISK_COLORS[k] for k in labels]
        title = "Churn Risk Level Distribution"
        trace = {
            "type": "pie",
            "labels": labels,
            "values": values,
            "name": title,
            "marker": {"colors": colors},
            "textinfo": "percent+label",
            "textfont": {"color": "#F0F0F0"},
        }
        layout = dict(PLOTLY_BASE_LAYOUT)
        layout["margin"] = {"l": 16, "r": 16, "t": 40, "b": 16}
        layout["legend"] = {"bgcolor": "transparent", "orientation": "h", "y": -0.1}

    else:  # histogram
        probs = [r["churn_probability"] for r in data]
        title = "Churn Probability Distribution"
        trace = {
            "type": "histogram",
            "x": probs,
            "name": title,
            "nbinsx": 10,
            "marker": {"color": "#6C63FF"},
        }
        layout = dict(PLOTLY_BASE_LAYOUT)
        layout["xaxis"] = {**PLOTLY_BASE_LAYOUT["xaxis"], "title": "Churn Probability"}
        layout["yaxis"] = {**PLOTLY_BASE_LAYOUT["yaxis"], "title": "Count"}

    config_json = json.dumps({"data": [trace], "layout": layout})

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
                    "title": title,
                    "chart_type": chart_type,
                    "config": config_json,
                    "query_used": "ML churn model batch prediction",
                    "session_id": session_id,
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
def generate_deal_prediction_chart(
    chart_type: str = "bar",
    top_n: int = 10,
    min_probability: float = 0.0,
    max_probability: float = 1.0,
    session_id: str = "default",
) -> str:
    """Generate a chart showing deal win probability predictions for open deals.
    Supports filtering by probability range.
    Examples: top 5 deals above 50% win chance, deals below 30% win probability, all uncertain deals.
    chart_type: 'bar' (default), 'scatter' (value vs probability), 'pie' (outcome distribution)
    """
    if chart_type not in {"bar", "scatter", "pie"}:
        return f"Invalid chart_type '{chart_type}'. Choose from: bar, scatter, pie"

    from backend.tools.prediction_charts import get_all_deal_predictions
    data = get_all_deal_predictions()
    if not data:
        return "No deal prediction data available. Ensure there are open deals and ML model artifacts exist."

    if chart_type == "bar":
        filtered = [d for d in data if min_probability <= d["win_probability"] <= max_probability]
        if not filtered:
            return f"No open deals found with win probability between {min_probability:.0%} and {max_probability:.0%}."
        subset = filtered[:max(1, int(top_n))]
        labels = [
            (d["title"][:30] + "...") if len(d["title"]) > 30 else d["title"]
            for d in subset
        ]
        probs = [d["win_probability"] * 100 for d in subset]
        colors = [_OUTCOME_COLORS.get(d["outcome_prediction"], "#6C63FF") for d in subset]
        title = "Deal win predictions by outcome"
        traces = [{
            "type": "bar",
            "orientation": "h",
            "x": probs,
            "y": labels,
            "name": title,
            "marker": {"color": colors},
        }]
        layout = dict(PLOTLY_BASE_LAYOUT)
        layout["xaxis"] = {**PLOTLY_BASE_LAYOUT["xaxis"], "title": "Win Probability (%)", "range": [0, 100]}
        layout["margin"] = {"l": 160, "r": 30, "t": 40, "b": 40}

    elif chart_type == "scatter":
        # One trace per outcome category so each gets a solid, discrete color with a legend entry.
        group_data: dict = {k: {"x": [], "y": []} for k in ["Likely Win", "Uncertain", "Likely Loss"]}
        for d in data:
            key = d["outcome_prediction"]
            if key in group_data:
                group_data[key]["x"].append(d["value"])
                group_data[key]["y"].append(d["win_probability"] * 100)

        title = "Deal Value vs. Win Probability"
        traces = [
            {
                "type": "scatter",
                "mode": "markers",
                "x": group_data[outcome]["x"],
                "y": group_data[outcome]["y"],
                "name": outcome,
                "marker": {"color": _OUTCOME_COLORS[outcome], "size": 10},
            }
            for outcome in ["Likely Win", "Uncertain", "Likely Loss"]
            if group_data[outcome]["x"]
        ]
        layout = dict(PLOTLY_BASE_LAYOUT)
        layout["xaxis"] = {**PLOTLY_BASE_LAYOUT["xaxis"], "title": "Deal Value (TND)"}
        layout["yaxis"] = {**PLOTLY_BASE_LAYOUT["yaxis"], "title": "Win Probability (%)"}

    else:  # pie
        from collections import Counter
        counts = Counter(d["outcome_prediction"] for d in data)
        labels = list(counts.keys())
        values = [counts[k] for k in labels]
        colors = [_OUTCOME_COLORS.get(k, "#6C63FF") for k in labels]
        title = "Deal Outcome Distribution"
        traces = [{
            "type": "pie",
            "labels": labels,
            "values": values,
            "name": title,
            "marker": {"colors": colors},
            "textinfo": "percent+label",
            "textfont": {"color": "#F0F0F0"},
        }]
        layout = dict(PLOTLY_BASE_LAYOUT)
        layout["margin"] = {"l": 16, "r": 16, "t": 40, "b": 16}
        layout["legend"] = {"bgcolor": "transparent", "orientation": "h", "y": -0.1}

    config_json = json.dumps({"data": traces, "layout": layout})

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
                    "title": title,
                    "chart_type": chart_type,
                    "config": config_json,
                    "query_used": "ML deal win model batch prediction",
                    "session_id": session_id,
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


ALL_CHART_TOOLS = [
    generate_chart,
    list_saved_charts,
    delete_chart,
    generate_churn_risk_chart,
    generate_deal_prediction_chart,
]
