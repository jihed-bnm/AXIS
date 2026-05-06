"""
Invoicing & Payments Tools — MCP-style tools for the Invoicing module.
"""
from langchain.tools import tool
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, text
from datetime import datetime, date, timedelta
from typing import Optional, List

from backend.models.invoice_models import Invoice, InvoiceItem, Payment
from backend.models.crm_models import Company, AuditLog
from backend.models.database import get_session, engine
from backend.utils.audit import log_action


def generate_invoice_number(db) -> str:
    year = datetime.utcnow().year
    count = db.query(Invoice).filter(extract("year", Invoice.created_at) == year).count()
    return f"INV-{year}-{str(count + 1).zfill(4)}"


# ─── READ TOOLS ──────────────────────────────────────────────────────────────

@tool
def list_invoices(status: Optional[str] = None, company_name: Optional[str] = None) -> str:
    """List invoices filtered by status (draft/sent/paid/overdue/cancelled) or company name."""
    db = get_session()
    try:
        query = db.query(Invoice).filter(Invoice.is_deleted == False)
        if status:
            query = query.filter(Invoice.status == status)
        if company_name:
            company = db.query(Company).filter(Company.name.ilike(f"%{company_name}%")).first()
            if company:
                query = query.filter(Invoice.company_id == company.id)
        total = query.count()
        invoices = query.order_by(Invoice.created_at.desc()).limit(50).all()
        if not invoices:
            return "No invoices found."
        rows = [
            f"Showing {len(invoices)} of {total} results:",
            "| ID | Invoice # | Company | Status | Total (TND) | Due Date |",
            "|---|---|---|---|---|---|",
        ]
        for inv in invoices:
            company = db.query(Company).filter(Company.id == inv.company_id).first()
            rows.append(f"| {inv.id} | {inv.invoice_number} | {company.name if company else '?'} | {inv.status.upper()} | {inv.total:,.0f} | {inv.due_date or 'N/A'} |")
        return "\n".join(rows)
    finally:
        db.close()


@tool
def get_invoice(invoice_number: Optional[str] = None, invoice_id: Optional[int] = None) -> str:
    """Get full details of an invoice including line items."""
    db = get_session()
    try:
        if invoice_id:
            inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        elif invoice_number:
            inv = db.query(Invoice).filter(Invoice.invoice_number == invoice_number).first()
        else:
            return "Please provide an invoice number or ID."
        if not inv:
            return "Invoice not found."
        company = db.query(Company).filter(Company.id == inv.company_id).first()
        items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == inv.id).all()
        lines = [
            f"Invoice: {inv.invoice_number}",
            f"  Client: {company.name if company else 'N/A'}",
            f"  Status: {inv.status} | Issue: {inv.issue_date} | Due: {inv.due_date}",
            f"  Items:"
        ]
        for item in items:
            lines.append(f"    - {item.description}: {item.quantity} x {item.unit_price:,.0f} = {item.total:,.0f} TND")
        lines.append(f"  Subtotal: {inv.subtotal:,.0f} TND")
        lines.append(f"  TVA ({inv.tax_rate}%): {inv.tax_amount:,.0f} TND")
        lines.append(f"  TOTAL: {inv.total:,.0f} TND")
        return "\n".join(lines)
    finally:
        db.close()


@tool
def get_revenue_summary(month: Optional[int] = None, year: Optional[int] = None, quarter: Optional[int] = None) -> str:
    """Sum of paid invoice totals. This measures collected revenue (money received), not deal pipeline value. Use this when the user asks about revenue, cash collected, or invoicing performance."""
    db = get_session()
    try:
        query = db.query(func.sum(Invoice.total)).filter(Invoice.status == "paid")
        if quarter:
            start_m = (quarter - 1) * 3 + 1
            query = query.filter(extract("month", Invoice.paid_at).between(start_m, start_m + 2))
            if year:
                query = query.filter(extract("year", Invoice.paid_at) == year)
        else:
            if month:
                query = query.filter(extract("month", Invoice.paid_at) == month)
            if year:
                query = query.filter(extract("year", Invoice.paid_at) == year)
        total = query.scalar() or 0
        pending = db.query(func.sum(Invoice.total)).filter(Invoice.status.in_(["sent", "draft"])).scalar() or 0
        overdue = db.query(func.sum(Invoice.total)).filter(Invoice.status == "overdue").scalar() or 0
        if quarter and year:
            period = f" for Q{quarter} {year}"
        elif quarter:
            period = f" for Q{quarter}"
        elif month and year:
            period = f" for {month}/{year}"
        elif year:
            period = f" for {year}"
        elif month:
            period = f" for month {month}"
        else:
            period = " (all time)"
        return (
            f"Revenue summary{period}:\n"
            f"  Collected (paid):  {total:>15,.0f} TND\n"
            f"  Pending (sent):    {pending:>15,.0f} TND\n"
            f"  Overdue:           {overdue:>15,.0f} TND"
        )
    finally:
        db.close()


