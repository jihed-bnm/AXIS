"""
CRM Tools — MCP-style tools registered with the LangChain agent.
Each tool maps to a specific ERP operation.
READ tools execute directly.
WRITE tools return a preview string; execution requires confirmed=True.
"""
from langchain.tools import tool
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, text
from datetime import datetime, date
from typing import Optional

from backend.models.crm_models import Company, Contact, Deal, Activity, AuditLog
from backend.models.database import get_session, engine
from backend.utils.audit import log_action

DEFAULT_LIST_LIMIT = 50

# ─── READ TOOLS ──────────────────────────────────────────────────────────────

@tool
def get_total_won_deal_value(month: Optional[int] = None, year: Optional[int] = None) -> str:
    """Sum of monetary value of deals marked as 'won' in the CRM pipeline. This measures sales pipeline outcome, not collected revenue. Use this when the user asks about deal values, pipeline performance, or won business."""
    db = get_session()
    try:
        query = db.query(func.sum(Deal.value)).filter(Deal.status == "won", Deal.is_deleted == False)
        if month:
            query = query.filter(extract("month", Deal.closed_at) == month)
        if year:
            query = query.filter(extract("year", Deal.closed_at) == year)
        total = query.scalar() or 0
        period = f" for {month}/{year}" if month or year else " (all time)"
        return f"Total won deal value{period}: {total:,.2f} TND"
    finally:
        db.close()


@tool
def list_companies(status: Optional[str] = None, industry: Optional[str] = None) -> str:
    """List companies. Filter by status (prospect/client/inactive) or industry."""
    db = get_session()
    try:
        query = db.query(Company).filter(Company.is_deleted == False)
        if status:
            query = query.filter(Company.status == status)
        if industry:
            query = query.filter(Company.industry.ilike(f"%{industry}%"))
        total = query.count()
        companies = query.limit(DEFAULT_LIST_LIMIT).all()
        if not companies:
            return "No companies found."
        lines = []
        if total > DEFAULT_LIST_LIMIT:
            lines.append(f"Showing first {DEFAULT_LIST_LIMIT} of {total} results.")
        lines.append(f"Found {len(companies)} companies:")
        for c in companies:
            lines.append(f"  [{c.id}] {c.name} | {c.industry} | {c.city} | Status: {c.status}")
        return "\n".join(lines)
    finally:
        db.close()


@tool
def get_company(name: Optional[str] = None, company_id: Optional[int] = None) -> str:
    """Get details of a specific company by name or ID."""
    db = get_session()
    try:
        if company_id:
            company = db.query(Company).filter(Company.id == company_id).first()
        elif name:
            company = db.query(Company).filter(Company.name.ilike(f"%{name}%")).first()
        else:
            return "Please provide a company name or ID."
        if not company:
            return f"Company not found."
        contacts = db.query(Contact).filter(Contact.company_id == company.id).count()
        deals = db.query(Deal).filter(Deal.company_id == company.id, Deal.status == "open").count()
        return (
            f"Company: {company.name}\n"
            f"  ID: {company.id}\n"
            f"  Industry: {company.industry}\n"
            f"  Status: {company.status}\n"
            f"  City: {company.city}, {company.country}\n"
            f"  Phone: {company.phone}\n"
            f"  Email: {company.email}\n"
            f"  Website: {company.website}\n"
            f"  Contacts: {contacts} | Open deals: {deals}\n"
            f"  Created: {company.created_at.strftime('%Y-%m-%d') if company.created_at else 'N/A'}"
        )
    finally:
        db.close()


