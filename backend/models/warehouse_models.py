"""
Data warehouse dimensional models (star schema) for JBM Consulting ERP analytics.

Schema overview:
  Dimensions : dim_date, dim_client, dim_employee, dim_service
  Facts      : fact_revenue, fact_deals, fact_project_performance, fact_hr_events
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Date, Text, Index
from datetime import datetime
from backend.models.database import Base


# ── Dimension Tables ───────────────────────────────────────────────────────────

class DimDate(Base):
    """
    Date dimension — pre-populated for the full analysis period.
    Grain: one row per calendar day.
    """
    __tablename__ = "dim_date"

    date_key    = Column(Integer, primary_key=True)  # YYYYMMDD integer key
    full_date   = Column(Date, nullable=False, unique=True, index=True)
    day         = Column(Integer, nullable=False)
    month       = Column(Integer, nullable=False)
    month_name  = Column(String(20), nullable=False)
    quarter     = Column(Integer, nullable=False)   # 1-4
    year        = Column(Integer, nullable=False)
    week_of_year = Column(Integer, nullable=False)
    day_of_week  = Column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    day_name     = Column(String(20), nullable=False)
    is_weekend   = Column(Boolean, default=False)
    fiscal_year  = Column(Integer, nullable=False)  # same as calendar year for Tunisia
    fiscal_quarter = Column(String(10), nullable=False)  # e.g. "FY2024Q1"


class DimClient(Base):
    """
    Client dimension — snapshot of company attributes at ETL time.
    Grain: one row per company (slowly changing — overwrite strategy for now).
    """
    __tablename__ = "dim_client"

    client_key    = Column(Integer, primary_key=True, autoincrement=True)
    source_id     = Column(Integer, nullable=False, unique=True, index=True)  # companies.id
    name          = Column(String, nullable=False)
    industry      = Column(String)
    city          = Column(String)
    country       = Column(String)
    status        = Column(String)    # client, prospect, inactive
    first_deal_date = Column(Date)
    total_won_deals = Column(Integer, default=0)
    total_revenue   = Column(Float, default=0.0)   # cumulative paid invoices
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DimEmployee(Base):
    """
    Employee dimension — current state snapshot at ETL time.
    Grain: one row per employee.
    """
    __tablename__ = "dim_employee"

    employee_key  = Column(Integer, primary_key=True, autoincrement=True)
    source_id     = Column(Integer, nullable=False, unique=True, index=True)  # employees.id
    full_name     = Column(String, nullable=False)
    position      = Column(String)
    department    = Column(String)
    contract_type = Column(String)
    hire_date     = Column(Date)
    salary        = Column(Float)
    status        = Column(String)    # active, resigned, terminated
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DimService(Base):
    """
    Service/product dimension — categories of consulting work billed by JBM.
    Grain: one row per service category.
    Populated manually or derived from invoice item descriptions via ETL.
    """
    __tablename__ = "dim_service"

    service_key   = Column(Integer, primary_key=True, autoincrement=True)
    name          = Column(String, nullable=False, unique=True)
    category      = Column(String)   # ERP, Cloud, Development, Consulting, Support
    billing_type  = Column(String)   # fixed, time_and_materials, retainer
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Fact Tables ────────────────────────────────────────────────────────────────

class FactRevenue(Base):
    """
    Revenue fact — one row per invoice.
    Grain: invoice.
    Dimensions: date (issue), client.
    Measures: subtotal, tax, total, payment lag (days from issue to paid).
    """
    __tablename__ = "fact_revenue"

    revenue_key    = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id     = Column(Integer, nullable=False, index=True)  # invoices.id
    date_key       = Column(Integer, nullable=False, index=True)  # FK -> dim_date.date_key (issue date)
    client_key     = Column(Integer, nullable=False, index=True)  # FK -> dim_client.client_key
    invoice_number = Column(String, nullable=False)
    issue_year     = Column(Integer, nullable=False)
    issue_month    = Column(Integer, nullable=False)
    issue_quarter  = Column(Integer, nullable=False)
    status         = Column(String)  # draft, sent, paid, overdue, cancelled
    subtotal       = Column(Float, default=0.0)
    tax_amount     = Column(Float, default=0.0)
    total          = Column(Float, default=0.0)
    currency       = Column(String, default="TND")
    days_to_pay    = Column(Integer)  # NULL if not paid; (paid_at - issue_date).days
    is_paid        = Column(Boolean, default=False)
    is_overdue     = Column(Boolean, default=False)
    loaded_at      = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_fact_revenue_year_month", "issue_year", "issue_month"),
    )


class FactDeals(Base):
    """
    Deals fact — one row per deal.
    Grain: deal.
    Dimensions: created date, closed date, client.
    Measures: value, sales cycle days, win/loss flag.
    """
    __tablename__ = "fact_deals"

    deal_key       = Column(Integer, primary_key=True, autoincrement=True)
    deal_id        = Column(Integer, nullable=False, index=True)   # deals.id
    client_key     = Column(Integer, nullable=False, index=True)   # FK -> dim_client
    created_date_key = Column(Integer, nullable=False, index=True) # FK -> dim_date
    closed_date_key  = Column(Integer)                              # FK -> dim_date, NULL if open
    closed_date      = Column(Date)                                  # actual close date, NULL if open
    title          = Column(String)
    value          = Column(Float, default=0.0)
    currency       = Column(String, default="TND")
    status         = Column(String)   # open, won, lost, on_hold
    stage          = Column(String)
    probability    = Column(Integer)
    is_won         = Column(Boolean, default=False)
    is_lost        = Column(Boolean, default=False)
    sales_cycle_days = Column(Integer)  # closed_at - created_at, NULL if open
    created_year   = Column(Integer)
    created_month  = Column(Integer)
    created_quarter = Column(Integer)
    loaded_at      = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_fact_deals_year_month", "created_year", "created_month"),
    )


class FactProjectPerformance(Base):
    """
    Project performance fact — one row per project (snapshot at ETL time).
    Grain: project.
    Dimensions: start date, client, manager employee.
    Measures: budget, spent, hours logged, task completion %, budget burn %.
    """
    __tablename__ = "fact_project_performance"

    perf_key         = Column(Integer, primary_key=True, autoincrement=True)
    project_id       = Column(Integer, nullable=False, index=True)
    client_key       = Column(Integer, nullable=False, index=True)
    manager_key      = Column(Integer)   # FK -> dim_employee
    start_date_key   = Column(Integer, nullable=False, index=True)  # FK -> dim_date
    end_date_key     = Column(Integer)   # FK -> dim_date, NULL if ongoing
    project_name     = Column(String)
    status           = Column(String)
    priority         = Column(String)
    budget           = Column(Float, default=0.0)
    spent            = Column(Float, default=0.0)
    budget_used_pct  = Column(Float, default=0.0)   # spent / budget * 100
    total_tasks      = Column(Integer, default=0)
    done_tasks       = Column(Integer, default=0)
    completion_pct   = Column(Float, default=0.0)   # done_tasks / total_tasks * 100
    total_hours      = Column(Float, default=0.0)
    is_over_budget   = Column(Boolean, default=False)
    is_overdue       = Column(Boolean, default=False)
    duration_days    = Column(Integer)   # end_date - start_date
    start_year       = Column(Integer)
    start_month      = Column(Integer)
    loaded_at        = Column(DateTime, default=datetime.utcnow)


class FactHrEvents(Base):
    """
    HR events fact — one row per payroll record or leave request event.
    Grain: individual payroll payment or leave request.
    Dimensions: date, employee.
    Measures: net salary, leave days.
    """
    __tablename__ = "fact_hr_events"

    event_key       = Column(Integer, primary_key=True, autoincrement=True)
    event_type      = Column(String, nullable=False)  # payroll, leave
    source_id       = Column(Integer, nullable=False)  # payroll.id or leave_request.id
    employee_key    = Column(Integer, nullable=False, index=True)  # FK -> dim_employee
    date_key        = Column(Integer, nullable=False, index=True)  # FK -> dim_date (period start)
    event_year      = Column(Integer, nullable=False)
    event_month     = Column(Integer, nullable=False)
    # Payroll measures
    base_salary     = Column(Float)
    bonuses         = Column(Float)
    deductions      = Column(Float)
    net_salary      = Column(Float)
    payroll_status  = Column(String)   # pending, paid
    # Leave measures
    leave_type      = Column(String)
    leave_days      = Column(Integer)
    leave_status    = Column(String)   # pending, approved, rejected
    loaded_at       = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_fact_hr_events_year_month", "event_year", "event_month"),
        Index("ix_fact_hr_events_type_source", "event_type", "source_id"),
    )