# ─── WRITE TOOLS ─────────────────────────────────────────────────────────────

@tool
def create_invoice(company_name: str, items_description: str,
                   project_name: Optional[str] = None,
                   due_days: int = 30, confirmed: bool = False) -> str:
    """
    Create an invoice for a company.
    items_description: comma-separated list in format 'description:quantity:unit_price'
    Example: 'Développement web:1:500000,Support technique:5:50000'
    Call with confirmed=False first for preview, then confirmed=True after user confirms.
    """
    # Parse items
    items = []
    subtotal = 0.0
    try:
        for item_str in items_description.split(","):
            # rsplit with maxsplit=2 so descriptions containing colons are preserved
            parts = item_str.strip().rsplit(":", 2)
            desc = parts[0].strip()
            qty = float(parts[1].strip()) if len(parts) > 1 else 1.0
            price = float(parts[2].strip()) if len(parts) > 2 else 0.0
            total = qty * price
            subtotal += total
            items.append({"description": desc, "quantity": qty, "unit_price": price, "total": total})
    except Exception:
        return "ERROR: Could not parse items. Use format: 'description:quantity:unit_price,...'"

    tax_rate = 19.0
    tax_amount = subtotal * tax_rate / 100
    grand_total = subtotal + tax_amount

    if not confirmed:
        lines = [f"WARNING: I am about to CREATE an invoice:\n  Client: {company_name}"]
        if project_name:
            lines.append(f"  Project: {project_name}")
        lines.append(f"  Items:")
        for it in items:
            lines.append(f"    - {it['description']}: {it['quantity']} x {it['unit_price']:,.0f} = {it['total']:,.0f} TND")
        lines.append(f"  Subtotal: {subtotal:,.0f} | TVA 19%: {tax_amount:,.0f} | TOTAL: {grand_total:,.0f} TND")
        lines.append(f"  Due in: {due_days} days\n\nPlease confirm: reply 'yes' or 'confirm' to proceed.")
        return "\n".join(lines)

    db = get_session()
    try:
        company = db.query(Company).filter(Company.name.ilike(f"%{company_name}%")).first()
        if not company:
            return f"ERROR: Company '{company_name}' not found."
        today = datetime.utcnow().date()
        inv = Invoice(
            invoice_number=generate_invoice_number(db),
            company_id=company.id,
            subtotal=subtotal,
            tax_rate=tax_rate,
            tax_amount=tax_amount,
            total=grand_total,
            issue_date=today,
            due_date=today + timedelta(days=due_days),
            status="draft"
        )
        db.add(inv)
        db.flush()
        for it in items:
            db.add(InvoiceItem(invoice_id=inv.id, **it))
        db.commit()
        log_action(db, "CREATE", "invoice", inv.id, {"company": company_name, "total": grand_total}, "success")
        return f"OK: Invoice {inv.invoice_number} created for '{company.name}' — Total: {grand_total:,.0f} TND (ID: {inv.id})."
    except Exception as e:
        db.rollback()
        return f"ERROR: Error: {str(e)}"
    finally:
        db.close()


@tool
def mark_invoice_paid(invoice_number: str, payment_method: Optional[str] = "bank_transfer",
                      confirmed: bool = False) -> str:
    """
    Mark an invoice as paid.
    Call with confirmed=False first for preview, then confirmed=True after user confirms.
    """
    db = get_session()
    try:
        inv = db.query(Invoice).filter(Invoice.invoice_number == invoice_number).first()
        if not inv:
            return f"ERROR: Invoice '{invoice_number}' not found."
        if not confirmed:
            return (
                f"WARNING: I am about to MARK as PAID:\n"
                f"  Invoice: {inv.invoice_number}\n"
                f"  Amount: {inv.total:,.0f} TND\n"
                f"  Method: {payment_method}\n\n"
                f"Please confirm: reply 'yes' or 'confirm' to proceed."
            )
        now = datetime.utcnow()
        inv.status = "paid"
        inv.paid_at = now
        payment = Payment(
            invoice_id=inv.id,
            amount=inv.total,
            method=payment_method,
            paid_at=now,
        )
        db.add(payment)
        log_action(db, "UPDATE", "invoice", inv.id, {"action": "paid", "method": payment_method}, "success")
        db.commit()
        return f"OK: Invoice {inv.invoice_number} marked as paid ({inv.total:,.0f} TND via {payment_method})."
    except Exception as e:
        db.rollback()
        return f"ERROR: {str(e)}"
    finally:
        db.close()


