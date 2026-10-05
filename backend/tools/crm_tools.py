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
    """Sum the total value of all deals marked as 'won' in the CRM pipeline, optionally filtered by month and/or year.

    Use this tool when the user asks things like:
    - "what is our total won deal value?"
    - "how much pipeline value have we closed this year?"
    - "what business did we win in March?"
    - "how much have we booked so far?"

    Do NOT use this tool when: the user asks about revenue, cash collected, or payments received — use get_revenue_summary (Invoicing module) instead. Won deal value measures pipeline outcomes (booked business); get_revenue_summary measures money actually received from paid invoices.

    Parameters:
    - month (int, optional): filter by the month deals were closed (1–12). Defaults to all months.
    - year (int, optional): filter by the year deals were closed (e.g. 2025). Defaults to all years.
    """
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
    """List all companies in the CRM, optionally filtered by status or industry.

    Use this tool when the user asks things like:
    - "show me all our clients"
    - "list all prospect companies"
    - "which companies are inactive?"
    - "what companies do we have in the software industry?"

    Do NOT use this tool when: the user asks about a specific company by name or ID — use get_company instead. Do NOT use when the user asks about contacts or deals linked to a company — use list_contacts or list_deals with a company_name filter.

    Parameters:
    - status (str, optional): filter by company status. Valid values: 'prospect', 'client', 'inactive'. Defaults to all statuses.
    - industry (str, optional): filter by industry keyword (partial match, case-insensitive). Defaults to all industries.
    """
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
        rows = [
            f"Showing {len(companies)} of {total} results:",
            "| ID | Name | Industry | City | Status |",
            "|---|---|---|---|---|",
        ]
        for c in companies:
            rows.append(f"| {c.id} | {c.name} | {c.industry or '—'} | {c.city or '—'} | {c.status} |")
        return "\n".join(rows)
    finally:
        db.close()


@tool
def get_company(name: Optional[str] = None, company_id: Optional[int] = None) -> str:
    """Get full details of a specific company by name or ID.

    Use this tool when the user asks things like:
    - "tell me about BNA"
    - "what do we know about Acme Corp?"
    - "show me company details for ID 7"
    - "look up Startup XYZ in the CRM"

    Do NOT use this tool when: the user wants a list of multiple companies — use list_companies instead. If this tool returns 'not found', report that result directly — do NOT substitute another company or guess.

    Parameters:
    - name (str, optional): company name to search (partial match, case-insensitive). Provide either name or company_id, not both.
    - company_id (int, optional): exact company ID to look up. Takes precedence over name if both are provided.
    """
    db = get_session()
    try:
        if company_id:
            company = db.query(Company).filter(
                Company.id == company_id, Company.is_deleted == False
            ).first()
        elif name:
            company = db.query(Company).filter(
                Company.name.ilike(f"%{name}%"), Company.is_deleted == False
            ).first()
        else:
            return "Please provide a company name or ID."
        if not company:
            lookup = name or str(company_id)
            return f"Company '{lookup}' not found."
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
    """List deals in the CRM pipeline, optionally filtered by status, company, or minimum value.

    Use this tool when the user asks things like:
    - "show me all open deals"
    - "what deals do we have with Acme Corp?"
    - "list all won deals"
    - "which deals are on hold?"

    Do NOT use this tool when: the user asks about a specific deal by ID or title — use get_deal instead. For pipeline counts and totals by stage, use get_pipeline_summary. For the total monetary value of won deals, use get_total_won_deal_value.

    Note: this tool does not support date-range filtering; it filters by status, company, and minimum value only.

    Parameters:
    - status (str, optional): filter by deal status. Valid values: 'open', 'won', 'lost', 'on_hold'. Defaults to all statuses.
    - company_name (str, optional): filter by company name (partial match). Defaults to all companies.
    - min_value (float, optional): only return deals worth at least this amount in TND. Defaults to no minimum.
    """
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
        rows = [
            f"Showing {len(deals)} of {total} results:",
            "| ID | Title | Company | Value (TND) | Status | Stage |",
            "|---|---|---|---|---|---|",
        ]
        for d in deals:
            co = companies_map.get(d.company_id)
            rows.append(f"| {d.id} | {d.title} | {co.name if co else '?'} | {d.value:,.0f} | {d.status.upper()} | {d.stage} |")
        return "\n".join(rows)
    finally:
        db.close()


