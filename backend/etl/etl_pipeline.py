"""
ETL pipeline: extracts from operational tables and loads into the data warehouse.

Usage:
    python -m backend.etl.etl_pipeline

Functions:
    run_full_etl()          — runs all ETL steps in dependency order
    etl_dim_date()          — populate dim_date for analysis period
    etl_dim_clients()       — upsert companies -> dim_client
    etl_dim_employees()     — upsert employees -> dim_employee
    etl_dim_services()      — populate dim_service from static list
    etl_fact_revenue()      — load invoices -> fact_revenue
    etl_fact_deals()        — load deals -> fact_deals
    etl_fact_projects()     — load projects -> fact_project_performance
    etl_fact_hr_events()    — load payroll + leave -> fact_hr_events
"""

# DEPRECATED — not used in current data flow
# Active ETL: airflow/dags/etl_jbm_pipeline.py

from datetime import date, datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.database import get_session, engine, Base
from backend.models.crm_models import Company, Deal
from backend.models.invoice_models import Invoice
from backend.models.warehouse_models import (
    DimDate, DimClient, DimEmployee, DimService,
    FactRevenue, FactDeals, FactProjectPerformance, FactHrEvents,
)
from backend.error_handler import logger

# Analysis window
ETL_START = date(2023, 1, 1)
ETL_END   = date(2026, 12, 31)

MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _date_key(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def _quarter(month: int) -> int:
    return (month - 1) // 3 + 1


# ── Dimension ETL ──────────────────────────────────────────────────────────────

def etl_dim_date(db: Session) -> int:
    """
    Populate dim_date for every calendar day in [ETL_START, ETL_END].
    Uses upsert strategy: inserts only missing rows.
    Returns number of rows inserted.
    """
    existing = {row.date_key for row in db.query(DimDate.date_key).all()}
    inserted = 0
    cur = ETL_START
    while cur <= ETL_END:
        key = _date_key(cur)
        if key not in existing:
            q = _quarter(cur.month)
            db.add(DimDate(
                date_key=key,
                full_date=cur,
                day=cur.day,
                month=cur.month,
                month_name=MONTH_NAMES[cur.month],
                quarter=q,
                year=cur.year,
                week_of_year=cur.isocalendar()[1],
                day_of_week=cur.weekday(),
                day_name=DAY_NAMES[cur.weekday()],
                is_weekend=cur.weekday() >= 5,
                fiscal_year=cur.year,
                fiscal_quarter=f"FY{cur.year}Q{q}",
            ))
            inserted += 1
        cur += timedelta(days=1)
    db.flush()
    return inserted


def etl_dim_clients(db: Session) -> int:
    """
    Upsert companies into dim_client.
    Computes first_deal_date, total_won_deals, total_revenue from operational data.
    Returns number of rows upserted.
    """
    companies = db.query(Company).filter(Company.is_deleted == False).all()
    upserted = 0

    for co in companies:
        first_deal = (
            db.query(func.min(Deal.created_at))
            .filter(Deal.company_id == co.id, Deal.is_deleted == False)
            .scalar()
        )
        won_count = (
            db.query(func.count(Deal.id))
            .filter(Deal.company_id == co.id, Deal.status == "won", Deal.is_deleted == False)
            .scalar() or 0
        )
        total_revenue = (
            db.query(func.sum(Invoice.total))
            .filter(Invoice.company_id == co.id, Invoice.status == "paid", Invoice.is_deleted == False)
            .scalar() or 0.0
        )

        existing = db.query(DimClient).filter(DimClient.source_id == co.id).first()
        if existing:
            existing.name = co.name
            existing.industry = co.industry
            existing.city = co.city
            existing.country = co.country
            existing.status = co.status
            existing.first_deal_date = first_deal.date() if first_deal else None
            existing.total_won_deals = won_count
            existing.total_revenue = total_revenue
            existing.updated_at = datetime.utcnow()
        else:
            db.add(DimClient(
                source_id=co.id,
                name=co.name,
                industry=co.industry,
                city=co.city,
                country=co.country,
                status=co.status,
                first_deal_date=first_deal.date() if first_deal else None,
                total_won_deals=won_count,
                total_revenue=total_revenue,
            ))
        upserted += 1

    db.flush()
    return upserted


def etl_dim_employees(db: Session) -> int:
    """
    Upsert employees into dim_employee.
    Returns number of rows upserted.
    """
    employees = db.query(Employee, Department.name.label("dept_name")).outerjoin(
        Department, Employee.department_id == Department.id
    ).filter(Employee.is_deleted == False).all()

    upserted = 0
    for emp, dept_name in employees:
        existing = db.query(DimEmployee).filter(DimEmployee.source_id == emp.id).first()
        full_name = f"{emp.first_name} {emp.last_name}"
        if existing:
            existing.full_name = full_name
            existing.position = emp.position
            existing.department = dept_name
            existing.contract_type = emp.contract_type
            existing.hire_date = emp.hire_date
            existing.salary = emp.salary
            existing.status = emp.status
            existing.updated_at = datetime.utcnow()
        else:
            db.add(DimEmployee(
                source_id=emp.id,
                full_name=full_name,
                position=emp.position,
                department=dept_name,
                contract_type=emp.contract_type,
                hire_date=emp.hire_date,
                salary=emp.salary,
                status=emp.status,
            ))
        upserted += 1

    db.flush()
    return upserted


def etl_dim_services(db: Session) -> int:
    """
    Populate dim_service from a static list of consulting service categories.
    Idempotent — only inserts new rows.
    Returns number of rows inserted.
    """
    services = [
        ("ERP Implementation",          "ERP",         "fixed"),
        ("Cloud Migration",             "Cloud",        "fixed"),
        ("Custom Software Development", "Development",  "time_and_materials"),
        ("Mobile App Development",      "Development",  "fixed"),
        ("IT Consulting",               "Consulting",   "time_and_materials"),
        ("Digital Transformation",      "Consulting",   "fixed"),
        ("BI & Analytics",              "Analytics",    "fixed"),
        ("Cybersecurity Audit",         "Security",     "fixed"),
        ("Support & Maintenance",       "Support",      "retainer"),
        ("Training & Change Management","Consulting",   "fixed"),
        ("API Integration",             "Development",  "fixed"),
        ("Infrastructure & DevOps",     "Cloud",        "time_and_materials"),
        ("Data Engineering",            "Analytics",    "time_and_materials"),
        ("UI/UX Design",                "Development",  "fixed"),
        ("Project Management Office",   "Consulting",   "retainer"),
    ]
    existing_names = {row.name for row in db.query(DimService.name).all()}
    inserted = 0
    for name, category, billing in services:
        if name not in existing_names:
            db.add(DimService(name=name, category=category, billing_type=billing))
            inserted += 1
    db.flush()
    return inserted


# ── Fact ETL ───────────────────────────────────────────────────────────────────

def etl_fact_revenue(db: Session) -> int:
    """
    Load invoices into fact_revenue.
    Truncate-and-reload strategy (clears existing rows first).
    Returns number of rows inserted.
    """
    db.query(FactRevenue).delete()
    db.flush()

    # Build client_key lookup
    client_key_map = {row.source_id: row.client_key for row in db.query(DimClient).all()}
    # Build date_key set for validation
    date_keys = {row.date_key for row in db.query(DimDate.date_key).all()}

    invoices = db.query(Invoice).filter(Invoice.is_deleted == False).all()
    inserted = 0
    today = date.today()

    for inv in invoices:
        if inv.issue_date is None:
            continue
        dk = _date_key(inv.issue_date)
        if dk not in date_keys:
            continue
        ck = client_key_map.get(inv.company_id)
        if ck is None:
            continue

        days_to_pay = None
        if inv.paid_at and inv.issue_date:
            days_to_pay = (inv.paid_at.date() - inv.issue_date).days

        is_overdue = (
            inv.status not in ("paid", "cancelled") and
            inv.due_date is not None and
            inv.due_date < today
        )

        db.add(FactRevenue(
            invoice_id=inv.id,
            date_key=dk,
            client_key=ck,
            invoice_number=inv.invoice_number,
            issue_year=inv.issue_date.year,
            issue_month=inv.issue_date.month,
            issue_quarter=_quarter(inv.issue_date.month),
            status=inv.status,
            subtotal=inv.subtotal or 0.0,
            tax_amount=inv.tax_amount or 0.0,
            total=inv.total or 0.0,
            currency=inv.currency or "TND",
            days_to_pay=days_to_pay,
            is_paid=(inv.status == "paid"),
            is_overdue=is_overdue,
        ))
        inserted += 1

    db.flush()
    return inserted


STAGE_MAP = {
    # French variants
    "prospection":      "prospecting",
    "qualification":    "qualification",
    "négociation":      "negotiation",
    "negociation":      "negotiation",
    "devis":            "proposal",
    "gagné":            "closed",
    "gagne":            "closed",
    "perdu":            "closed",
    # English dirty variants
    "closed-won":       "closed",
    "closed_won":       "closed",
    "closed won":       "closed",
    "closed-lost":      "closed",
    "closed_lost":      "closed",
    "propsal":          "proposal",
    "proposal":         "proposal",
    "qualify":          "qualification",
    "negotiation":      "negotiation",
    "prospecting":      "prospecting",
}


def etl_fact_deals(db: Session) -> int:
    """
    Load deals into fact_deals.
    Truncate-and-reload strategy.
    Returns number of rows inserted.
    """
    db.query(FactDeals).delete()
    db.flush()

    client_key_map = {row.source_id: row.client_key for row in db.query(DimClient).all()}
    date_keys = {row.date_key for row in db.query(DimDate.date_key).all()}

    deals = db.query(Deal).filter(Deal.is_deleted == False).all()
    inserted = 0

    for deal in deals:
        if deal.created_at is None:
            continue
        created_date = deal.created_at.date() if isinstance(deal.created_at, datetime) else deal.created_at
        cdk = _date_key(created_date)
        if cdk not in date_keys:
            continue
        ck = client_key_map.get(deal.company_id)
        if ck is None:
            continue

        closed_dk = None
        closed_date_val = None
        sales_cycle = None
        if deal.closed_at:
            closed_date = deal.closed_at.date() if isinstance(deal.closed_at, datetime) else deal.closed_at
            closed_date_val = closed_date
            closed_dk = _date_key(closed_date)
            if closed_dk not in date_keys:
                closed_dk = None
            sales_cycle = (closed_date - created_date).days

        raw_stage = (deal.stage or "").lower().strip()
        normalized_stage = STAGE_MAP.get(raw_stage, raw_stage) if raw_stage else deal.stage

        db.add(FactDeals(
            deal_id=deal.id,
            client_key=ck,
            created_date_key=cdk,
            closed_date_key=closed_dk,
            closed_date=closed_date_val,
            title=deal.title,
            value=deal.value or 0.0,
            currency=deal.currency or "TND",
            status=deal.status,
            stage=normalized_stage,
            probability=deal.probability,
            is_won=(deal.status == "won"),
            is_lost=(deal.status == "lost"),
            sales_cycle_days=sales_cycle,
            created_year=created_date.year,
            created_month=created_date.month,
            created_quarter=_quarter(created_date.month),
        ))
        inserted += 1

    db.flush()
    return inserted


def etl_fact_projects(db: Session) -> int:
    """
    Load project performance snapshots into fact_project_performance.
    Truncate-and-reload strategy.
    Returns number of rows inserted.
    """
    db.query(FactProjectPerformance).delete()
    db.flush()

    client_key_map   = {row.source_id: row.client_key for row in db.query(DimClient).all()}
    employee_key_map = {row.source_id: row.employee_key for row in db.query(DimEmployee).all()}
    date_keys        = {row.date_key for row in db.query(DimDate.date_key).all()}

    projects = db.query(Project).filter(Project.is_deleted == False).all()
    today = date.today()
    inserted = 0

    for proj in projects:
        if proj.start_date is None:
            continue
        sdk = _date_key(proj.start_date)
        if sdk not in date_keys:
            continue

        ck = client_key_map.get(proj.company_id)
        if ck is None:
            continue

        edk = _date_key(proj.end_date) if proj.end_date and _date_key(proj.end_date) in date_keys else None
        mk = employee_key_map.get(proj.manager_id)

        total_tasks = db.query(func.count(Task.id)).filter(Task.project_id == proj.id).scalar() or 0
        done_tasks  = db.query(func.count(Task.id)).filter(Task.project_id == proj.id, Task.status == "done").scalar() or 0
        total_hours = db.query(func.sum(TimeLog.hours)).filter(TimeLog.project_id == proj.id).scalar() or 0.0

        budget = proj.budget or 0.0
        spent  = proj.spent or 0.0
        budget_used_pct = round(spent / budget * 100, 1) if budget > 0 else 0.0
        completion_pct  = round(done_tasks / total_tasks * 100, 1) if total_tasks > 0 else 0.0
        duration_days   = (proj.end_date - proj.start_date).days if proj.end_date else None

        is_over_budget = spent > budget and budget > 0
        is_overdue = (
            proj.status not in ("completed", "cancelled") and
            proj.end_date is not None and
            proj.end_date < today
        )

        db.add(FactProjectPerformance(
            project_id=proj.id,
            client_key=ck,
            manager_key=mk,
            start_date_key=sdk,
            end_date_key=edk,
            project_name=proj.name,
            status=proj.status,
            priority=proj.priority,
            budget=budget,
            spent=spent,
            budget_used_pct=budget_used_pct,
            total_tasks=total_tasks,
            done_tasks=done_tasks,
            completion_pct=completion_pct,
            total_hours=float(total_hours),
            is_over_budget=is_over_budget,
            is_overdue=is_overdue,
            duration_days=duration_days,
            start_year=proj.start_date.year,
            start_month=proj.start_date.month,
        ))
        inserted += 1

    db.flush()
    return inserted


def etl_fact_hr_events(db: Session) -> int:
    """
    Load payroll records and leave requests into fact_hr_events.
    Truncate-and-reload strategy.
    Returns number of rows inserted.
    """
    db.query(FactHrEvents).delete()
    db.flush()

    employee_key_map = {row.source_id: row.employee_key for row in db.query(DimEmployee).all()}
    date_keys        = {row.date_key for row in db.query(DimDate.date_key).all()}

    inserted = 0

    # Payroll events
    payroll_records = db.query(Payroll).all()
    for pr in payroll_records:
        ek = employee_key_map.get(pr.employee_id)
        if ek is None:
            continue
        period_date = date(pr.year, pr.month, 1)
        dk = _date_key(period_date)
        if dk not in date_keys:
            continue

        db.add(FactHrEvents(
            event_type="payroll",
            source_id=pr.id,
            employee_key=ek,
            date_key=dk,
            event_year=pr.year,
            event_month=pr.month,
            base_salary=pr.base_salary,
            bonuses=pr.bonuses,
            deductions=pr.deductions,
            net_salary=pr.net_salary,
            payroll_status=pr.status,
        ))
        inserted += 1

    # Leave request events
    leave_records = db.query(LeaveRequest).all()
    for lr in leave_records:
        ek = employee_key_map.get(lr.employee_id)
        if ek is None:
            continue
        dk = _date_key(lr.start_date)
        if dk not in date_keys:
            continue

        db.add(FactHrEvents(
            event_type="leave",
            source_id=lr.id,
            employee_key=ek,
            date_key=dk,
            event_year=lr.start_date.year,
            event_month=lr.start_date.month,
            leave_type=lr.leave_type,
            leave_days=lr.days,
            leave_status=lr.status,
        ))
        inserted += 1

    db.flush()
    return inserted


# ── Full ETL orchestration ─────────────────────────────────────────────────────

def run_full_etl() -> dict:
    """
    Run all ETL steps in dependency order.
    Returns a dict with row counts per step.
    """
    # Ensure warehouse tables exist
    Base.metadata.create_all(bind=engine)

    db = get_session()
    results = {}
    try:
        logger.info("[ETL] Starting full ETL pipeline...")

        results["dim_date"]      = etl_dim_date(db)
        logger.info(f"[ETL] dim_date: {results['dim_date']} rows inserted")

        results["dim_clients"]   = etl_dim_clients(db)
        logger.info(f"[ETL] dim_client: {results['dim_clients']} rows upserted")

        results["dim_employees"] = etl_dim_employees(db)
        logger.info(f"[ETL] dim_employee: {results['dim_employees']} rows upserted")

        results["dim_services"]  = etl_dim_services(db)
        logger.info(f"[ETL] dim_service: {results['dim_services']} rows inserted")

        results["fact_revenue"]  = etl_fact_revenue(db)
        logger.info(f"[ETL] fact_revenue: {results['fact_revenue']} rows loaded")

        results["fact_deals"]    = etl_fact_deals(db)
        logger.info(f"[ETL] fact_deals: {results['fact_deals']} rows loaded")

        results["fact_projects"] = etl_fact_projects(db)
        logger.info(f"[ETL] fact_project_performance: {results['fact_projects']} rows loaded")

        results["fact_hr_events"] = etl_fact_hr_events(db)
        logger.info(f"[ETL] fact_hr_events: {results['fact_hr_events']} rows loaded")

        db.commit()
        logger.info("[ETL] Pipeline completed successfully.")

    except Exception as e:
        db.rollback()
        logger.error(f"[ETL] Pipeline failed: {e}")
        raise
    finally:
        db.close()

    return results


if __name__ == "__main__":
    stats = run_full_etl()
    print("\nETL Summary:")
    for step, count in stats.items():
        print(f"  {step:<25}: {count} rows")