@tool
def list_deals(status: Optional[str] = None, company_name: Optional[str] = None, min_value: Optional[float] = None) -> str:
    """List deals. Filter by status (open/won/lost/on_hold), company name, or minimum value."""
    db = get_session()
    try:
        query = db.query(Deal).join(Company).filter(Deal.is_deleted == False)
        if status:
            query = query.filter(Deal.status == status)
        if company_name:
            query = query.filter(Company.name.ilike(f"%{company_name}%"))
        if min_value:
            query = query.filter(Deal.value >= min_value)
        total = query.count()
        deals = query.limit(DEFAULT_LIST_LIMIT).all()
        if not deals:
            return "No deals found."
        cids = {d.company_id for d in deals if d.company_id}
        companies_map = (
            {co.id: co for co in db.query(Company).filter(Company.id.in_(cids)).all()}
            if cids else {}
        )
        lines = []
        if total > DEFAULT_LIST_LIMIT:
            lines.append(f"Showing first {DEFAULT_LIST_LIMIT} of {total} results.")
        lines.append(f"Found {len(deals)} deals:")
        for d in deals:
            co = companies_map.get(d.company_id)
            lines.append(f"  [{d.id}] {d.title} | {co.name if co else '?'} | {d.value:,.0f} TND | {d.status.upper()} | Stage: {d.stage}")
        return "\n".join(lines)
    finally:
        db.close()


@tool
def get_deal(deal_id: Optional[int] = None, title: Optional[str] = None) -> str:
    """Get details of a specific deal by ID or title."""
    db = get_session()
    try:
        query = db.query(Deal).filter(Deal.is_deleted == False)
        if deal_id:
            deal = query.filter(Deal.id == deal_id).first()
        elif title:
            deal = query.filter(Deal.title.ilike(f'%{title}%')).first()
        else:
            return "Please provide a deal_id or title."

        if not deal:
            return f"Deal not found."

        company = db.query(Company).filter(Company.id == deal.company_id).first()
        return (
            f"Deal #{deal.id}: {deal.title}\n"
            f"Company: {company.name if company else 'Unknown'}\n"
            f"Value: {deal.value:,.0f} TND\n"
            f"Stage: {deal.stage}\n"
            f"Status: {deal.status}\n"
            f"Probability: {deal.probability}%\n"
            f"Created: {deal.created_at.date() if deal.created_at else 'N/A'}\n"
            f"Closed: {deal.closed_at.date() if deal.closed_at else 'N/A'}\n"
            f"Notes: {deal.notes or 'None'}"
        )
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        db.close()


@tool
def get_pipeline_summary() -> str:
    """Get a summary of the sales pipeline: count and total value by stage and status."""
    db = get_session()
    try:
        rows = db.query(Deal.status, func.count(Deal.id), func.sum(Deal.value)).filter(Deal.is_deleted == False).group_by(Deal.status).all()
        lines = ["=== Pipeline Summary ==="]
        for status, count, total in rows:
            lines.append(f"  {status.upper():10} : {count:3} deals | {(total or 0):>15,.0f} TND")
        return "\n".join(lines)
    finally:
        db.close()


@tool
def list_contacts(company_name: Optional[str] = None, company_id: Optional[int] = None, name: Optional[str] = None) -> str:
    """List contacts. Filter by company name, company ID, or contact name (first or last name)."""
    db = get_session()
    try:
        query = db.query(Contact).filter(Contact.is_deleted == False)
        if company_id:
            query = query.filter(Contact.company_id == company_id)
        elif company_name:
            company = db.query(Company).filter(Company.name.ilike(f"%{company_name}%")).first()
            if not company:
                return f"Company '{company_name}' not found."
            query = query.filter(Contact.company_id == company.id)
        if name:
            parts = name.strip().split()
            if len(parts) == 2:
                # "First Last" — match both columns
                query = query.filter(
                    Contact.first_name.ilike(f"%{parts[0]}%") &
                    Contact.last_name.ilike(f"%{parts[1]}%")
                )
            elif len(parts) > 2:
                # Compound name — OR on individual columns plus full-string match
                full = f"%{name}%"
                from sqlalchemy import func
                query = query.filter(
                    Contact.first_name.ilike(full) |
                    Contact.last_name.ilike(full) |
                    func.concat(Contact.first_name, ' ', Contact.last_name).ilike(full)
                )
            else:
                # Single token — match either column
                query = query.filter(
                    Contact.first_name.ilike(f"%{name}%") |
                    Contact.last_name.ilike(f"%{name}%")
                )
        total = query.count()
        contacts = query.limit(DEFAULT_LIST_LIMIT).all()
        if not contacts:
            return "No contacts found."
        cids = {c.company_id for c in contacts if c.company_id}
        companies_map = (
            {co.id: co for co in db.query(Company).filter(Company.id.in_(cids)).all()}
            if cids else {}
        )
        lines = []
        if total > DEFAULT_LIST_LIMIT:
            lines.append(f"Showing first {DEFAULT_LIST_LIMIT} of {total} results.")
        lines.append(f"Found {len(contacts)} contacts:")
        for c in contacts:
            co = companies_map.get(c.company_id)
            lines.append(f"  [{c.id}] {c.first_name} {c.last_name} | {c.role} | {co.name if co else '?'} | {c.email}")
        return "\n".join(lines)
    finally:
        db.close()


