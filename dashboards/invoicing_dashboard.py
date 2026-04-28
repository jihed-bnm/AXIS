"""JBM Consulting — Finance & Invoicing Dashboard"""
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
RED = "#e74c3c"
TEMPLATE = "plotly_dark"

PERIOD_OPTIONS = [
    "All time", "Last 12 months", "Last 6 months", "Last 3 months",
    "2026", "2025", "2024", "2023",
]
STATUSES = ["All", "paid", "pending", "overdue", "partial", "cancelled"]


# ── Filter helpers ────────────────────────────────────────────────────────────

def _and(*conditions):
    active = [c for c in conditions if c]
    if not active:
        return ""
    return "WHERE " + " AND ".join(active)


def _period_cond(period, date_col="invoice_date"):
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


def _status_cond(status):
    return f"status = '{status}'" if status != "All" else ""


# ── Cached data loaders ───────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_kpis(period):
    pc = _period_cond(period, "invoice_date")
    result = query(f"""
        SELECT
            COALESCE(SUM(CASE WHEN status = 'paid'    THEN total_amount END), 0) AS collected,
            COALESCE(SUM(CASE WHEN status = 'pending' THEN total_amount END), 0) AS pending,
            COALESCE(SUM(CASE WHEN status = 'overdue' THEN total_amount END), 0) AS overdue,
            COUNT(*) AS total_count,
            COUNT(CASE WHEN status = 'paid' THEN 1 END) AS paid_count
        FROM warehouse.fact_revenue {_and(pc)}
    """)
    collected = float(result["collected"].iloc[0])
    pending   = float(result["pending"].iloc[0])
    overdue   = float(result["overdue"].iloc[0])
    total_c   = int(result["total_count"].iloc[0])
    paid_c    = int(result["paid_count"].iloc[0])
    collection_rate = (paid_c / total_c * 100) if total_c > 0 else 0.0
    return collected, pending, overdue, collection_rate


@st.cache_data(ttl=300)
def load_revenue_by_year(period):
    pc = _period_cond(period, "invoice_date")
    w = _and("invoice_date IS NOT NULL", "invoice_date <= CURRENT_DATE", pc)
    return query(f"""
        SELECT EXTRACT(year FROM invoice_date)::int AS year,
               COALESCE(SUM(CASE WHEN status = 'paid'    THEN total_amount END), 0) AS collected,
               COALESCE(SUM(CASE WHEN status = 'pending' THEN total_amount END), 0) AS pending,
               COALESCE(SUM(CASE WHEN status = 'overdue' THEN total_amount END), 0) AS overdue
        FROM warehouse.fact_revenue {w}
        GROUP BY 1
        ORDER BY 1
    """)


