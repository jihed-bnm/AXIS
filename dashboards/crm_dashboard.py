"""JBM Consulting — Sales & CRM Dashboard"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

import warnings
warnings.filterwarnings('ignore')

from db import query

BLUE = "#4f7ef8"
GREEN = "#3ecf8e"
ORANGE = "#f5a623"
TEMPLATE = "plotly_dark"

PERIOD_OPTIONS = [
    "All time", "Last 12 months", "Last 6 months", "Last 3 months",
    "2026", "2025", "2024", "2023",
]


# ── Filter helpers ────────────────────────────────────────────────────────────

def _and(*conditions):
    active = [c for c in conditions if c]
    if not active:
        return ""
    return "WHERE " + " AND ".join(active)


def _period_cond(period, date_col="created_date"):
    """SQL condition fragment for a date column (no WHERE keyword)."""
    if period == "All time":
        return ""
    if period == "Last 12 months":
        return f"{date_col} >= CURRENT_DATE - INTERVAL '12 months'"
    if period == "Last 6 months":
        return f"{date_col} >= CURRENT_DATE - INTERVAL '6 months'"
    if period == "Last 3 months":
        return f"{date_col} >= CURRENT_DATE - INTERVAL '3 months'"
    if period in ("2023", "2024", "2025", "2026"):
        return f"EXTRACT(year FROM {date_col}) = {period}"
    return ""


# ── Cached data loaders ───────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_kpis(period):
    pc_rev = _period_cond(period, "invoice_date")
    pc_deal = _period_cond(period, "created_date")

    paid_cond = "status = 'paid'"
    total_revenue = query(
        f"SELECT COALESCE(SUM(total_amount), 0) FROM warehouse.fact_revenue "
        f"{_and(paid_cond, pc_rev)}"
    ).iloc[0, 0]

    dw = _and(pc_deal)
    total_deals = query(
        f"SELECT COUNT(*) FROM warehouse.fact_deals {dw}"
    ).iloc[0, 0]

    wl = query(f"""
        SELECT
            COUNT(*) FILTER (WHERE status = 'won')                AS won,
            COUNT(*) FILTER (WHERE status IN ('won', 'lost'))     AS closed
        FROM warehouse.fact_deals {dw}
    """)
    won = int(wl["won"].iloc[0])
    closed = int(wl["closed"].iloc[0])
    win_rate = (won / closed * 100) if closed > 0 else 0.0

    pw = _and("status = 'open'", pc_deal)
    active_pipeline = query(
        f"SELECT COALESCE(SUM(value_tnd), 0) FROM warehouse.fact_deals {pw}"
    ).iloc[0, 0]

    return float(total_revenue), int(total_deals), float(win_rate), float(active_pipeline)


@st.cache_data(ttl=300)
def load_revenue_trend(period):
    paid_cond = "status = 'paid'"
    pc = _period_cond(period, "invoice_date")
    w = _and(paid_cond, "invoice_date IS NOT NULL", "invoice_date <= CURRENT_DATE", pc)
    df = query(f"""
        SELECT EXTRACT(year  FROM invoice_date)::int AS year,
               EXTRACT(month FROM invoice_date)::int AS month,
               SUM(total_amount)                     AS revenue
        FROM warehouse.fact_revenue {w}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)
    if not df.empty:
        df["date"] = pd.to_datetime(
            df["year"].astype(str) + "-" + df["month"].astype(str) + "-01"
        )
    return df


@st.cache_data(ttl=300)
def load_win_rate_by_trimestre(period):
    w = _and("status IN ('won', 'lost')", _period_cond(period, "created_date"))
    df = query(f"""
        SELECT
            quarter,
            ROUND(
                COUNT(*) FILTER (WHERE status = 'won') * 100.0
                / NULLIF(COUNT(*), 0),
            1) AS win_rate
        FROM warehouse.fact_deals {w}
        GROUP BY quarter
        ORDER BY MIN(created_date)
    """)
    return df


@st.cache_data(ttl=300)
def load_pipeline_by_stage(period):
    w = _and("stage IS NOT NULL", _period_cond(period, "created_date"))
    return query(f"""
        SELECT stage, COUNT(DISTINCT deal_ref) AS deal_count
        FROM warehouse.fact_deals {w}
        GROUP BY stage
        ORDER BY deal_count DESC
    """)


@st.cache_data(ttl=300)
def load_top_clients(period):
    # FIX: added value_tnd IS NOT NULL to exclude null-value deals from SUM
    w = _and(
        "status = 'won'",
        "company_name IS NOT NULL",
        "value_tnd IS NOT NULL",
        _period_cond(period, "created_date"),
    )
    return query(f"""
        SELECT UPPER(TRIM(company_name)) AS company_name,
               SUM(value_tnd) AS total_value
        FROM warehouse.fact_deals {w}
        GROUP BY UPPER(TRIM(company_name))
        ORDER BY total_value DESC
        LIMIT 10
    """)


@st.cache_data(ttl=300)
def load_new_vs_closed(period):
    pc_new = _period_cond(period, "created_date")
    pc_closed = _period_cond(period, "closed_date")

    new_df = query(f"""
        SELECT DATE_TRUNC('month', created_date)::date AS month,
               COUNT(*) AS new_deals
        FROM warehouse.fact_deals
        {_and("created_date <= CURRENT_DATE", pc_new)}
        GROUP BY 1 ORDER BY 1
    """)

    closed_df = query(f"""
        SELECT DATE_TRUNC('month', closed_date)::date AS month,
               COUNT(*) AS closed_deals
        FROM warehouse.fact_deals
        {_and("status IN ('won', 'lost')",
              "closed_date IS NOT NULL", "closed_date <= CURRENT_DATE", pc_closed)}
        GROUP BY 1 ORDER BY 1
    """)

    merged = new_df.merge(closed_df, on="month", how="outer").sort_values("month")
    merged["new_deals"] = merged["new_deals"].fillna(0).astype(int)
    merged["closed_deals"] = merged["closed_deals"].fillna(0).astype(int)
    return merged


