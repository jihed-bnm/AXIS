"""
populate_operational.py
Reads clean staging CSVs and populates the 5 operational PostgreSQL tables:
  companies, contacts, deals, invoices, activities

Run: python data/populate_operational.py
"""
import csv
import re
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# ── Make sure project root is on sys.path ─────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from sqlalchemy import text
from backend.models.database import SessionLocal, engine
from backend.models.crm_models import Company, Contact, Deal, Activity

STAGING = ROOT / "data" / "staging"
ACTIVITY_LIMIT = 50_000


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_date(val: str):
    """Try several common date formats, return datetime or None."""
    if not val or not val.strip():
        return None
    val = val.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%b-%y", "%d/%m/%Y", "%m/%d/%Y",
                "%d-%m-%Y", "%b-%y", "%Y%m%d"):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    return None


def parse_float(val, default=0.0):
    if not val or not str(val).strip():
        return default
    try:
        return float(str(val).replace(",", "").replace(" ", "").replace("TND", "").strip())
    except (ValueError, TypeError):
        return default


def parse_int(val, default=0):
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default


def clamp(val, lo, hi):
    return max(lo, min(hi, val))


def norm(name: str) -> str:
    """Normalize company name for lookup."""
    return name.strip().upper() if name else ""


def _normalize_company_name(name: str) -> str:
    """Defensive guard against garbage-character pollution in raw/clean CSVs.
    Mirrors the cleanup logic from cleanup_companies.sql to prevent regression
    on re-runs. Strips *, #, !, @ injected by generate_raw_data.py (see
    line 168: random.choice(["@", "#", "e", "o"]) and line 791 for ###/!!!/***).
    Collapses internal whitespace, trims edges. Case is preserved intentionally.
    NOTE: 'e' and 'o' injections (also from line 168) cannot be stripped safely
    and are left for fuzzy-match cleanup if needed.
    """
    name = re.sub(r'[*#!@]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def read_csv(filename: str):
    path = STAGING / filename
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ── Step 0: TRUNCATE all 5 tables ─────────────────────────────────────────────

def truncate_tables():
    print("Truncating tables...")
    with engine.connect() as conn:
        conn.execute(text(
            "TRUNCATE activities, invoices, deals, contacts, companies "
            "RESTART IDENTITY CASCADE"
        ))
        conn.commit()
    print("  Done.\n")


# ── Step 1: Companies ─────────────────────────────────────────────────────────

STATUS_COMPANY = {
    "active":   "client",
    "prospect": "prospect",
    "churned":  "inactive",
}

def load_companies(db) -> dict:
    """Returns dict: norm(company_name) → Company.id"""
    rows = read_csv("clean_clients.csv")
    seen_names = set()
    inserted = 0
    skipped = 0

    for i, row in enumerate(rows, 1):
        name = _normalize_company_name(row.get("company_name", "").strip())
        if not name:
            skipped += 1
            continue
        key = norm(name)
        if key in seen_names:
            skipped += 1
            continue
        seen_names.add(key)

        status_raw = row.get("status", "").strip().lower()
        status = STATUS_COMPANY.get(status_raw, "prospect")
        created = parse_date(row.get("created_date", "")) or datetime.utcnow()

        try:
            company = Company(
                name=name,
                industry=row.get("industry") or None,
                phone=row.get("contact_phone") or None,   # company-level phone from contact
                email=row.get("contact_email") or None,   # company-level email from contact
                city=row.get("city") or None,
                country=row.get("country") or None,
                status=status,
                created_at=created,
            )
            db.add(company)
            if inserted % 1000 == 0:
                db.flush()
            inserted += 1
            if inserted % 1000 == 0:
                print(f"  companies: {inserted} inserted...")
        except Exception as e:
            skipped += 1
            db.rollback()
            continue

    db.commit()
    print(f"  companies: {inserted} inserted, {skipped} skipped.\n")

    # Build lookup dict
    lookup = {}
    for c in db.query(Company.id, Company.name).all():
        lookup[norm(c.name)] = c.id
    return lookup


# ── Step 2: Contacts ──────────────────────────────────────────────────────────

def load_contacts(db, company_lookup: dict) -> int:
    rows = read_csv("clean_clients.csv")
    inserted = 0
    skipped = 0
    seen = set()   # (company_id, norm_email) to avoid duplicates

    for i, row in enumerate(rows, 1):
        first = row.get("contact_firstname", "").strip()
        last  = row.get("contact_lastname",  "").strip()
        if not first or not last:
            skipped += 1
            continue

        cname = _normalize_company_name(row.get("company_name", "").strip())
        company_id = company_lookup.get(norm(cname))
        if not company_id:
            skipped += 1
            continue

        email = row.get("contact_email", "").strip() or None
        dedup_key = (company_id, norm(email) if email else f"{norm(first)}{norm(last)}")
        if dedup_key in seen:
            skipped += 1
            continue
        seen.add(dedup_key)

        created = parse_date(row.get("created_date", "")) or datetime.utcnow()

        try:
            contact = Contact(
                company_id=company_id,
                first_name=first,
                last_name=last,
                email=email,
                phone=row.get("contact_phone", "").strip() or None,
                is_primary=True,
                created_at=created,
            )
            db.add(contact)
            inserted += 1
            if inserted % 1000 == 0:
                db.flush()
                print(f"  contacts: {inserted} inserted...")
        except Exception as e:
            skipped += 1
            db.rollback()
            continue

    db.commit()
    print(f"  contacts: {inserted} inserted, {skipped} skipped.\n")
    return inserted


# ── Step 3: Deals ─────────────────────────────────────────────────────────────

STATUS_DEAL = {
    "won":       "won",
    "lost":      "lost",
    "open":      "open",
    "cancelled": "on_hold",
}

STAGE_DEAL = {
    "Prospecting":   "prospecting",
    "Qualification": "qualification",
    "Proposal":      "proposal",
    "Negotiation":   "negotiation",
    "Closed":        "closed",
}

def load_deals(db, company_lookup: dict) -> int:
    rows = read_csv("clean_deals.csv")
    inserted = 0
    skipped = 0

    for i, row in enumerate(rows, 1):
        cname = _normalize_company_name(row.get("company_name", "").strip())
        company_id = company_lookup.get(norm(cname))
        if not company_id:
            skipped += 1
            continue

        deal_id_raw = row.get("deal_id", "").strip()
        title_raw   = row.get("deal_title", "").strip()
        title       = title_raw if title_raw else (deal_id_raw or "Untitled")

        value = parse_float(row.get("value_tnd", ""), 0.0)

        status_raw = row.get("status", "").strip().lower()
        status = STATUS_DEAL.get(status_raw, "open")

        stage_raw = row.get("stage", "").strip()
        stage = STAGE_DEAL.get(stage_raw, "prospecting")

        prob = clamp(parse_int(row.get("probability", "50"), 50), 0, 100)

        created  = parse_date(row.get("created_date",  "")) or datetime.utcnow()
        closed_d = parse_date(row.get("closed_date",   ""))

        closed_at = None
        if status in ("won", "lost") and closed_d:
            closed_at = closed_d

        try:
            deal = Deal(
                company_id=company_id,
                title=title,
                value=value,
                currency="TND",
                status=status,
                stage=stage,
                probability=prob,
                notes=row.get("notes", "").strip() or None,
                closed_at=closed_at,
                created_at=created,
            )
            db.add(deal)
            inserted += 1
            if inserted % 1000 == 0:
                db.flush()
                print(f"  deals: {inserted} inserted...")
        except Exception as e:
            skipped += 1
            db.rollback()
            continue

    db.commit()
    print(f"  deals: {inserted} inserted, {skipped} skipped.\n")
    return inserted


# ── Step 4: Invoices ──────────────────────────────────────────────────────────

STATUS_INVOICE = {
    "paid":      "paid",
    "pending":   "draft",
    "overdue":   "overdue",
    "cancelled": "cancelled",
    "partial":   "sent",
}

def load_invoices(company_lookup: dict) -> int:
    """Uses raw SQL to avoid SQLAlchemy FK resolution error for missing 'projects' table."""
    rows = read_csv("clean_invoices.csv")
    inserted = 0
    skipped = 0
    seen_numbers = set()

    INSERT_SQL = text("""
        INSERT INTO invoices
            (invoice_number, company_id, status, subtotal, tax_rate, tax_amount,
             total, currency, issue_date, due_date, paid_at, notes, is_deleted, created_at)
        VALUES
            (:invoice_number, :company_id, :status, :subtotal, :tax_rate, :tax_amount,
             :total, :currency, :issue_date, :due_date, :paid_at, :notes, false, NOW())
    """)

    with engine.connect() as conn:
        for i, row in enumerate(rows, 1):
            inv_num = row.get("invoice_number", "").strip()
            if not inv_num or inv_num in seen_numbers:
                skipped += 1
                continue

            cname = _normalize_company_name(row.get("company_name", "").strip())
            company_id = company_lookup.get(norm(cname))
            if not company_id:
                skipped += 1
                continue

            seen_numbers.add(inv_num)

            status_raw = row.get("status", "").strip().lower()
            status = STATUS_INVOICE.get(status_raw, "draft")

            subtotal   = parse_float(row.get("subtotal",     ""), 0.0)
            tax_amount = parse_float(row.get("tax_amount",   ""), 0.0)
            total      = parse_float(row.get("total_amount", ""), 0.0)

            issue_date_dt = parse_date(row.get("invoice_date", ""))
            issue_date    = issue_date_dt.date() if issue_date_dt else None

            due_dt   = parse_date(row.get("due_date", ""))
            due_date = due_dt.date() if due_dt else None

            paid_at = None
            if status == "paid":
                delay = parse_int(row.get("payment_delay_days", ""), 0)
                if issue_date_dt and delay:
                    paid_at = issue_date_dt + timedelta(days=delay)
                elif row.get("payment_date"):
                    paid_at = parse_date(row.get("payment_date", ""))

            notes = row.get("notes", "").strip() or None

            try:
                conn.execute(INSERT_SQL, {
                    "invoice_number": inv_num,
                    "company_id":     company_id,
                    "status":         status,
                    "subtotal":       subtotal,
                    "tax_rate":       19.0,
                    "tax_amount":     tax_amount,
                    "total":          total,
                    "currency":       "TND",
                    "issue_date":     issue_date,
                    "due_date":       due_date,
                    "paid_at":        paid_at,
                    "notes":          notes,
                })
                inserted += 1
                if inserted % 1000 == 0:
                    conn.commit()
                    print(f"  invoices: {inserted} inserted...")
            except Exception as e:
                skipped += 1
                conn.rollback()
                continue

        conn.commit()

    print(f"  invoices: {inserted} inserted, {skipped} skipped.\n")
    return inserted


# ── Step 5: Activities ────────────────────────────────────────────────────────

TYPE_ACTIVITY = {
    "Appel":     "call",
    "Email":     "email",
    "Réunion":   "meeting",
    "Visite":    "meeting",
    "Démo":      "meeting",
    "Relance":   "call",
    "Proposition": "task",
    "Formation": "task",
    "Support":   "task",
    "Note":      "task",
    "Task":      "task",
}

def load_activities(db, company_lookup: dict) -> int:
    rows = read_csv("clean_activities.csv")
    inserted = 0
    skipped = 0

    for i, row in enumerate(rows[:ACTIVITY_LIMIT], 1):
        cname = _normalize_company_name(row.get("company_name", "").strip())
        company_id = company_lookup.get(norm(cname))
        if not company_id:
            skipped += 1
            continue

        act_type_raw = row.get("activity_type", "").strip()
        act_type = TYPE_ACTIVITY.get(act_type_raw, "task")

        desc  = row.get("description", "").strip() or None
        title = (desc[:100] if desc else None) or act_type_raw or "Activity"

        due_dt  = parse_date(row.get("activity_date", ""))
        created = parse_date(row.get("created_at", "")) or due_dt or datetime.utcnow()

        try:
            activity = Activity(
                company_id=company_id,
                type=act_type,
                title=title,
                description=desc,
                due_date=due_dt,
                done=False,
                created_at=created,
            )
            db.add(activity)
            inserted += 1
            if inserted % 1000 == 0:
                db.flush()
                print(f"  activities: {inserted} inserted...")
        except Exception as e:
            skipped += 1
            db.rollback()
            continue

    db.commit()
    print(f"  activities: {inserted} inserted, {skipped} skipped.\n")
    return inserted


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  Operational DB Population Script")
    print("=" * 55)
    print()

    truncate_tables()

    db = SessionLocal()
    try:
        print("Step 1/5 — Companies")
        company_lookup = load_companies(db)

        print("Step 2/5 — Contacts")
        n_contacts = load_contacts(db, company_lookup)

        print("Step 3/5 — Deals")
        n_deals = load_deals(db, company_lookup)

        print("Step 4/5 — Invoices")
        n_invoices = load_invoices(company_lookup)

        print("Step 5/5 — Activities (limit 50,000)")
        n_activities = load_activities(db, company_lookup)

    finally:
        db.close()

    print("=" * 55)
    print("  FINAL SUMMARY")
    print("=" * 55)
    print(f"  companies  : {len(company_lookup):>7,}")
    print(f"  contacts   : {n_contacts:>7,}")
    print(f"  deals      : {n_deals:>7,}")
    print(f"  invoices   : {n_invoices:>7,}")
    print(f"  activities : {n_activities:>7,}")
    print("=" * 55)


if __name__ == "__main__":
    main()