@tool
def list_activities(due_this_week: bool = False, done: Optional[bool] = None, company_name: Optional[str] = None) -> str:
    """List activities. Filter by due_this_week, done status, or company name."""
    db = get_session()
    try:
        query = db.query(Activity)
        if due_this_week:
            today = datetime.utcnow()
            week_end = today.replace(hour=23, minute=59) 
            from datetime import timedelta
            week_end = today + timedelta(days=7)
            query = query.filter(Activity.due_date >= today, Activity.due_date <= week_end)
        if done is not None:
            query = query.filter(Activity.done == done)
        if company_name:
            company = db.query(Company).filter(Company.name.ilike(f"%{company_name}%")).first()
            if company:
                query = query.filter(Activity.company_id == company.id)
        total = query.count()
        activities = query.order_by(Activity.due_date).limit(DEFAULT_LIST_LIMIT).all()
        if not activities:
            return "No activities found."
        cids = {a.company_id for a in activities if a.company_id}
        companies_map = (
            {co.id: co for co in db.query(Company).filter(Company.id.in_(cids)).all()}
            if cids else {}
        )
        lines = []
        if total > DEFAULT_LIST_LIMIT:
            lines.append(f"Showing first {DEFAULT_LIST_LIMIT} of {total} results.")
        lines.append(f"Found {len(activities)} activities:")
        for a in activities:
            co = companies_map.get(a.company_id)
            due_str = a.due_date.strftime("%Y-%m-%d") if a.due_date else "No date"
            done_str = "OK:" if a.done else "⏳"
            lines.append(f"  [{a.id}] {done_str} {a.type.upper()} | {a.title} | {co.name if co else '?'} | Due: {due_str}")
        return "\n".join(lines)
    finally:
        db.close()


# ─── WRITE TOOLS (require confirmed=True) ────────────────────────────────────

@tool
def create_company(name: str, industry: Optional[str] = None, city: Optional[str] = None,
                   email: Optional[str] = None, phone: Optional[str] = None, confirmed: bool = False) -> str:
    """
    Create a new company in the CRM.
    IMPORTANT: First call with confirmed=False to show a preview.
    Only call with confirmed=True after explicit user confirmation.
    """
    if not confirmed:
        return (
            f"WARNING: I am about to CREATE a new company:\n"
            f"  Name: {name}\n"
            f"  Industry: {industry or 'N/A'}\n"
            f"  City: {city or 'N/A'}\n"
            f"  Email: {email or 'N/A'}\n"
            f"  Phone: {phone or 'N/A'}\n\n"
            f"Please confirm: reply 'yes' or 'confirm' to proceed."
        )
    db = get_session()
    try:
        company = Company(name=name, industry=industry, city=city, email=email, phone=phone)
        db.add(company)
        db.commit()
        db.refresh(company)
        log_action(db, "CREATE", "company", company.id, {"name": name, "industry": industry}, "success")
        return f"OK: Company '{name}' created successfully with ID {company.id}."
    except Exception as e:
        db.rollback()
        return f"ERROR: Error creating company: {str(e)}"
    finally:
        db.close()