@tool
def send_invoice(invoice_number: str, confirmed: bool = False) -> str:
    """
    Mark an invoice as sent (to the client).
    Call with confirmed=False first for preview, then confirmed=True after user confirms.
    """
    db = get_session()
    try:
        inv = db.query(Invoice).filter(Invoice.invoice_number == invoice_number).first()
        if not inv:
            return f"ERROR: Invoice '{invoice_number}' not found."
        if not confirmed:
            company = db.query(Company).filter(Company.id == inv.company_id).first()
            return (
                f"WARNING: I am about to mark invoice {inv.invoice_number} as SENT to {company.name if company else '?'}\n"
                f"  Total: {inv.total:,.0f} TND | Due: {inv.due_date}\n\n"
                f"Please confirm: reply 'yes' or 'confirm' to proceed."
            )
        inv.status = "sent"
        db.commit()
        return f"OK: Invoice {inv.invoice_number} marked as sent."
    except Exception as e:
        db.rollback()
        return f"ERROR: Error: {str(e)}"
    finally:
        db.close()


@tool
def delete_invoice(invoice_id: int, confirmed: bool = False) -> str:
    """
    Soft-delete an invoice by ID (sets is_deleted=True, record is preserved).
    Call with confirmed=False first for preview, then confirmed=True after user confirms.
    """
    db = get_session()
    try:
        inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.is_deleted == False).first()
        if not inv:
            return f"ERROR: Invoice #{invoice_id} not found."
        company = db.query(Company).filter(Company.id == inv.company_id).first()
        if not confirmed:
            return (
                f"WARNING: I am about to DELETE invoice #{invoice_id}:\n"
                f"  Number: {inv.invoice_number}\n"
                f"  Client: {company.name if company else 'N/A'} | Total: {inv.total:,.0f} TND\n"
                f"  Status: {inv.status} | Due: {inv.due_date or 'N/A'}\n\n"
                f"Please confirm: reply 'yes' or 'confirm' to proceed."
            )
        inv.is_deleted = True
        db.commit()
        log_action(db, "DELETE", "invoice", invoice_id, {"invoice_number": inv.invoice_number, "total": inv.total}, "success")
        return f"OK: Invoice '{inv.invoice_number}' (ID: {invoice_id}) has been deleted."
    except Exception as e:
        db.rollback()
        return f"ERROR: {str(e)}"
    finally:
        db.close()


@tool
def get_overdue_invoices() -> str:
    """Return all overdue invoices with days outstanding, sorted by most overdue first."""
    db = get_session()
    try:
        today = date.today()
        invoices = (
            db.query(Invoice)
            .filter(
                Invoice.is_deleted == False,
                Invoice.status.notin_(["paid", "cancelled"]),
                Invoice.due_date < today,
            )
            .order_by(Invoice.due_date.asc())
            .all()
        )
        # Also include explicitly marked overdue
        explicit_overdue = (
            db.query(Invoice)
            .filter(Invoice.is_deleted == False, Invoice.status == "overdue")
            .all()
        )
        # Merge, deduplicate by ID
        seen = set()
        combined = []
        for inv in list(invoices) + list(explicit_overdue):
            if inv.id not in seen:
                seen.add(inv.id)
                combined.append(inv)
        combined.sort(key=lambda i: i.due_date or today)

        if not combined:
            return "No overdue invoices found."

        lines = [f"Overdue Invoices ({len(combined)} total):"]
        for inv in combined:
            company = db.query(Company).filter(Company.id == inv.company_id).first()
            days_overdue = (today - inv.due_date).days if inv.due_date else "?"
            lines.append(
                f"  {inv.invoice_number} | {company.name if company else '?'} | "
                f"{inv.total:,.0f} TND | Due: {inv.due_date} | {days_overdue} days overdue"
            )
        return "\n".join(lines)
    finally:
        db.close()