@tool
def get_deal(deal_id: Optional[int] = None, title: Optional[str] = None) -> str:
    """Get full details of a specific deal by its integer ID or a keyword in its title.

    Use this tool when the user asks things like:
    - "show me deal #42"
    - "what's the status of the Acme ERP deal?"
    - "give me details on deal ID 15"
    - "look up the Microsoft migration opportunity"

    Do NOT use this tool when: the user wants a list of deals — use list_deals instead. For pipeline-level counts and totals, use get_pipeline_summary.

    Parameters:
    - deal_id (int, optional): exact deal ID. Provide either deal_id or title, not both.
    - title (str, optional): keyword to search in the deal title (partial match, case-insensitive).
    """
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
    """Return deal counts and total TND value grouped by outcome status (open / won / lost / on_hold).

    Use this tool when the user asks things like:
    - "what does our pipeline look like?"
    - "how are our deals distributed?"
    - "give me a pipeline overview"
    - "deal breakdown by stage"
    - "how many deals are open vs won?"

    Do NOT use this tool when: the user wants the actual list of individual deals — use list_deals instead. For the specific monetary total of won deals only, use get_total_won_deal_value.

    Parameters: none.
    """
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
    """List CRM contacts, optionally filtered by company or contact name.

    Use this tool when the user asks things like:
    - "show me all contacts"
    - "who are the contacts at Acme Corp?"
    - "find contact Ahmed"
    - "list everyone we know at BNA"

    Do NOT use this tool when: the user asks about a specific company's overall profile — use get_company instead. When the user says 'find contact [name]', call this tool with the name parameter; do NOT ask for a company name first.

    Parameters:
    - company_name (str, optional): filter contacts by associated company (partial match). Defaults to all companies.
    - company_id (int, optional): filter contacts by exact company ID. Takes precedence over company_name if both are provided.
    - name (str, optional): search by contact first or last name (partial match). Single token matches either column; 'First Last' format matches both.
    """
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
        rows = [
            f"Showing {len(contacts)} of {total} results:",
            "| ID | First Name | Last Name | Role | Company | Email |",
            "|---|---|---|---|---|---|",
        ]
        for c in contacts:
            co = companies_map.get(c.company_id)
            rows.append(f"| {c.id} | {c.first_name} | {c.last_name} | {c.role or '—'} | {co.name if co else '?'} | {c.email or '—'} |")
        return "\n".join(rows)
    finally:
        db.close()