@st.cache_data(ttl=300)
def load_deal_size_dist(period):
    w = _and("deal_size_category IS NOT NULL",
             _period_cond(period, "created_date"))
    return query(f"""
        SELECT deal_size_category, COUNT(*) AS deal_count
        FROM warehouse.fact_deals {w}
        GROUP BY deal_size_category
        ORDER BY deal_count DESC
    """)


# ── Main show() ───────────────────────────────────────────────────────────────

def show():
    st.title("JBM Consulting — Sales & CRM Dashboard")

    # ── Sidebar filters ───────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader("Filters")
    period = st.sidebar.selectbox("Period", PERIOD_OPTIONS, index=0)

    with st.spinner("Loading dashboard data..."):
        try:
            total_revenue, total_deals, win_rate, active_pipeline = load_kpis(period)
        except Exception as e:
            st.error(f"Database error: {e}")
            return

    # ── Row 1: KPI Cards ──────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Revenue (Paid)", f"{total_revenue:,.0f} TND")
    c2.metric("Total Deals", f"{total_deals:,}")
    c3.metric("Win Rate", f"{win_rate:.1f}%")
    c4.metric("Active Pipeline", f"{active_pipeline:,.0f} TND")

    st.markdown("---")

    # ── Row 2: Revenue Trend ──────────────────────────────────────────────────
    rev_df = load_revenue_trend(period)
    if not rev_df.empty:
        fig = px.line(
            rev_df,
            x="date",
            y="revenue",
            title="Monthly Revenue Trend (TND)",
            labels={"date": "Month", "revenue": "Revenue (TND)"},
            template=TEMPLATE,
            color_discrete_sequence=[BLUE],
        )
        fig.update_traces(line_width=2.5, fill="tozeroy", fillcolor="rgba(79,126,248,0.15)")
        fig.update_layout(hovermode="x unified")
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("No revenue data for the selected period.")

    # ── Row 3: Win Rate by Trimestre | Pipeline Funnel ────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        wq_df = load_win_rate_by_trimestre(period)
        if not wq_df.empty:
            wq_df["color"] = wq_df["win_rate"].apply(
                lambda r: GREEN if r >= 40 else ORANGE
            )
            fig = go.Figure(go.Bar(
                x=wq_df["quarter"],
                y=wq_df["win_rate"],
                marker_color=wq_df["color"],
                text=wq_df["win_rate"].apply(lambda r: f"{r:.1f}%"),
                textposition="outside",
            ))
            fig.update_layout(
                title="Win Rate by Quarter (%)",
                template=TEMPLATE,
                xaxis_title="Quarter",
                yaxis_title="Win Rate (%)",
                yaxis_range=[0, 100],
                showlegend=False,
            )
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("No win-rate data for the selected period.")

    with col_right:
        stage_df = load_pipeline_by_stage(period)
        if not stage_df.empty:
            fig = px.funnel(
                stage_df,
                x="deal_count",
                y="stage",
                title="Pipeline by Stage (unique deals)",
                template=TEMPLATE,
                color_discrete_sequence=[BLUE],
            )
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("No pipeline stage data for the selected period.")

    # ── Row 4: Top 10 Clients | New vs Closed ────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        top_df = load_top_clients(period)
        if not top_df.empty:
            top_df = top_df.sort_values("total_value")
            max_val = top_df["total_value"].max()
            fig = px.bar(
                top_df,
                x="total_value",
                y="company_name",
                orientation="h",
                title="Top 10 Clients by Won Deal Value",
                labels={"total_value": "Total Value (TND)", "company_name": "Company"},
                template=TEMPLATE,
                color_discrete_sequence=[GREEN],
                text="total_value",
            )
            fig.update_traces(texttemplate="%{text:,.0f} TND", textposition="outside")
            fig.update_layout(
                yaxis_title="",
                xaxis=dict(range=[0, max_val * 1.30]),
            )
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("No client deal data for the selected period.")

    with col_right:
        nvc_df = load_new_vs_closed(period)
        if not nvc_df.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=nvc_df["month"], y=nvc_df["new_deals"],
                name="New Deals", line=dict(color=BLUE, width=2),
            ))
            fig.add_trace(go.Scatter(
                x=nvc_df["month"], y=nvc_df["closed_deals"],
                name="Closed Deals", line=dict(color=GREEN, width=2),
            ))
            fig.update_layout(
                title="New Deals vs Closed Deals per Month",
                template=TEMPLATE,
                xaxis_title="Month",
                yaxis_title="Count",
                hovermode="x unified",
            )
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("No deal trend data for the selected period.")

    # ── Row 5: Deal Size Distribution ────────────────────────────────────────
    size_df = load_deal_size_dist(period)
    if not size_df.empty:
        fig = px.pie(
            size_df,
            names="deal_size_category",
            values="deal_count",
            title="Deal Size Distribution",
            template=TEMPLATE,
            color_discrete_sequence=[BLUE, GREEN, ORANGE, "#e74c3c"],
            hole=0.35,
        )
        fig.update_traces(textinfo="percent+label")
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("No deal size data for the selected period.")