"""
Seed script for JBM Consulting — a fictional Tunisian IT consulting firm.
Generates realistic data spanning Jan 2023 - Mar 2026.

Usage:
    python -m backend.seed.seed_jbm
"""

import random
from datetime import date, datetime, timedelta
from sqlalchemy import text
from backend.models.database import get_session, engine, Base
from backend.models.crm_models import Company, Contact, Deal, Activity, User
from backend.models.hr_models import Department, Employee, LeaveRequest, Payroll
from backend.models.project_models import Project, Task, TimeLog
from backend.models.invoice_models import Invoice, InvoiceItem, Payment

random.seed(42)

# ── Helpers ────────────────────────────────────────────────────────────────────

def rdate(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def rdatetime(start: date, end: date) -> datetime:
    d = rdate(start, end)
    return datetime(d.year, d.month, d.day, random.randint(8, 18), random.randint(0, 59))


def make_invoice_number(year: int, idx: int) -> str:
    return f"JBM-{year}-{idx:04d}"


START = date(2023, 1, 1)
END   = date(2026, 3, 27)

# ── Master data ────────────────────────────────────────────────────────────────

DEPT_DATA = [
    ("Engineering",  "Software development and technical delivery"),
    ("Consulting",   "Business consulting and client advisory"),
    ("Sales",        "Business development and account management"),
    ("Finance",      "Financial operations, invoicing, and payroll"),
    ("HR",           "Human resources and talent management"),
    ("Operations",   "Infrastructure, DevOps, and internal IT"),
]

# 39 employees: 31 active + 8 former
# Fields: first, last, position, dept_name, salary, hire_date, status, contract
EMPLOYEE_DATA = [
    # Engineering (12 active)
    ("Karim",    "Mansouri",   "Lead Software Engineer",   "Engineering",  8500,  date(2021, 3, 15), "active",     "cdi"),
    ("Sarra",    "Belhadj",    "Full Stack Developer",     "Engineering",  6800,  date(2022, 6, 1),  "active",     "cdi"),
    ("Anis",     "Trabelsi",   "Backend Developer",        "Engineering",  6200,  date(2022, 9, 12), "active",     "cdi"),
    ("Nour",     "Cherif",     "Frontend Developer",       "Engineering",  5900,  date(2023, 2, 20), "active",     "cdi"),
    ("Mehdi",    "Oueslati",   "DevOps Engineer",          "Engineering",  7200,  date(2021, 11, 8), "active",     "cdi"),
    ("Ines",     "Hammami",    "Mobile Developer",         "Engineering",  6100,  date(2023, 5, 1),  "active",     "cdi"),
    ("Youssef",  "Boughanmi",  "Software Architect",       "Engineering",  9800,  date(2020, 7, 14), "active",     "cdi"),
    ("Fatma",    "Jlassi",     "QA Engineer",              "Engineering",  5600,  date(2023, 8, 7),  "active",     "cdi"),
    ("Rami",     "Saidi",      "Data Engineer",            "Engineering",  7400,  date(2022, 1, 17), "active",     "cdi"),
    ("Leila",    "Khelifi",    "Full Stack Developer",     "Engineering",  6500,  date(2023, 11, 3), "active",     "cdd"),
    ("Omar",     "Ferchichi",  "Security Engineer",        "Engineering",  7800,  date(2021, 5, 22), "active",     "cdi"),
    ("Salma",    "Boukadida",  "Junior Developer",         "Engineering",  4800,  date(2024, 2, 12), "active",     "cdd"),
    # Consulting (7 active)
    ("Hatem",    "Gharbi",     "Senior Consultant",        "Consulting",   9200,  date(2020, 4, 6),  "active",     "cdi"),
    ("Meriem",   "Tlili",      "Business Analyst",         "Consulting",   7600,  date(2021, 9, 1),  "active",     "cdi"),
    ("Bilel",    "Jendoubi",   "ERP Consultant",           "Consulting",   8800,  date(2022, 3, 15), "active",     "cdi"),
    ("Dorra",    "Nasri",      "IT Consultant",            "Consulting",   7100,  date(2023, 1, 9),  "active",     "cdi"),
    ("Tarek",    "Dridi",      "Process Analyst",          "Consulting",   7300,  date(2022, 7, 25), "active",     "cdi"),
    ("Rim",      "Zouari",     "Junior Consultant",        "Consulting",   5200,  date(2024, 3, 4),  "active",     "cdd"),
    ("Khaled",   "Chaouch",    "Senior ERP Consultant",    "Consulting",  10500,  date(2019, 6, 10), "active",     "cdi"),
    # Sales (4 active)
    ("Aymen",    "Msakni",     "Sales Manager",            "Sales",        9000,  date(2020, 10, 1), "active",     "cdi"),
    ("Hela",     "Ben Ali",    "Account Executive",        "Sales",        6800,  date(2022, 4, 18), "active",     "cdi"),
    ("Sofiane",  "Mejri",      "Business Developer",       "Sales",        6400,  date(2023, 6, 5),  "active",     "cdi"),
    ("Yasmine",  "Ghariani",   "Pre-Sales Engineer",       "Sales",        6600,  date(2023, 9, 11), "active",     "cdi"),
    # Finance (3 active)
    ("Manel",    "Sghaier",    "Finance Manager",          "Finance",      9500,  date(2020, 2, 3),  "active",     "cdi"),
    ("Firas",    "Kraiem",     "Accountant",               "Finance",      6200,  date(2022, 8, 29), "active",     "cdi"),
    ("Asma",     "Hamdi",      "Financial Controller",     "Finance",      7800,  date(2021, 12, 6), "active",     "cdi"),
    # HR (2 active)
    ("Sabrine",  "Belhaj",     "HR Manager",               "HR",           8800,  date(2020, 1, 15), "active",     "cdi"),
    ("Walid",    "Bensaid",    "HR Officer",               "HR",           5900,  date(2023, 4, 17), "active",     "cdi"),
    # Operations (3 active)
    ("Nizar",    "Riahi",      "IT Operations Manager",    "Operations",   9100,  date(2020, 8, 20), "active",     "cdi"),
    ("Cyrine",   "Mbarek",     "System Administrator",     "Operations",   6700,  date(2022, 5, 10), "active",     "cdi"),
    ("Hichem",   "Bouzid",     "Network Engineer",         "Operations",   6300,  date(2023, 7, 1),  "active",     "cdi"),
    # Former employees (8)
    ("Adel",     "Hamrouni",   "Backend Developer",        "Engineering",  6000,  date(2021, 4, 1),  "resigned",   "cdi"),
    ("Sonia",    "Karray",     "IT Consultant",            "Consulting",   7200,  date(2020, 9, 15), "resigned",   "cdi"),
    ("Bassem",   "Ouali",      "Junior Developer",         "Engineering",  4500,  date(2022, 11, 7), "terminated", "cdd"),
    ("Amira",    "Cherni",     "Account Executive",        "Sales",        6100,  date(2022, 2, 14), "resigned",   "cdi"),
    ("Zied",     "Mabrouk",    "Data Analyst",             "Engineering",  6400,  date(2021, 7, 20), "resigned",   "cdi"),
    ("Olfa",     "Baccouche",  "HR Officer",               "HR",           5500,  date(2022, 6, 3),  "resigned",   "cdi"),
    ("Ramzi",    "Touati",     "System Administrator",     "Operations",   6000,  date(2021, 10, 12),"resigned",   "cdi"),
    ("Nesrine",  "Haddar",     "Business Analyst",         "Consulting",   6800,  date(2020, 5, 25), "resigned",   "cdi"),
]

# 45 companies: mix of Tunisian + regional + multinational clients
COMPANY_DATA = [
    # name, industry, city, country, status
    ("Tunisie Telecom",         "Telecom",          "Tunis",       "Tunisia",  "client"),
    ("Ooredoo Tunisie",         "Telecom",          "Tunis",       "Tunisia",  "client"),
    ("STB Bank",                "Finance",          "Tunis",       "Tunisia",  "client"),
    ("BNA Bank",                "Finance",          "Tunis",       "Tunisia",  "client"),
    ("Attijari Bank",           "Finance",          "Tunis",       "Tunisia",  "client"),
    ("STEG",                    "Energy",           "Tunis",       "Tunisia",  "client"),
    ("Tunisair",                "Transport",        "Tunis",       "Tunisia",  "client"),
    ("Sofrecom Tunisie",        "Telecom",          "Tunis",       "Tunisia",  "client"),
    ("Poulina Group",           "Agro-industrie",   "Tunis",       "Tunisia",  "client"),
    ("Carthago Ceramics",       "Manufacturing",    "Nabeul",      "Tunisia",  "client"),
    ("Delice Danone",           "Agro-industrie",   "Tunis",       "Tunisia",  "client"),
    ("Enda Tamweel",            "Finance",          "Tunis",       "Tunisia",  "client"),
    ("Cnudst",                  "Education",        "Tunis",       "Tunisia",  "client"),
    ("Ministere des Finances",  "Government",       "Tunis",       "Tunisia",  "client"),
    ("CNAM Tunisie",            "Healthcare",       "Tunis",       "Tunisia",  "client"),
    ("Tunisie Autoroutes",      "Infrastructure",   "Tunis",       "Tunisia",  "client"),
    ("Ben Yedder Group",        "Real Estate",      "Sfax",        "Tunisia",  "client"),
    ("BIAT",                    "Finance",          "Tunis",       "Tunisia",  "client"),
    ("Societe Generale Tunis",  "Finance",          "Tunis",       "Tunisia",  "client"),
    ("Smart Systems",           "IT",               "Tunis",       "Tunisia",  "client"),
    ("Vermeg",                  "IT",               "Tunis",       "Tunisia",  "client"),
    ("Talan Tunisie",           "IT",               "Tunis",       "Tunisia",  "client"),
    ("Telnet Holding",          "IT",               "Tunis",       "Tunisia",  "client"),
    ("HITS Telecom",            "Telecom",          "Tunis",       "Tunisia",  "client"),
    ("Hexabyte",                "Telecom",          "Tunis",       "Tunisia",  "client"),
    ("SONEDE",                  "Utilities",        "Tunis",       "Tunisia",  "prospect"),
    ("ONAT",                    "Tourism",          "Tunis",       "Tunisia",  "prospect"),
    ("GCT",                     "Mining",           "Gafsa",       "Tunisia",  "prospect"),
    ("Groupe Chimique Tunisien","Chemical",         "Gabes",       "Tunisia",  "prospect"),
    ("Ecole Polytechnique",     "Education",        "Tunis",       "Tunisia",  "prospect"),
    ("Universite Centrale",     "Education",        "Tunis",       "Tunisia",  "prospect"),
    ("Clinique El Amen",        "Healthcare",       "Tunis",       "Tunisia",  "prospect"),
    ("Polyclinique Taoufik",    "Healthcare",       "Sfax",        "Tunisia",  "prospect"),
    ("Maghreb Steel",           "Manufacturing",    "Tunis",       "Tunisia",  "prospect"),
    ("Sopal",                   "Manufacturing",    "Sfax",        "Tunisia",  "prospect"),
    # Regional
    ("Orange Maroc",            "Telecom",          "Casablanca",  "Morocco",  "client"),
    ("Maroc Telecom",           "Telecom",          "Rabat",       "Morocco",  "client"),
    ("CIH Bank",                "Finance",          "Casablanca",  "Morocco",  "client"),
    ("Attijariwafa Bank",       "Finance",          "Casablanca",  "Morocco",  "client"),
    ("Algerie Telecom",         "Telecom",          "Alger",       "Algeria",  "client"),
    ("BNA Algerie",             "Finance",          "Alger",       "Algeria",  "client"),
    # Inactive
    ("TopNet",                  "Telecom",          "Tunis",       "Tunisia",  "inactive"),
    ("Tunisia Mall",            "Retail",           "Tunis",       "Tunisia",  "inactive"),
    ("Comet Tunisie",           "Retail",           "Tunis",       "Tunisia",  "inactive"),
    ("Sfax Ceramics",           "Manufacturing",    "Sfax",        "Tunisia",  "inactive"),
]

# Contact roles per industry
CONTACT_ROLES = ["CEO", "CTO", "IT Director", "CFO", "Project Manager", "Procurement Manager", "DSI"]

# Deal titles templates
DEAL_TITLES = [
    "Implémentation ERP {module}",
    "Migration Cloud {tech}",
    "Développement Application {type}",
    "Audit SI et Conseil",
    "Intégration API {tech}",
    "Refonte Système {domain}",
    "Formation et Accompagnement",
    "Support et Maintenance {level}",
    "Tableau de Bord BI",
    "Cybersécurité et Conformité",
    "Digitalisation {domain}",
    "Déploiement Infrastructure {tech}",
    "Consulting Transformation Digitale",
    "Développement Mobile {platform}",
    "Data Analytics Platform",
]

MODULES  = ["Finance", "RH", "CRM", "Achats", "Stock", "Production"]
TECHS    = ["AWS", "Azure", "GCP", "Kubernetes", "Docker", "Microservices"]
TYPES    = ["Web", "Mobile", "Desktop", "SaaS"]
DOMAINS  = ["RH", "Finance", "Logistique", "Commercial", "Achats"]
LEVELS   = ["N1/N2", "N2/N3", "Premium"]
PLATFORMS = ["iOS/Android", "Android", "iOS", "React Native"]

def random_deal_title() -> str:
    t = random.choice(DEAL_TITLES)
    return t.format(
        module=random.choice(MODULES),
        tech=random.choice(TECHS),
        type=random.choice(TYPES),
        domain=random.choice(DOMAINS),
        level=random.choice(LEVELS),
        platform=random.choice(PLATFORMS),
    )

# Project name templates
PROJECT_NAMES = [
    "ERP {client} Phase {n}",
    "Migration Cloud {client}",
    "Application Mobile {client}",
    "Plateforme BI {client}",
    "Refonte SI {client}",
    "Audit Sécurité {client}",
    "Portail RH {client}",
    "Intégration API {client}",
    "Data Warehouse {client}",
    "DevOps Pipeline {client}",
]

TASK_TITLES = [
    "Analyse des besoins",
    "Conception architecture",
    "Développement module core",
    "Intégration base de données",
    "Tests unitaires",
    "Tests d'intégration",
    "Déploiement UAT",
    "Formation utilisateurs",
    "Documentation technique",
    "Mise en production",
    "Recette client",
    "Configuration serveurs",
    "Développement API",
    "Interface utilisateur",
    "Revue de code",
]

ACTIVITY_TITLES_CALL = [
    "Appel de suivi projet",
    "Point hebdomadaire",
    "Discussion technique",
    "Appel commercial",
    "Qualification prospect",
]
ACTIVITY_TITLES_MEETING = [
    "Réunion de lancement",
    "Présentation solution",
    "Atelier technique",
    "Comité de pilotage",
    "Démonstration produit",
]
ACTIVITY_TITLES_EMAIL = [
    "Envoi proposition commerciale",
    "Suivi devis",
    "Confirmation RDV",
    "Rapport d'avancement",
    "Relance facture",
]


# ── Main seed function ──────────────────────────────────────────────────────────

def run_seed():
    Base.metadata.create_all(bind=engine)
    db = get_session()

    try:
        db.execute(text("""
            TRUNCATE TABLE
                time_logs, tasks, invoice_items, payments, invoices,
                activities, leave_requests, payroll, audit_logs, sessions,
                projects, deals, contacts, employees, departments,
                companies, users
            RESTART IDENTITY CASCADE
        """))
        db.commit()
        print("Cleared existing data")

        # ── Admin user ────────────────────────────────────────────────────────
        admin = User(
            username="admin",
            email="admin@jbm-consulting.tn",
            password_hash="$2b$12$placeholder_hash_for_seed",
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.flush()

        # ── Departments ───────────────────────────────────────────────────────
        dept_map: dict[str, Department] = {}
        for name, desc in DEPT_DATA:
            d = Department(name=name, description=desc)
            db.add(d)
            dept_map[name] = d
        db.flush()

        # ── Employees ─────────────────────────────────────────────────────────
        emp_list: list[Employee] = []
        for (fn, ln, pos, dept_name, sal, hdate, status, ctype) in EMPLOYEE_DATA:
            emp = Employee(
                first_name=fn,
                last_name=ln,
                email=f"{fn.lower().replace(' ', '.')}.{ln.lower().replace(' ', '.')}@jbm-consulting.tn",
                phone=f"+216 {random.randint(20,99)} {random.randint(100,999)} {random.randint(100,999)}",
                position=pos,
                department_id=dept_map[dept_name].id,
                salary=sal,
                currency="TND",
                hire_date=hdate,
                birth_date=date(random.randint(1980, 1998), random.randint(1, 12), random.randint(1, 28)),
                status=status,
                contract_type=ctype,
                is_deleted=False,
            )
            db.add(emp)
            emp_list.append(emp)
        db.flush()

        # Assign department managers (pick a senior active employee per dept)
        dept_mgr: dict[str, Employee] = {}
        for emp in emp_list:
            dname = next(d for d, o in dept_map.items() if o.id == emp.department_id)
            if emp.status == "active" and dname not in dept_mgr:
                dept_mgr[dname] = emp
        for dname, mgr in dept_mgr.items():
            dept_map[dname].manager_id = mgr.id
        db.flush()

        active_emps = [e for e in emp_list if e.status == "active"]

        # ── Payroll (Jan 2023 – Mar 2026 for all employees while active) ──────
        payroll_months = []
        cur = date(2023, 1, 1)
        while cur <= date(2026, 3, 1):
            payroll_months.append((cur.year, cur.month))
            cur = date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)

        for emp in emp_list:
            for (yr, mo) in payroll_months:
                # Skip months before hire
                if date(yr, mo, 1) < emp.hire_date:
                    continue
                # Former employees: stop payroll after a plausible end date
                if emp.status in ("resigned", "terminated"):
                    end_yr = emp.hire_date.year + random.randint(1, 3)
                    end_mo = random.randint(1, 12)
                    if date(yr, mo, 1) > date(end_yr, end_mo, 1):
                        continue
                bonus = round(random.choice([0, 0, 0, emp.salary * 0.05,
                                             emp.salary * 0.1, emp.salary * 0.15]), 0)
                deductions = round(emp.salary * random.uniform(0.08, 0.12), 0)
                net = emp.salary + bonus - deductions
                is_paid = date(yr, mo, 1) < date(2026, 3, 1)
                p = Payroll(
                    employee_id=emp.id,
                    month=mo,
                    year=yr,
                    base_salary=emp.salary,
                    bonuses=bonus,
                    deductions=deductions,
                    net_salary=net,
                    status="paid" if is_paid else "pending",
                    paid_at=datetime(yr, mo, random.randint(25, 28), 9, 0) if is_paid else None,
                )
                db.add(p)

        # ── Leave requests ────────────────────────────────────────────────────
        leave_types = ["annual", "annual", "annual", "sick", "sick", "maternity", "unpaid"]
        for emp in active_emps:
            for _ in range(random.randint(2, 6)):
                start = rdate(max(emp.hire_date, START), date(2026, 2, 28))
                days = random.randint(1, 10)
                end = start + timedelta(days=days - 1)
                ltype = random.choice(leave_types)
                status = random.choice(["approved", "approved", "approved", "pending", "rejected"])
                approver = random.choice(active_emps)
                lr = LeaveRequest(
                    employee_id=emp.id,
                    approved_by=approver.id if status == "approved" else None,
                    leave_type=ltype,
                    start_date=start,
                    end_date=end,
                    days=days,
                    reason=f"Congé {ltype}",
                    status=status,
                )
                db.add(lr)

        db.flush()

        # ── Companies ─────────────────────────────────────────────────────────
        co_list: list[Company] = []
        for (name, industry, city, country, status) in COMPANY_DATA:
            co = Company(
                name=name,
                industry=industry,
                city=city,
                country=country,
                phone=f"+{216 if country=='Tunisia' else (212 if country=='Morocco' else 213)} {random.randint(10,99)} {random.randint(100,999)} {random.randint(100,999)}",
                email=f"contact@{name.lower().replace(' ', '-').replace('/', '')[:20]}.{('tn' if country=='Tunisia' else 'ma' if country=='Morocco' else 'dz')}",
                website=f"www.{name.lower().replace(' ', '-').replace('/', '')[:20]}.{('tn' if country=='Tunisia' else 'ma' if country=='Morocco' else 'dz')}",
                status=status,
                is_deleted=False,
                created_at=rdatetime(date(2022, 1, 1), date(2023, 6, 1)),
            )
            db.add(co)
            co_list.append(co)
        db.flush()

        client_cos = [c for c in co_list if c.status == "client"]
        prospect_cos = [c for c in co_list if c.status == "prospect"]
        active_cos = client_cos + prospect_cos

        # ── Contacts (1-3 per company) ────────────────────────────────────────
        contact_list: list[Contact] = []
        first_names_m = ["Ahmed", "Mohamed", "Karim", "Youssef", "Tarek", "Nabil", "Samir", "Hassan", "Omar", "Rachid"]
        first_names_f = ["Amira", "Fatima", "Samira", "Nadia", "Leila", "Rania", "Houda", "Sonia", "Asma", "Sara"]
        last_names    = ["Benali", "Mansouri", "Trabelsi", "Gharbi", "Saidi", "Khelifi", "Nasri", "Dridi",
                         "Hmidi", "Ferchichi", "Ouali", "Jlassi", "Sfaxi", "Belkadi", "Oujida"]

        for co in co_list:
            n_contacts = random.randint(1, 3)
            for i in range(n_contacts):
                gender = random.choice(["m", "f"])
                fn = random.choice(first_names_m if gender == "m" else first_names_f)
                ln = random.choice(last_names)
                role = random.choice(CONTACT_ROLES)
                ct = Contact(
                    company_id=co.id,
                    first_name=fn,
                    last_name=ln,
                    email=f"{fn.lower()}.{ln.lower()}@{co.name.lower().replace(' ', '-')[:15]}.tn",
                    phone=f"+216 {random.randint(20,99)} {random.randint(100,999)} {random.randint(100,999)}",
                    role=role,
                    is_primary=(i == 0),
                    is_deleted=False,
                )
                db.add(ct)
                contact_list.append(ct)
        db.flush()

        # ── Deals (180) ───────────────────────────────────────────────────────
        deal_list: list[Deal] = []
        stages   = ["prospecting", "qualification", "proposal", "negotiation", "closed"]
        statuses_weights = {
            "client":   [("won", 50), ("lost", 15), ("open", 30), ("on_hold", 5)],
            "prospect": [("won", 10), ("lost", 25), ("open", 55), ("on_hold", 10)],
            "inactive": [("won", 20), ("lost", 50), ("open", 10), ("on_hold", 20)],
        }

        def pick_status(co_status: str):
            choices = statuses_weights.get(co_status, statuses_weights["prospect"])
            pool = [s for s, w in choices for _ in range(w)]
            return random.choice(pool)

        n_deals = 0
        for _ in range(180):
            co = random.choice(active_cos)
            status = pick_status(co.status)
            created = rdate(START, date(2026, 1, 31))
            if status in ("won", "lost"):
                stage = "closed"
                closed = rdate(created + timedelta(days=30), min(created + timedelta(days=180), END))
                exp_close = closed
            elif status == "open":
                stage = random.choice(stages[:4])
                closed = None
                exp_close = rdate(date(2026, 1, 1), date(2026, 12, 31))
            else:
                stage = random.choice(stages[:3])
                closed = None
                exp_close = rdate(date(2026, 3, 1), date(2026, 9, 30))

            value = round(random.choice([
                random.uniform(15000, 50000),
                random.uniform(50000, 150000),
                random.uniform(150000, 400000),
                random.uniform(400000, 800000),
            ]), -3)

            deal = Deal(
                company_id=co.id,
                title=random_deal_title(),
                value=value,
                currency="TND",
                status=status,
                stage=stage,
                probability={"prospecting": 10, "qualification": 25, "proposal": 50,
                             "negotiation": 75, "closed": 100 if status == "won" else 0}.get(stage, 50),
                expected_close_date=datetime.combine(exp_close, datetime.min.time()) if exp_close else None,
                closed_at=datetime.combine(closed, datetime.min.time()) if closed else None,
                notes=f"Deal {n_deals + 1}",
                is_deleted=False,
                created_at=rdatetime(START, date(2026, 1, 31)),
            )
            db.add(deal)
            deal_list.append(deal)
            n_deals += 1

        db.flush()

        # ── Activities (3-8 per active company) ───────────────────────────────
        activity_types = ["call", "meeting", "email", "task"]
        activity_title_map = {
            "call":    ACTIVITY_TITLES_CALL,
            "meeting": ACTIVITY_TITLES_MEETING,
            "email":   ACTIVITY_TITLES_EMAIL,
            "task":    ["Préparer proposal", "Relancer prospect", "Mise à jour CRM"],
        }
        co_contacts: dict[int, list[Contact]] = {}
        for ct in contact_list:
            co_contacts.setdefault(ct.company_id, []).append(ct)

        for co in active_cos:
            for _ in range(random.randint(3, 8)):
                atype = random.choice(activity_types)
                atitle = random.choice(activity_title_map[atype])
                due = rdate(START, END)
                done = due < date(2026, 3, 1) and random.random() > 0.2
                contacts_for_co = co_contacts.get(co.id, [])
                act = Activity(
                    company_id=co.id,
                    contact_id=random.choice(contacts_for_co).id if contacts_for_co else None,
                    user_id=admin.id,
                    type=atype,
                    title=atitle,
                    description=f"Activité liée à {co.name}",
                    due_date=datetime.combine(due, datetime.min.time()),
                    done=done,
                    done_at=datetime.combine(due, datetime.min.time()) if done else None,
                    created_at=rdatetime(START, END),
                )
                db.add(act)

        db.flush()

        # ── Projects (35) ─────────────────────────────────────────────────────
        proj_statuses = ["active", "active", "active", "completed", "completed", "planning", "on_hold", "cancelled"]
        proj_priorities = ["high", "high", "medium", "medium", "medium", "low", "critical"]

        project_list: list[Project] = []
        won_deals = [d for d in deal_list if d.status == "won"]
        random.shuffle(won_deals)
        deal_pool = won_deals[:35] + deal_list[:]  # fallback

        used_companies_for_projects = set()
        for i in range(35):
            # Prefer linking to won deals
            linked_deal = deal_pool[i] if i < len(deal_pool) else random.choice(deal_list)
            co = next((c for c in co_list if c.id == linked_deal.company_id), random.choice(client_cos))

            short_name = co.name.split()[0]
            proj_name = random.choice(PROJECT_NAMES).format(client=short_name, n=random.randint(1, 3))
            pstatus = random.choice(proj_statuses)
            ppriority = random.choice(proj_priorities)

            start = rdate(date(2023, 1, 1), date(2025, 6, 1))
            duration_days = random.randint(60, 365)
            end = start + timedelta(days=duration_days)

            budget = round(linked_deal.value * random.uniform(0.6, 0.95), -3) if linked_deal.value else round(random.uniform(30000, 300000), -3)
            spent_pct = {"active": random.uniform(0.2, 0.7),
                         "completed": random.uniform(0.8, 1.05),
                         "planning": random.uniform(0.0, 0.15),
                         "on_hold": random.uniform(0.3, 0.6),
                         "cancelled": random.uniform(0.1, 0.4)}.get(pstatus, 0.5)
            spent = round(budget * spent_pct, -2)

            manager = random.choice([e for e in active_emps if e.department_id == dept_map["Engineering"].id or
                                     e.department_id == dept_map["Consulting"].id])

            proj = Project(
                name=proj_name,
                description=f"Projet {proj_name} pour {co.name}",
                company_id=co.id,
                deal_id=linked_deal.id,
                manager_id=manager.id,
                status=pstatus,
                priority=ppriority,
                budget=budget,
                spent=spent,
                currency="TND",
                start_date=start,
                end_date=end,
                completed_at=datetime(end.year, end.month, end.day) if pstatus == "completed" else None,
                is_deleted=False,
                created_at=rdatetime(date(2023, 1, 1), start),
            )
            db.add(proj)
            project_list.append(proj)

        db.flush()

        # ── Tasks (4-8 per project) ───────────────────────────────────────────
        task_list: list[Task] = []
        task_statuses = ["todo", "in_progress", "review", "done"]

        for proj in project_list:
            n_tasks = random.randint(4, 8)
            for j in range(n_tasks):
                ttitle = random.choice(TASK_TITLES)
                if proj.status == "completed":
                    tstatus = "done"
                elif proj.status == "planning":
                    tstatus = random.choice(["todo", "todo", "in_progress"])
                elif proj.status == "cancelled":
                    tstatus = random.choice(["todo", "in_progress", "done"])
                else:
                    tstatus = random.choice(task_statuses)

                due = rdate(proj.start_date, proj.end_date)
                assignee = random.choice(active_emps)
                est_hours = random.choice([8, 16, 24, 32, 40, 48])

                task = Task(
                    project_id=proj.id,
                    assigned_to=assignee.id,
                    title=ttitle,
                    description=f"Tâche: {ttitle} pour projet {proj.name}",
                    status=tstatus,
                    priority=random.choice(["low", "medium", "high"]),
                    due_date=due,
                    completed_at=datetime(due.year, due.month, due.day) if tstatus == "done" else None,
                    estimated_hours=float(est_hours),
                    created_at=rdatetime(proj.start_date, due),
                )
                db.add(task)
                task_list.append(task)

        db.flush()

        # ── Time logs (realistic hours per project) ───────────────────────────
        eng_emps = [e for e in active_emps if e.department_id in
                    (dept_map["Engineering"].id, dept_map["Consulting"].id)]

        for proj in project_list:
            total_target_hours = proj.budget / 250 if proj.budget else 100  # ~250 TND/hour
            total_target_hours = min(max(total_target_hours, 40), 2000)
            logged = 0
            proj_tasks = [t for t in task_list if t.project_id == proj.id]

            while logged < total_target_hours * 0.7:
                emp = random.choice(eng_emps)
                hours = round(random.uniform(1, 8), 1)
                log_date = rdate(proj.start_date, min(proj.end_date, END))
                task = random.choice(proj_tasks) if proj_tasks else None
                tl = TimeLog(
                    project_id=proj.id,
                    task_id=task.id if task else None,
                    employee_id=emp.id,
                    hours=hours,
                    description=f"Travail sur {proj.name}",
                    log_date=log_date,
                    created_at=datetime.combine(log_date, datetime.min.time()),
                )
                db.add(tl)
                logged += hours

        db.flush()

        # ── Invoices (linked to completed/active projects) ────────────────────
        invoice_idx = 1
        invoice_list: list[Invoice] = []

        # One or two invoices per project with status completed or active
        billable_projects = [p for p in project_list if p.status in ("completed", "active")]

        for proj in billable_projects:
            co = next(c for c in co_list if c.id == proj.company_id)
            n_invoices = 2 if proj.status == "completed" else 1

            for inv_n in range(n_invoices):
                issue = rdate(proj.start_date, min(proj.end_date, date(2026, 3, 1)))
                due = issue + timedelta(days=30)
                subtotal = round(proj.budget * (0.5 if n_invoices == 2 else random.uniform(0.6, 0.9)), -2)
                tax = round(subtotal * 0.19, 2)
                total = round(subtotal + tax, 2)

                is_past_due = due < date(2026, 3, 1)
                status_choice = random.choices(
                    ["paid", "sent", "overdue"],
                    weights=[60, 25, 15] if is_past_due else [0, 80, 20],
                )[0]

                inv = Invoice(
                    invoice_number=make_invoice_number(issue.year, invoice_idx),
                    company_id=co.id,
                    project_id=proj.id,
                    status=status_choice,
                    subtotal=subtotal,
                    tax_rate=19.0,
                    tax_amount=tax,
                    total=total,
                    currency="TND",
                    issue_date=issue,
                    due_date=due,
                    paid_at=datetime.combine(rdate(issue, due), datetime.min.time()) if status_choice == "paid" else None,
                    notes=f"Facture {inv_n + 1}/{n_invoices} - {proj.name}",
                    is_deleted=False,
                    created_at=datetime.combine(issue, datetime.min.time()),
                )
                db.add(inv)
                db.flush()  # assigns inv.id before creating items
                invoice_list.append(inv)
                invoice_idx += 1

                # Invoice items
                item_descriptions = [
                    "Développement logiciel",
                    "Conseil et assistance technique",
                    "Déploiement et configuration",
                    "Formation utilisateurs",
                    "Gestion de projet",
                ]
                n_items = random.randint(2, 4)
                remaining = subtotal
                for k in range(n_items):
                    qty = random.randint(1, 10)
                    if k == n_items - 1:
                        item_total = round(remaining, 2)
                        unit_p = round(item_total / qty, 2)
                    else:
                        unit_p = round(random.uniform(500, 5000), 0)
                        item_total = round(qty * unit_p, 2)
                        remaining -= item_total

                    db.add(InvoiceItem(
                        invoice_id=inv.id,
                        description=random.choice(item_descriptions),
                        quantity=float(qty),
                        unit_price=unit_p,
                        total=item_total,
                    ))

                # Payment record for paid invoices
                if status_choice == "paid":
                    db.add(Payment(
                        invoice_id=inv.id,
                        amount=total,
                        method=random.choice(["bank_transfer", "bank_transfer", "check"]),
                        reference=f"VIR-{issue.year}-{random.randint(1000, 9999)}",
                        paid_at=inv.paid_at,
                        notes="Paiement reçu",
                    ))

        db.flush()
        db.commit()

        # Stats
        print("Seed JBM Consulting completed:")
        print(f"  Departments   : {db.query(Department).count()}")
        print(f"  Employees     : {db.query(Employee).count()} ({db.query(Employee).filter_by(status='active').count()} active)")
        print(f"  Companies     : {db.query(Company).count()}")
        print(f"  Contacts      : {db.query(Contact).count()}")
        print(f"  Deals         : {db.query(Deal).count()}")
        print(f"  Activities    : {db.query(Activity).count()}")
        print(f"  Projects      : {db.query(Project).count()}")
        print(f"  Tasks         : {db.query(Task).count()}")
        print(f"  Time logs     : {db.query(TimeLog).count()}")
        print(f"  Invoices      : {db.query(Invoice).count()}")
        print(f"  Payments      : {db.query(Payment).count()}")
        print(f"  Payroll rows  : {db.query(Payroll).count()}")
        print(f"  Leave requests: {db.query(LeaveRequest).count()}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