@tool
def update_company(
    company_id: int,
    name: Optional[str] = None,
    industry: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    status: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    website: Optional[str] = None,
    confirmed: bool = False,
) -> str:
    """Update fields of an existing company by ID. Requires confirmed=True to apply changes."""
    db = get_session()
    try:
        company = db.query(Company).filter(Company.id == company_id, Company.is_deleted == False).first()
        if not company:
            return f"Error: Company with ID {company_id} not found."

        changes = {}
        if name is not None:     changes['name'] = name
        if industry is not None: changes['industry'] = industry
        if city is not None:     changes['city'] = city
        if country is not None:  changes['country'] = country
        if status is not None:   changes['status'] = status
        if phone is not None:    changes['phone'] = phone
        if email is not None:    changes['email'] = email
        if website is not None:  changes['website'] = website

        if not changes:
            return "No changes specified."

        if not confirmed:
            changes_str = ", ".join(f"{k}: '{v}'" for k, v in changes.items())
            return f"WARNING: About to update Company #{company_id} '{company.name}': {changes_str}. Call again with confirmed=True to apply."

        for field, value in changes.items():
            setattr(company, field, value)
        db.commit()

        log_action(db, "UPDATE", "company", company_id, changes, "success")

        changes_str = ", ".join(f"{k} → '{v}'" for k, v in changes.items())
        return f"OK: Company #{company_id} '{company.name}' updated: {changes_str}."
    except Exception as e:
        db.rollback()
        return f"Error updating company: {str(e)}"
    finally:
        db.close()


@tool
def create_contact(first_name: str, last_name: str, company_name: Optional[str] = None,
                   role: Optional[str] = None, email: Optional[str] = None,
                   phone: Optional[str] = None, confirmed: bool = False) -> str:
    """
    Create a new contact linked to a company.
    Call with confirmed=False first for preview, then confirmed=True after user confirms.
    """
    if not company_name:
        return "Please provide a company name to create this contact. Which company does this contact belong to?"
    if not confirmed:
        return (
            f"WARNING: I am about to CREATE a new contact:\n"
            f"  Name: {first_name} {last_name}\n"
            f"  Company: {company_name}\n"
            f"  Role: {role or 'N/A'}\n"
            f"  Email: {email or 'N/A'}\n"
            f"  Phone: {phone or 'N/A'}\n\n"
            f"Please confirm: reply 'yes' or 'confirm' to proceed."
        )
    db = get_session()
    try:
        company = db.query(Company).filter(Company.name.ilike(f"%{company_name}%")).first()
        if not company:
            return f"ERROR: Company '{company_name}' not found. Please create the company first."
        contact = Contact(
            company_id=company.id, first_name=first_name, last_name=last_name,
            role=role, email=email, phone=phone
        )
        db.add(contact)
        db.commit()
        db.refresh(contact)
        log_action(db, "CREATE", "contact", contact.id, {"name": f"{first_name} {last_name}", "company": company_name}, "success")
        return f"OK: Contact '{first_name} {last_name}' created at '{company.name}' with ID {contact.id}."
    except Exception as e:
        db.rollback()
        return f"ERROR: Error: {str(e)}"
    finally:
        db.close()