@st.cache_data(ttl=300)
def load_cumulative_revenue(period):
    pc = _period_cond(period, "invoice_date")
    paid_cond = "status = 'paid'"
    w = _and(paid_cond, "invoice_date IS NOT NULL", "invoice_date <= CURRENT_DATE", pc)
    df = query(f"""
        SELECT EXTRACT(year  FROM invoice_date)::int AS year,
               EXTRACT(month FROM invoice_date)::int AS month,
               SUM(total_amount) AS monthly_revenue
        FROM warehouse.fact_revenue {w}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)
    if not df.empty:
        df["date"] = pd.to_datetime(
            df["year"].astype(str) + "-" + df["month"].astype(str) + "-01"
        )
        df["cumulative"] = df["monthly_revenue"].cumsum()
    return df


@st.cache_data(ttl=300)
def load_payment_delay(period):
    pc = _period_cond(period, "invoice_date")
    paid_cond = "status = 'paid'"
    w = _and(paid_cond, "payment_delay_days IS NOT NULL", pc)
    return query(f"""
        SELECT
            CASE
                WHEN payment_delay_days <= 0  THEN 'On Time'
                WHEN payment_delay_days <= 30 THEN 'Late 1-30 days'
                WHEN payment_delay_days <= 60 THEN 'Late 31-60 days'
                ELSE                               'Late 60+ days'
            END AS delay_category,
            COUNT(*) AS count
        FROM warehouse.fact_revenue {w}
        GROUP BY delay_category
    """)


@st.cache_data(ttl=300)
def load_status_distribution(period):
    pc = _period_cond(period, "invoice_date")
    w = _and("status IS NOT NULL", "invoice_date <= CURRENT_DATE", pc)
    return query(f"""
        SELECT status, COUNT(*) AS invoice_count
        FROM warehouse.fact_revenue {w}
        GROUP BY status
        ORDER BY invoice_count DESC
    """)


@st.cache_data(ttl=300)
def load_top_clients(period, status):
    pc = _period_cond(period, "invoice_date")
    # FIX: added total_amount IS NOT NULL to exclude null totals from SUM
    w = _and(
        _status_cond(status),
        "company_name IS NOT NULL",
        "total_amount IS NOT NULL",
        "invoice_date <= CURRENT_DATE",
        pc,
    )
    return query(f"""
        SELECT UPPER(TRIM(company_name)) AS company_name,
               SUM(total_amount) AS total_invoiced
        FROM warehouse.fact_revenue {w}
        GROUP BY UPPER(TRIM(company_name))
        ORDER BY total_invoiced DESC
        LIMIT 10
    """)


@st.cache_data(ttl=300)
def load_monthly_activity(period):
    pc = _period_cond(period, "invoice_date")
    # FIX: added invoice_date <= CURRENT_DATE to exclude future dates
    w = _and("invoice_date IS NOT NULL", "invoice_date <= CURRENT_DATE", pc)
    df = query(f"""
        SELECT EXTRACT(year  FROM invoice_date)::int AS year,
               EXTRACT(month FROM invoice_date)::int AS month,
               COUNT(*)                                                          AS issued,
               COUNT(*) FILTER (WHERE status = 'paid')                          AS paid,
               COUNT(*) FILTER (WHERE status = 'overdue' OR is_overdue = true)  AS overdue
        FROM warehouse.fact_revenue {w}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)
    if not df.empty:
        df["date"] = pd.to_datetime(
            df["year"].astype(str) + "-" + df["month"].astype(str) + "-01"
        )
    return df


# ── Main show() ───────────────────────────────────────────────────────────────