@tool
def get_client_balance(company_name: str) -> str:
    """Return total outstanding balance for a specific client, broken down by invoice status."""
    db = get_session()
    try:
        company = db.query(Company).filter(Company.name.ilike(f"%{company_name}%")).first()
        if not company:
            return f"Error: Company '{company_name}' not found."

        unpaid = (
            db.query(Invoice)
            .filter(
                Invoice.company_id == company.id,
                Invoice.is_deleted == False,
                Invoice.status.notin_(["paid", "cancelled"]),
            )
            .order_by(Invoice.issue_date.asc())
            .all()
        )

        if not unpaid:
            return f"{company.name} has no outstanding invoices."

        by_status: dict = {}
        for inv in unpaid:
            by_status.setdefault(inv.status, 0.0)
            by_status[inv.status] += inv.total or 0.0

        total_outstanding = sum(by_status.values())
        oldest = unpaid[0].issue_date

        lines = [f"Outstanding balance for {company.name}:"]
        for status, amount in sorted(by_status.items()):
            lines.append(f"  {status.capitalize():10}: {amount:>15,.0f} TND")
        lines.append(f"  {'TOTAL':10}: {total_outstanding:>15,.0f} TND")
        lines.append(f"  Oldest unpaid invoice: {oldest}")
        return "\n".join(lines)
    finally:
        db.close()


@tool
def cancel_invoice(invoice_number: str, confirmed: bool = False) -> str:
    """Cancel an invoice by setting its status to cancelled. Cannot cancel paid invoices."""
    db = get_session()
    try:
        inv = db.query(Invoice).filter(
            Invoice.invoice_number == invoice_number,
            Invoice.is_deleted == False,
        ).first()
        if not inv:
            return f"Error: Invoice '{invoice_number}' not found."
        if inv.status == "paid":
            return f"Error: Invoice '{invoice_number}' is already paid and cannot be cancelled."
        if inv.status == "cancelled":
            return f"Invoice '{invoice_number}' is already cancelled."

        if not confirmed:
            company = db.query(Company).filter(Company.id == inv.company_id).first()
            company_name = company.name if company else "N/A"
            return (
                f"WARNING: About to CANCEL invoice {inv.invoice_number}:\n"
                f"  Client: {company_name}\n"
                f"  Total: {inv.total:,.0f} TND | Status: {inv.status}\n\n"
                f"Call again with confirmed=True to apply."
            )

        inv.status = "cancelled"
        log_action(db, "UPDATE", "invoice", inv.id, {"action": "cancelled"}, "success")
        db.commit()
        return f"OK: Invoice {inv.invoice_number} has been cancelled."
    except Exception as e:
        db.rollback()
        return f"Error cancelling invoice: {str(e)}"
    finally:
        db.close()


@tool
def update_invoice(
    invoice_number: str,
    due_date: Optional[str] = None,
    notes: Optional[str] = None,
    confirmed: bool = False,
) -> str:
    """Update due date or notes on a draft or sent invoice. Cannot update paid or cancelled invoices."""
    db = get_session()
    try:
        inv = db.query(Invoice).filter(
            Invoice.invoice_number == invoice_number,
            Invoice.is_deleted == False,
        ).first()
        if not inv:
            return f"Error: Invoice '{invoice_number}' not found."
        if inv.status in ("paid", "cancelled"):
            return f"Error: Cannot update a {inv.status} invoice."

        changes = {}
        parsed_due = None
        if due_date is not None:
            try:
                parsed_due = datetime.strptime(due_date, "%Y-%m-%d").date()
                changes['due_date'] = due_date
            except ValueError:
                return "Error: due_date must be in YYYY-MM-DD format."
        if notes is not None:
            changes['notes'] = notes

        if not changes:
            return "No changes specified."

        if not confirmed:
            changes_str = ", ".join(f"{k}: '{v}'" for k, v in changes.items())
            return (
                f"WARNING: About to update Invoice {inv.invoice_number}: {changes_str}. "
                f"Call again with confirmed=True to apply."
            )

        if parsed_due is not None:
            inv.due_date = parsed_due
        if notes is not None:
            inv.notes = notes

        log_action(db, "UPDATE", "invoice", inv.id, changes, "success")
        db.commit()

        changes_str = ", ".join(f"{k} → '{v}'" for k, v in changes.items())
        return f"OK: Invoice {inv.invoice_number} updated: {changes_str}."
    except Exception as e:
        db.rollback()
        return f"Error updating invoice: {str(e)}"
    finally:
        db.close()


ALL_INVOICE_TOOLS = [
    list_invoices,
    get_invoice,
    get_revenue_summary,
    get_overdue_invoices,
    get_client_balance,
    create_invoice,
    mark_invoice_paid,
    send_invoice,
    cancel_invoice,
    update_invoice,
    delete_invoice,
]