@tool
def create_deal(company_name: str, title: str, value: float,
                stage: Optional[str] = "prospecting", confirmed: bool = False) -> str:
    """
    Create a new deal/opportunity.
    Call with confirmed=False first for preview, then confirmed=True after user confirms.
    IMPORTANT: This tool requires a company_name not a contact name — if the user provided a person's name instead, first call list_contacts(name=...) to find their company, then use that company name here.
    """
    if not confirmed:
        return (
            f"WARNING: I am about to CREATE a new deal:\n"
            f"  Title: {title}\n"
            f"  Company: {company_name}\n"
            f"  Value: {value:,.2f} TND\n"
            f"  Stage: {stage}\n\n"
            f"Please confirm: reply 'yes' or 'confirm' to proceed."
        )
    db = get_session()
    try:
        company = db.query(Company).filter(Company.name.ilike(f"%{company_name}%")).first()
        if not company:
            return f"ERROR: Company '{company_name}' not found."
        deal = Deal(company_id=company.id, title=title, value=value, stage=stage)
        db.add(deal)
        db.commit()
        db.refresh(deal)
        log_action(db, "CREATE", "deal", deal.id, {"title": title, "value": value, "company": company_name}, "success")
        return f"OK: Deal '{title}' created for '{company.name}' worth {value:,.2f} TND (ID: {deal.id})."
    except Exception as e:
        db.rollback()
        return f"ERROR: Error: {str(e)}"
    finally:
        db.close()


@tool
def update_deal_status(deal_id: int, new_status: str, confirmed: bool = False) -> str:
    """
    Update the status of a deal (open/won/lost/on_hold).
    Call with confirmed=False first for preview, then confirmed=True after user confirms.
    """
    db = get_session()
    try:
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if not deal:
            return f"ERROR: Deal #{deal_id} not found."
        if not confirmed:
            return (
                f"WARNING: I am about to UPDATE deal #{deal_id}:\n"
                f"  Title: {deal.title}\n"
                f"  Current status: {deal.status}\n"
                f"  New status: {new_status}\n\n"
                f"Please confirm: reply 'yes' or 'confirm' to proceed."
            )
        old_status = deal.status
        deal.status = new_status
        if new_status in ["won", "lost"]:
            deal.closed_at = datetime.utcnow()
        db.commit()
        log_action(db, "UPDATE", "deal", deal_id, {"from": old_status, "to": new_status}, "success")
        return f"OK: Deal #{deal_id} '{deal.title}' status updated: {old_status} → {new_status}."
    except Exception as e:
        db.rollback()
        return f"ERROR: Error: {str(e)}"
    finally:
        db.close()


@tool
def create_activity(company_name: str, title: str, activity_type: str,
                    due_date: Optional[str] = None, description: Optional[str] = None,
                    confirmed: bool = False) -> str:
    """
    Create a new activity (call/meeting/email/task/note).
    due_date format: YYYY-MM-DD.
    Call with confirmed=False first for preview, then confirmed=True after user confirms.
    """
    if not confirmed:
        return (
            f"WARNING: I am about to CREATE a new activity:\n"
            f"  Type: {activity_type}\n"
            f"  Title: {title}\n"
            f"  Company: {company_name}\n"
            f"  Due date: {due_date or 'Not set'}\n\n"
            f"Please confirm: reply 'yes' or 'confirm' to proceed."
        )
    db = get_session()
    try:
        company = db.query(Company).filter(Company.name.ilike(f"%{company_name}%")).first()
        if not company:
            return f"ERROR: Company '{company_name}' not found."
        parsed_due = datetime.strptime(due_date, "%Y-%m-%d") if due_date else None
        activity = Activity(
            company_id=company.id, type=activity_type, title=title,
            description=description, due_date=parsed_due
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)
        log_action(db, "CREATE", "activity", activity.id, {"type": activity_type, "title": title}, "success")
        return f"OK: Activity '{title}' ({activity_type}) created for '{company.name}' (ID: {activity.id})."
    except Exception as e:
        db.rollback()
        return f"ERROR: Error: {str(e)}"
    finally:
        db.close()