def show():
    st.title("JBM Consulting — Finance & Invoicing Dashboard")

    # ── Sidebar filters ───────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader("Filters")
    period = st.sidebar.selectbox("Period", PERIOD_OPTIONS, index=0)
    status = st.sidebar.selectbox("Invoice Status", STATUSES, index=0)

    with st.spinner("Loading dashboard data..."):
        try:
            collected, pending, overdue, collection_rate = load_kpis(period)
        except Exception as e:
            st.error(f"Database error: {e}")
            return

    # ── Row 1: KPI Cards ──────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Collected (Paid)", f"{collected:,.0f} TND")
    c2.metric("Total Pending", f"{pending:,.0f} TND")
    c3.metric("Total Overdue", f"{overdue:,.0f} TND")
    c4.metric("Collection Rate", f"{collection_rate:.1f}%")

    st.markdown("---")

    # ── Row 2: Revenue by Year ────────────────────────────────────────────────
    yr_df = load_revenue_by_year(period)
    if not yr_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Collected", x=yr_df["year"], y=yr_df["collected"],
            marker_color=GREEN,
        ))
        fig.add_trace(go.Bar(
            name="Pending", x=yr_df["year"], y=yr_df["pending"],
            marker_color=ORANGE,
        ))
        fig.add_trace(go.Bar(
            name="Overdue", x=yr_df["year"], y=yr_df["overdue"],
            marker_color=RED,
        ))
        fig.update_layout(
            title="Revenue by Year (TND)",
            template=TEMPLATE,
            barmode="group",
            xaxis_title="Year",
            yaxis_title="Amount (TND)",
            legend_title="Status",
        )
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("No yearly revenue data for the selected period.")

    # ── Row 3: Cumulative Revenue | Payment Delay Distribution ───────────────
    col_left, col_right = st.columns(2)

    with col_left:
        cum_df = load_cumulative_revenue(period)
        if not cum_df.empty:
            fig = px.line(
                cum_df,
                x="date",
                y="cumulative",
                title="Cumulative Revenue Over Time (TND)",
                labels={"date": "Month", "cumulative": "Cumulative Revenue (TND)"},
                template=TEMPLATE,
                color_discrete_sequence=[GREEN],
            )
            fig.update_traces(line_width=2.5, fill="tozeroy",
                              fillcolor="rgba(62,207,142,0.15)")
            fig.update_layout(hovermode="x unified")
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("No cumulative revenue data for the selected period.")

    with col_right:
        delay_df = load_payment_delay(period)
        if not delay_df.empty:
            delay_color_map = {
                "On Time": GREEN,
                "Late 1-30 days": ORANGE,
                "Late 31-60 days": "#f39c12",
                "Late 60+ days": RED,
            }
            fig = px.bar(
                delay_df,
                x="delay_category",
                y="count",
                title="Payment Delay Distribution",
                labels={"delay_category": "Delay Category", "count": "Invoice Count"},
                template=TEMPLATE,
                color="delay_category",
                color_discrete_map=delay_color_map,
            )
            fig.update_layout(showlegend=False, xaxis_title="")
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("No payment delay data for the selected period.")

    # ── Row 4: Status Distribution | Top 10 Clients ──────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        status_df = load_status_distribution(period)
        if not status_df.empty:
            color_map = {
                "paid": GREEN, "pending": ORANGE,
                "overdue": RED, "partial": BLUE, "cancelled": "#95a5a6",
            }
            fig = px.pie(
                status_df,
                names="status",
                values="invoice_count",
                title="Invoice Status Distribution",
                template=TEMPLATE,
                color="status",
                color_discrete_map=color_map,
                hole=0.35,
            )
            fig.update_traces(textinfo="percent+label")
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("No status distribution data for the selected period.")

    with col_right:
        top_df = load_top_clients(period, status)
        if not top_df.empty:
            top_df = top_df.sort_values("total_invoiced")
            max_val = top_df["total_invoiced"].max()
            fig = px.bar(
                top_df,
                x="total_invoiced",
                y="company_name",
                orientation="h",
                title="Top 10 Clients by Invoice Value",
                labels={"total_invoiced": "Total Invoiced (TND)", "company_name": "Company"},
                template=TEMPLATE,
                color_discrete_sequence=[BLUE],
                text="total_invoiced",
            )
            fig.update_traces(texttemplate="%{text:,.0f} TND", textposition="outside")
            fig.update_layout(
                yaxis_title="",
                xaxis=dict(range=[0, max_val * 1.30]),
            )
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("No client invoice data for the selected period.")

    # ── Row 5: Monthly Invoicing Activity ─────────────────────────────────────
    act_df = load_monthly_activity(period)
    if not act_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Issued", x=act_df["date"], y=act_df["issued"],
            marker_color=BLUE,
        ))
        fig.add_trace(go.Bar(
            name="Paid", x=act_df["date"], y=act_df["paid"],
            marker_color=GREEN,
        ))
        fig.add_trace(go.Bar(
            name="Overdue", x=act_df["date"], y=act_df["overdue"],
            marker_color=RED,
        ))
        fig.update_layout(
            title="Monthly Invoicing Activity",
            template=TEMPLATE,
            barmode="stack",
            xaxis_title="Month",
            yaxis_title="Invoice Count",
            legend_title="Status",
            hovermode="x unified",
        )
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("No monthly activity data for the selected period.")