@tool
def list_activities(due_this_week: bool = False, done: Optional[bool] = None, company_name: Optional[str] = None) -> str:
    """List CRM activities (calls, meetings, emails, tasks, notes), with optional filters.

    Use this tool when the user asks things like:
    - "show me all activities"
    - "what activities are due this week?"
    - "show completed activities"
    - "what tasks do we have with Acme Corp?"

    Do NOT use this tool when: the user wants to mark an activity as done — first call this tool to find the activity ID shown in brackets (e.g. [42]), then pass that integer to mark_activity_done. For creating a new activity, use create_activity.

    Parameters:
    - due_this_week (bool, optional): if True, only return activities due within the next 7 days. Defaults to False.
    - done (bool, optional): filter by completion status. True = completed only, False = pending only. Omit to return all activities regardless of status.
    - company_name (str, optional): filter by associated company (partial match). Defaults to all companies.
    """
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
    """Create a new company in the CRM. Always call with confirmed=False first to show a preview; only call with confirmed=True after the user explicitly confirms.

    Use this tool when the user asks things like:
    - "add a new company called Startup XYZ"
    - "create a company: BNA in Tunis"
    - "register a new prospect called Acme Corp"
    - "add Infinity IT to our CRM"

    Do NOT use this tool when: the company may already exist — use get_company to check first. For updating an existing company's details, use update_company.

    Parameters:
    - name (str, required): the company name.
    - industry (str, optional): industry sector (e.g. 'Banking', 'IT Consulting'). Defaults to None.
    - city (str, optional): city where the company is located. Defaults to None.
    - email (str, optional): company contact email. Defaults to None.
    - phone (str, optional): company phone number. Defaults to None.
    - confirmed (bool, required): must be False on first call (shows preview). Set to True only after user confirms.
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
    """Update one or more fields of an existing company by its integer ID. Always call with confirmed=False first to show a preview; only call with confirmed=True after the user explicitly confirms.

    Use this tool when the user asks things like:
    - "change BNA's status to client"
    - "update the phone number for company ID 5"
    - "rename Acme Corp to Acme Corporation"
    - "set the industry for company 12 to Banking"

    Do NOT use this tool when: the user wants to create a new company — use create_company. To find a company's integer ID, call get_company first.

    Parameters:
    - company_id (int, required): numeric ID of the company to update (not its name). Call get_company first if you only have the name.
    - name (str, optional): new company name.
    - industry (str, optional): new industry.
    - city (str, optional): new city.
    - country (str, optional): new country.
    - status (str, optional): new status. Valid values: 'prospect', 'client', 'inactive'.
    - phone (str, optional): new phone number.
    - email (str, optional): new email address.
    - website (str, optional): new website URL.
    - confirmed (bool, required): must be False on first call (shows preview). Set to True only after user confirms.
    """
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
    """Create a new contact person and link them to an existing company. Always call with confirmed=False first to show a preview; only call with confirmed=True after the user explicitly confirms.

    Use this tool when the user asks things like:
    - "add John Smith from Acme Corp as a contact"
    - "create a new contact: Sarah, CTO at BNA"
    - "register a contact for the Infinity IT account"
    - "new contact: Ahmed Ben Ali, developer at Startup XYZ"

    Do NOT use this tool when: the user is searching for existing contacts — use list_contacts instead. If no company_name is given, ask which company the contact belongs to before calling this tool.

    Parameters:
    - first_name (str, required): contact's first name.
    - last_name (str, required): contact's last name.
    - company_name (str, required): name of the company the contact belongs to (must already exist in CRM).
    - role (str, optional): job title or role (e.g. 'CTO', 'Account Manager'). Defaults to None.
    - email (str, optional): contact email address. Defaults to None.
    - phone (str, optional): contact phone number. Defaults to None.
    - confirmed (bool, required): must be False on first call (shows preview). Set to True only after user confirms.
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
    """Create a new deal/opportunity linked to a company. Always call with confirmed=False first to show a preview; only call with confirmed=True after the user explicitly confirms.

    Use this tool when the user asks things like:
    - "create a deal for Acme Corp worth 50,000 TND"
    - "add a new opportunity with BNA for the ERP project"
    - "open a new deal for Startup XYZ"
    - "log a new opportunity with the Ministry of Finance"

    Do NOT use this tool when: the user provides a person's name instead of a company name — first call list_contacts(name=...) to find their company, then use that company name here. For updating an existing deal, use update_deal or update_deal_status.

    Parameters:
    - company_name (str, required): name of the company this deal belongs to (must already exist in CRM). This must be a company name, not a contact/person name.
    - title (str, required): short descriptive title for the deal (e.g. 'ERP Implementation Phase 1').
    - value (float, required): estimated deal value in TND.
    - stage (str, optional): initial pipeline stage. Valid values: 'prospecting', 'qualification', 'proposal', 'negotiation', 'closed'. Defaults to 'prospecting'.
    - confirmed (bool, required): must be False on first call (shows preview). Set to True only after user confirms.
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
    """Change the outcome status of a deal to won, lost, or on_hold. Use only for terminal or hold decisions — not for pipeline stage progression. Always call with confirmed=False first to show a preview; only call with confirmed=True after the user explicitly confirms.

    Use this tool when the user asks things like:
    - "mark deal 10 as won"
    - "we lost deal 42, update the record"
    - "put deal 5 on hold"
    - "close deal 8 as a win"

    Do NOT use this tool when: the user wants to change a deal's pipeline stage (e.g. move to 'negotiation' or 'proposal') — use update_deal instead.
    MUTUAL EXCLUSION: update_deal_status is ONLY for final outcome decisions (won / lost / on_hold). update_deal is for FIELD CHANGES (stage, value, title, probability, notes). Stage ('negotiation', 'proposal') is a pipeline position; status ('won', 'lost') is an outcome. Never use this tool to change the pipeline stage.

    Parameters:
    - deal_id (int, required): numeric ID of the deal whose status should change.
    - new_status (str, required): the new outcome status. Valid values: 'open', 'won', 'lost', 'on_hold'. Setting 'won' or 'lost' also records the close date automatically.
    - confirmed (bool, required): must be False on first call (shows preview). Set to True only after user confirms.
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
    """Create a new CRM activity (call, meeting, email, task, or note) linked to a company. Always call with confirmed=False first to show a preview; only call with confirmed=True after the user explicitly confirms.

    Use this tool when the user asks things like:
    - "schedule a call with BNA for 2026-06-01"
    - "add a meeting with Acme Corp next week"
    - "log a follow-up task for Startup XYZ"
    - "create a note for the BNA account"

    Do NOT use this tool when: the user wants to mark an existing activity as completed — use mark_activity_done (call list_activities first to find the activity ID). For listing current activities, use list_activities.

    Parameters:
    - company_name (str, required): name of the company this activity is linked to.
    - title (str, required): short description of the activity (e.g. 'Follow-up call re: proposal').
    - activity_type (str, required): type of activity. Valid values: 'call', 'meeting', 'email', 'task', 'note'.
    - due_date (str, optional): due date in YYYY-MM-DD format. Compute absolute dates from relative phrasings before passing. Defaults to no due date.
    - description (str, optional): longer description or notes for the activity. Defaults to None.
    - confirmed (bool, required): must be False on first call (shows preview). Set to True only after user confirms.
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
    """Soft-delete a company by its integer ID (sets is_deleted=True; the record is preserved in the database). Always call with confirmed=False first to show a preview; only call with confirmed=True after the user explicitly confirms.

    Use this tool when the user asks things like:
    - "delete company ID 7"
    - "remove Startup XYZ from the CRM"
    - "archive company number 12"
    - "get rid of the duplicate company with ID 3"

    Do NOT use this tool when: the user wants to change the company's status to 'inactive' — use update_company with status='inactive' instead. To find the company's integer ID before deleting, call get_company first.

    Parameters:
    - company_id (int, required): numeric ID of the company to delete. This is an integer — call get_company first if you only have the name.
    - confirmed (bool, required): must be False on first call (shows preview). Set to True only after user confirms.
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
    """Soft-delete a contact by their integer ID (sets is_deleted=True; the record is preserved in the database). Always call with confirmed=False first to show a preview; only call with confirmed=True after the user explicitly confirms.

    Use this tool when the user asks things like:
    - "delete contact ID 9"
    - "remove John Smith from our contacts"
    - "delete the contact for Sarah at Acme"
    - "clear contact number 14 from the system"

    Do NOT use this tool when: the user wants to update a contact's details — use update_contact. To find the contact's integer ID before deleting, call list_contacts first.

    Parameters:
    - contact_id (int, required): numeric ID of the contact to delete. This is an integer — call list_contacts first if you only have a name.
    - confirmed (bool, required): must be False on first call (shows preview). Set to True only after user confirms.
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
    """Soft-delete a deal by its integer ID (sets is_deleted=True; the record is preserved in the database). Always call with confirmed=False first to show a preview; only call with confirmed=True after the user explicitly confirms.

    Use this tool when the user asks things like:
    - "delete deal ID 5"
    - "remove the Acme ERP deal from the pipeline"
    - "get rid of deal number 22"
    - "archive deal 8"

    Do NOT use this tool when: the user wants to close a deal as won or lost — use update_deal_status instead. Closing a deal preserves it correctly as a historical record; deletion hides it from all views.

    Parameters:
    - deal_id (int, required): numeric ID of the deal to delete. Call get_deal first if you only have a title.
    - confirmed (bool, required): must be False on first call (shows preview). Set to True only after user confirms.
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
    """Update one or more fields of an existing contact by their integer ID. Always call with confirmed=False first to show a preview; only call with confirmed=True after the user explicitly confirms.

    Use this tool when the user asks things like:
    - "update Ahmed's email to ahmed@bna.com"
    - "change contact ID 8's role to Senior Developer"
    - "update the phone number for Sarah at Acme"
    - "set contact 15 as the primary contact"

    Do NOT use this tool when: the user wants to create a new contact — use create_contact. To find a contact's integer ID, call list_contacts first.

    Parameters:
    - contact_id (int, required): numeric ID of the contact to update. Call list_contacts first if you only have a name.
    - first_name (str, optional): new first name.
    - last_name (str, optional): new last name.
    - email (str, optional): new email address.
    - phone (str, optional): new phone number.
    - role (str, optional): new job title or role.
    - is_primary (bool, optional): whether this contact is the primary contact for their company.
    - confirmed (bool, required): must be False on first call (shows preview). Set to True only after user confirms.
    """
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
    """Update content fields of an existing deal: title, value, stage, probability, or notes. Use this for pipeline progression or correcting deal details. Always call with confirmed=False first to show a preview; only call with confirmed=True after the user explicitly confirms.

    Use this tool when the user asks things like:
    - "move deal 5 to the negotiation stage"
    - "update the value of deal 12 to 80,000 TND"
    - "rename deal 7 to 'ERP Phase 2'"
    - "set the probability on deal 3 to 75%"

    Do NOT use this tool when: the user wants to mark a deal as won, lost, or on_hold — use update_deal_status instead.
    MUTUAL EXCLUSION: update_deal is for FIELD CHANGES (stage, value, title, probability, notes). update_deal_status is for TERMINAL STATUS TRANSITIONS (won / lost / on_hold). Stage ('negotiation', 'proposal') is a pipeline position; status ('won', 'lost') is an outcome. Never use this tool to set won/lost/on_hold.

    Parameters:
    - deal_id (int, required): numeric ID of the deal to update.
    - title (str, optional): new deal title.
    - value (float, optional): new deal value in TND.
    - stage (str, optional): new pipeline stage. Valid values: 'prospecting', 'qualification', 'proposal', 'negotiation', 'closed'.
    - probability (int, optional): estimated win probability as a percentage (0–100).
    - notes (str, optional): notes or comments to attach to the deal.
    - confirmed (bool, required): must be False on first call (shows preview). Set to True only after user confirms.
    """
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
    """Mark a specific CRM activity as completed by its integer activity ID. Always call with confirmed=False first to show a preview; only call with confirmed=True after the user explicitly confirms.

    Use this tool when the user asks things like:
    - "mark activity 42 as done"
    - "complete the call activity with BNA"
    - "I finished the meeting with Acme, mark it done"
    - "tick off activity number 7"

    Do NOT use this tool when: you do not yet know the activity's integer ID — call list_activities first to find the ID shown in square brackets (e.g. [42]), then pass that integer here.

    CRITICAL: activity_id is the integer shown in brackets in list_activities output, e.g. [42]. It is an Activity ID — NOT a deal_id, company_id, or contact_id. Never guess this value.

    Parameters:
    - activity_id (int, required): the integer activity ID from list_activities output (e.g. 42 from [42]).
    - confirmed (bool, required): must be False on first call (shows preview). Set to True only after user confirms.
    """
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
    """Return a ranked list of all companies currently showing churn signals, based on recent CRM activity patterns.

    Use this tool when the user asks things like:
    - "which clients should I worry about losing?"
    - "customers at risk of churning"
    - "who might we lose?"
    - "show me at-risk clients"
    - "which companies have churn signals?"
    - "who are our most at-risk accounts?"

    Do NOT use this tool when: the user asks about churn risk for a specific named company — use predict_churn(company_name=...) instead. This tool gives a cross-client ranked overview; predict_churn gives a deep ML-based probability and recommendations for one company.

    Parameters: none.
    """
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
    """Run an ML churn prediction for a single named company, returning probability, risk level (High/Medium/Low), contributing factors, and retention recommendations.

    Use this tool when the user asks things like:
    - "what's the churn risk for BNA?"
    - "is Acme Corp at risk of leaving us?"
    - "how healthy is our relationship with Startup XYZ?"
    - "predict churn for the Ministry of Finance account"

    Do NOT use this tool when: the user wants a ranked list of at-risk clients across all companies — use get_at_risk_clients instead. This tool requires a specific company name and produces a single-company deep analysis; get_at_risk_clients gives a cross-client overview with no company argument.

    Parameters:
    - company_name (str, required): the name of the company to analyse (partial match accepted). Must match a company in the CRM.
    """
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
            val = factor['value']
            val_str = f"{val*100:.0f}%" if 0 < val < 1 else f"{val:.2f}"
            lines.append(f"  - {factor['feature']}: {val_str} (impact: {factor['importance']:.3f})")

        if result.get('recommendations'):
            lines.append("")
            lines.append("Recommendations:")
            for r in result['recommendations']:
                lines.append(f"  [{r['priority']}] {r['category']}: {r['action']}")
                lines.append(f"    Rationale: {r['rationale']}")

        if result.get('summary'):
            lines.append("")
            lines.append("Summary:")
            lines.append(result['summary'])

        return "\n".join(lines)
    except Exception as e:
        return f"Could not predict churn for '{company_name}': {str(e)}"


@tool
def predict_deal_win(deal_id: int) -> str:
    """Run an ML win/loss prediction for a specific deal by its integer ID, returning win probability, predicted outcome (Likely Win / Uncertain / Likely Loss), and top contributing factors.

    Use this tool when the user asks things like:
    - "what are the odds on deal 42?"
    - "will we win deal 15?"
    - "what's the win probability for deal ID 7?"
    - "predict the outcome of deal number 3"

    Do NOT use this tool when: the user has not provided a deal ID — call list_deals or get_deal first to find the correct integer deal ID, then call this tool. For company-level relationship health, use predict_churn instead.

    Parameters:
    - deal_id (int, required): the numeric ID of the deal to predict. This is a deal ID — use list_deals to find it if you only have a title or company name.
    """
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