@tool
def delete_company(company_id: int, confirmed: bool = False) -> str:
    """
    Soft-delete a company by ID (sets is_deleted=True, record is preserved).
    Call with confirmed=False first for preview, then confirmed=True after user confirms.
    """
    db = get_session()
    try:
        company = db.query(Company).filter(Company.id == company_id, Company.is_deleted == False).first()
        if not company:
            return f"ERROR: Company #{company_id} not found."
        if not confirmed:
            return (
                f"WARNING: I am about to DELETE company #{company_id}:\n"
                f"  Name: {company.name}\n"
                f"  Industry: {company.industry or 'N/A'} | City: {company.city or 'N/A'}\n"
                f"  Status: {company.status}\n\n"
                f"Please confirm: reply 'yes' or 'confirm' to proceed."
            )
        company.is_deleted = True
        db.commit()
        log_action(db, "DELETE", "company", company_id, {"name": company.name}, "success")
        return f"OK: Company '{company.name}' (ID: {company_id}) has been deleted."
    except Exception as e:
        db.rollback()
        return f"ERROR: {str(e)}"
    finally:
        db.close()


@tool
def delete_contact(contact_id: int, confirmed: bool = False) -> str:
    """
    Soft-delete a contact by ID (sets is_deleted=True, record is preserved).
    Call with confirmed=False first for preview, then confirmed=True after user confirms.
    """
    db = get_session()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id, Contact.is_deleted == False).first()
        if not contact:
            return f"ERROR: Contact #{contact_id} not found."
        company = db.query(Company).filter(Company.id == contact.company_id).first()
        if not confirmed:
            return (
                f"WARNING: I am about to DELETE contact #{contact_id}:\n"
                f"  Name: {contact.first_name} {contact.last_name}\n"
                f"  Role: {contact.role or 'N/A'} | Company: {company.name if company else 'N/A'}\n\n"
                f"Please confirm: reply 'yes' or 'confirm' to proceed."
            )
        contact.is_deleted = True
        db.commit()
        log_action(db, "DELETE", "contact", contact_id, {"name": f"{contact.first_name} {contact.last_name}"}, "success")
        return f"OK: Contact '{contact.first_name} {contact.last_name}' (ID: {contact_id}) has been deleted."
    except Exception as e:
        db.rollback()
        return f"ERROR: {str(e)}"
    finally:
        db.close()


@tool
def delete_deal(deal_id: int, confirmed: bool = False) -> str:
    """
    Soft-delete a deal by ID (sets is_deleted=True, record is preserved).
    Call with confirmed=False first for preview, then confirmed=True after user confirms.
    """
    db = get_session()
    try:
        deal = db.query(Deal).filter(Deal.id == deal_id, Deal.is_deleted == False).first()
        if not deal:
            return f"ERROR: Deal #{deal_id} not found."
        company = db.query(Company).filter(Company.id == deal.company_id).first()
        if not confirmed:
            return (
                f"WARNING: I am about to DELETE deal #{deal_id}:\n"
                f"  Title: {deal.title}\n"
                f"  Company: {company.name if company else 'N/A'} | Value: {deal.value:,.0f} TND\n"
                f"  Status: {deal.status} | Stage: {deal.stage}\n\n"
                f"Please confirm: reply 'yes' or 'confirm' to proceed."
            )
        deal.is_deleted = True
        db.commit()
        log_action(db, "DELETE", "deal", deal_id, {"title": deal.title, "value": deal.value}, "success")
        return f"OK: Deal '{deal.title}' (ID: {deal_id}) has been deleted."
    except Exception as e:
        db.rollback()
        return f"ERROR: {str(e)}"
    finally:
        db.close()


@tool
def update_contact(
    contact_id: int,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    role: Optional[str] = None,
    is_primary: Optional[bool] = None,
    confirmed: bool = False,
) -> str:
    """Update fields of an existing contact by ID. Requires confirmed=True to apply."""
    db = get_session()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id, Contact.is_deleted == False).first()
        if not contact:
            return f"Error: Contact with ID {contact_id} not found."

        changes = {}
        if first_name is not None: changes['first_name'] = first_name
        if last_name is not None:  changes['last_name'] = last_name
        if email is not None:      changes['email'] = email
        if phone is not None:      changes['phone'] = phone
        if role is not None:       changes['role'] = role
        if is_primary is not None: changes['is_primary'] = is_primary

        if not changes:
            return "No changes specified."

        if not confirmed:
            changes_str = ", ".join(f"{k}: '{v}'" for k, v in changes.items())
            return (
                f"WARNING: About to update Contact #{contact_id} '{contact.first_name} {contact.last_name}': "
                f"{changes_str}. Call again with confirmed=True to apply."
            )

        for field, value in changes.items():
            setattr(contact, field, value)
        db.commit()

        log_action(db, "UPDATE", "contact", contact_id, changes, "success")

        changes_str = ", ".join(f"{k} → '{v}'" for k, v in changes.items())
        return f"OK: Contact #{contact_id} '{contact.first_name} {contact.last_name}' updated: {changes_str}."
    except Exception as e:
        db.rollback()
        return f"Error updating contact: {str(e)}"
    finally:
        db.close()


@tool
def update_deal(
    deal_id: int,
    title: Optional[str] = None,
    value: Optional[float] = None,
    stage: Optional[str] = None,
    probability: Optional[int] = None,
    notes: Optional[str] = None,
    assigned_to_id: Optional[int] = None,
    confirmed: bool = False,
) -> str:
    """Update fields of an existing deal by ID. Requires confirmed=True to apply.
    Valid stages: prospecting, qualification, proposal, negotiation, closed."""
    db = get_session()
    try:
        deal = db.query(Deal).filter(Deal.id == deal_id, Deal.is_deleted == False).first()
        if not deal:
            return f"Error: Deal with ID {deal_id} not found."

        VALID_STAGES = {"prospecting", "qualification", "proposal", "negotiation", "closed"}
        if stage and stage not in VALID_STAGES:
            return f"Error: Invalid stage '{stage}'. Valid stages: {', '.join(sorted(VALID_STAGES))}."

        changes = {}
        if title is not None:       changes['title'] = title
        if value is not None:       changes['value'] = value
        if stage is not None:       changes['stage'] = stage
        if probability is not None: changes['probability'] = probability
        if notes is not None:       changes['notes'] = notes

        if not changes:
            return "No changes specified."

        if not confirmed:
            changes_str = ", ".join(f"{k}: '{v}'" for k, v in changes.items())
            return (
                f"WARNING: About to update Deal #{deal_id} '{deal.title}': {changes_str}. "
                f"Call again with confirmed=True to apply."
            )

        for field, val in changes.items():
            setattr(deal, field, val)
        db.commit()

        log_action(db, "UPDATE", "deal", deal_id, changes, "success")

        changes_str = ", ".join(f"{k} → '{v}'" for k, v in changes.items())
        return f"OK: Deal #{deal_id} '{deal.title}' updated: {changes_str}."
    except Exception as e:
        db.rollback()
        return f"Error updating deal: {str(e)}"
    finally:
        db.close()


@tool
def mark_activity_done(activity_id: int, confirmed: bool = False) -> str:
    """Mark an activity as completed. Requires confirmed=True to apply."""
    db = get_session()
    try:
        activity = db.query(Activity).filter(Activity.id == activity_id).first()
        if not activity:
            return f"Error: Activity with ID {activity_id} not found."
        if activity.done:
            return f"Activity #{activity_id} '{activity.title}' is already marked as done."

        if not confirmed:
            due_str = activity.due_date.strftime("%Y-%m-%d") if activity.due_date else "No date"
            return (
                f"WARNING: About to mark Activity #{activity_id} as done:\n"
                f"  Title: {activity.title}\n"
                f"  Type: {activity.type} | Due: {due_str}\n\n"
                f"Call again with confirmed=True to apply."
            )

        activity.done = True
        activity.done_at = datetime.utcnow()
        db.commit()

        log_action(db, "UPDATE", "activity", activity_id, {"done": True}, "success")
        return f"OK: Activity #{activity_id} '{activity.title}' marked as done."
    except Exception as e:
        db.rollback()
        return f"Error marking activity done: {str(e)}"
    finally:
        db.close()


@tool
def get_at_risk_clients() -> str:
    """Return list of companies with churn signals based on recent CRM activity descriptions."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT
                    company_name,
                    COUNT(*) AS churn_signals,
                    MAX(activity_date) AS last_churn_date,
                    MAX(description) AS last_description
                FROM warehouse.fact_activities
                WHERE churn_signal = TRUE
                  AND company_name IS NOT NULL
                GROUP BY company_name
                ORDER BY churn_signals DESC
                LIMIT 10
            """)).fetchall()

        if not rows:
            return "No at-risk clients detected based on current activity data."

        lines = [f"At-Risk Clients (top {len(rows)} by churn signals):"]
        for i, row in enumerate(rows, 1):
            last_date = str(row[2])[:10] if row[2] else "N/A"
            desc = (str(row[3])[:80] + "...") if row[3] and len(str(row[3])) > 80 else (row[3] or "N/A")
            lines.append(
                f"  {i}. {row[0]} — {row[1]} signal(s) | Last: {last_date}\n"
                f"     Recent: {desc}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving at-risk clients: {str(e)}"


@tool
def predict_churn(company_name: str) -> str:
    """Predict the churn risk for a specific client company.
    Returns the churn probability, risk level (High/Medium/Low), and the top contributing factors.
    Use when user asks about churn risk, client health, at-risk clients, or retention priorities."""
    from backend.ml.predictor import predict_company_churn
    try:
        result = predict_company_churn(company_name)
        lines = [
            f"=== Churn Prediction for {result['company']} ===",
            f"Risk Level: {result['risk_level']}",
            f"Churn Probability: {result['churn_probability']:.1%}",
            "",
            "Top Contributing Factors:",
        ]
        for factor in result['top_factors']:
            lines.append(f"  - {factor['feature']}: {factor['value']:.2f} (impact: {factor['importance']:.3f})")
        return "\n".join(lines)
    except Exception as e:
        return f"Could not predict churn for '{company_name}': {str(e)}"


@tool
def predict_deal_win(deal_id: int) -> str:
    """Predict whether a specific deal will be won or lost based on its features and company history.
    Returns win probability, predicted outcome (Likely Win/Uncertain/Likely Loss), and top contributing factors.
    Use when user asks about deal chances, deal prediction, win probability, or deal outcome."""
    from backend.ml.deal_predictor import predict_deal_outcome
    try:
        result = predict_deal_outcome(deal_id)
        lines = [
            f"=== Deal Win Prediction ===",
            f"Deal: {result['deal_title']} (ID: {result['deal_id']})",
            f"Company: {result['company']}",
            f"Prediction: {result['outcome_prediction']}",
            f"Win Probability: {result['win_probability']:.1%}",
            "",
            "Top Contributing Factors:",
        ]
        for factor in result['top_factors']:
            lines.append(f"  - {factor['feature']}: {factor['value']:.2f} (impact: {factor['importance']:.3f})")
        return "\n".join(lines)
    except Exception as e:
        return f"Could not predict outcome for deal {deal_id}: {str(e)}"


# All tools list — imported by the agent
ALL_CRM_TOOLS = [
    get_total_won_deal_value,
    list_companies,
    get_company,
    list_deals,
    get_deal,
    get_pipeline_summary,
    list_contacts,
    list_activities,
    create_company,
    create_contact,
    create_deal,
    update_company,
    update_contact,
    update_deal,
    update_deal_status,
    mark_activity_done,
    create_activity,
    get_at_risk_clients,
    predict_churn,
    predict_deal_win,
    delete_company,
    delete_contact,
    delete_deal,
]
