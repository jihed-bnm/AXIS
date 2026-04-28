"""
generate_raw_data.py  (v2 - large-volume pre-ETL data)
Generates 4 raw Excel files (~410,000 rows) simulating dirty pre-ETL
ERP data for JBM Consulting, a Tunisian IT consulting firm (2023-2026).

Usage:
    python data/generate_raw_data.py
"""

import os
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

# ── Reproducibility ────────────────────────────────────────────────────────────
random.seed(42)
np.random.seed(42)
Faker.seed(42)

fake = Faker("fr_FR")

# ── Output directory ───────────────────────────────────────────────────────────
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(DATA_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# DATE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

PERIOD_START = date(2023, 1, 1)
PERIOD_END   = date(2026, 3, 31)

_DATE_FMTS = ["%Y-%m-%d", "%d/%m/%Y", "%B %d %Y", "%d-%b-%y", "%Y/%m/%d"]


def rand_date(start=PERIOD_START, end=PERIOD_END) -> date:
    delta = (end - start).days
    if delta <= 0:
        return start
    return start + timedelta(days=random.randint(0, delta))


def messy_date(d, null_prob: float = 0.0):
    if d is None:
        return None
    if null_prob > 0 and random.random() < null_prob:
        return None
    return d.strftime(random.choice(_DATE_FMTS))


def rand_date_seasonal(year: int) -> date:
    if year == 2026:
        return rand_date(date(2026, 1, 1), date(2026, 3, 31))
    q = random.choices([1, 2, 3, 4], weights=[1.0, 1.3, 0.7, 1.5])[0]
    ranges = {
        1: (date(year, 1, 1),  date(year, 3, 31)),
        2: (date(year, 4, 1),  date(year, 6, 30)),
        3: (date(year, 7, 1),  date(year, 9, 30)),
        4: (date(year, 10, 1), date(year, 12, 31)),
    }
    return rand_date(*ranges[q])


def rand_date_activity(year: int) -> date:
    """Activity date with weekday bias and seasonal patterns (rejection sampling)."""
    while True:
        d = rand_date_seasonal(year)
        dow = d.weekday()
        if dow == 6 and random.random() > 0.05:   # Sunday: 5%
            continue
        if dow == 5 and random.random() > 0.20:   # Saturday: 20%
            continue
        if d.month in (7, 8) and random.random() > 0.60:          # Summer dip
            continue
        if d.month == 12 and d.day >= 15 and random.random() > 0.70:  # Xmas
            continue
        if d.month in (10, 11) and random.random() < 0.20:        # Q4 extra accepted
            pass
        return d


# ══════════════════════════════════════════════════════════════════════════════
# COMPANIES
# ══════════════════════════════════════════════════════════════════════════════

REAL_COMPANIES = [
    "Tunisie Telecom", "STEG", "Orange Tunisie", "Banque de Tunisie",
    "BIAT", "Poulina Group", "Delice Danone", "Tunisair", "BNA Bank",
    "Attijari Bank", "UIB", "Ooredoo Tunisie", "La Poste Tunisienne",
    "CNSS", "CNAM", "Ministere des Finances", "Topnet", "Hexabyte",
    "GlobalNet", "CyberPark Elghazala",
]

TUN_LASTNAMES = [
    "Ben Salah", "Mansour", "Chaabane", "Trabelsi", "Hamdi", "Agrebi",
    "Khalfallah", "Zouari", "Mejri", "Ben Romdhane", "Gharbi", "Hamouda",
    "Laabidi", "Ferchiou", "Haddad", "Mrad", "Sghaier", "Bouzid",
    "Chaker", "Rekik", "Belhadj", "Oueslati", "Jlassi", "Turki",
]

_MED_TMPLS = [
    "STE {ln} Informatique", "STE {ln} Consulting", "Cabinet {ln} & Associes",
    "Groupe {ln} Digital", "Bureau d'Etudes {ln}", "Groupe {ln} Technologies",
    "STE {ln} Solutions", "Cabinet {ln} Conseil", "STE {ln} & Fils",
    "Entreprise {ln}",
]

_r42 = random.Random(42)
_seen: set = set()
MEDIUM_COMPANIES: list = []
for _ in range(1000):
    _ln = TUN_LASTNAMES[_r42.randint(0, len(TUN_LASTNAMES) - 1)]
    _t  = _MED_TMPLS[_r42.randint(0, len(_MED_TMPLS) - 1)]
    _n  = _t.format(ln=_ln)
    if _n not in _seen:
        _seen.add(_n)
        MEDIUM_COMPANIES.append(_n)
    if len(MEDIUM_COMPANIES) == 40:
        break

SMALL_COMPANIES = [
    "Pharmacie Al Amal", "Restaurant Le Mediterranee",
    "Magasin Mabrouk Electronique", "Cabinet Comptable Slim",
    "Auto-Ecole Nejib", "Librairie Al Manar", "Boulangerie Chez Faouzi",
    "Agence Immobiliere Sfax Centre", "Cafe Carthage",
    "Clinique Dentaire Dr Mrad", "Studio Photo Memories",
    "Garage Mecanique Toumi", "Imprimerie El Ittihad",
    "Centre de Formation Avenir", "Ecole Privee Ibn Khaldoun",
    "Salon Coiffure Elegance", "Bijouterie Sfaxienne",
    "Fleuriste Au Jasmin", "Centre Medical Bouzid",
    "Societe Haddad Import Export",
]

ALL_COMPANIES = REAL_COMPANIES + MEDIUM_COMPANIES + SMALL_COMPANIES  # 80 total

COMPANY_TYPE: dict = {}
for _c in REAL_COMPANIES:   COMPANY_TYPE[_c] = "large"
for _c in MEDIUM_COMPANIES: COMPANY_TYPE[_c] = "medium"
for _c in SMALL_COMPANIES:  COMPANY_TYPE[_c] = "small"

# ── Company health for churn signal embedding ─────────────────────────────────
# 60% healthy | 25% churning | 15% at_risk  (reproducible via seed)
_health_pool = ["healthy"] * 48 + ["churning"] * 20 + ["at_risk"] * 12
_rnd_health  = random.Random(99)
_rnd_health.shuffle(_health_pool)
COMPANY_HEALTH: dict = {c: h for c, h in zip(ALL_COMPANIES, _health_pool)}

# Weights for activity company selection (larger = more activities)
COMPANY_WEIGHTS = [
    5 if COMPANY_TYPE[c] == "large" else
    2 if COMPANY_TYPE[c] == "medium" else 1
    for c in ALL_COMPANIES
]


def dirty_name(name: str, prob: float = 0.15) -> str:
    if random.random() > prob:
        return name
    r = random.random()
    if r < 0.18: return name.lower()
    if r < 0.33: return name.upper()
    if r < 0.48: return name.replace(" ", "-")
    if r < 0.63:
        pos = random.randint(1, max(len(name) - 1, 1))
        return name[:pos] + random.choice(["@", "#", "e", "o"]) + name[pos:]
    if r < 0.78:
        words = name.split()
        return words[0][0] + "." + " ".join(words[1:]) if len(words) > 1 else name
    if r < 0.90:
        return name + " " + random.choice(["SARL", "SA", "SUARL"])
    return name.replace("e", "e").replace("E", "E")  # accent noop for safety


# ══════════════════════════════════════════════════════════════════════════════
# PEOPLE / CONTACT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

TUN_FIRSTNAMES = [
    "Aymen", "Sonia", "Karim", "Nadia", "Mehdi", "Leila", "Yassine",
    "Amira", "Bilel", "Salma", "Rami", "Dorra", "Hichem", "Ines",
    "Tarek", "Rim", "Fares", "Olfa", "Adem", "Jihen", "Walid", "Yasmine",
    "Khaled", "Fatma", "Lotfi", "Maryem", "Slim", "Cyrine", "Mourad", "Emna",
    "Oussama", "Sirine", "Bassem", "Hajer", "Amine", "Wafa", "Saber", "Hela",
]

TUN_LASTNAMES_POOL = [
    "Trabelsi", "Ben Salah", "Mansouri", "Chaabane", "Zouari", "Gharbi",
    "Mejri", "Haddad", "Mrad", "Sghaier", "Bouzid", "Chaker", "Rekik",
    "Belhadj", "Oueslati", "Jlassi", "Turki", "Hamouda", "Laabidi",
    "Ferchiou", "Ben Romdhane", "Khalfallah", "Agrebi", "Hamdi",
]


def rand_person():
    return random.choice(TUN_FIRSTNAMES), random.choice(TUN_LASTNAMES_POOL)


# ══════════════════════════════════════════════════════════════════════════════
# DATA QUALITY HELPERS (shared)
# ══════════════════════════════════════════════════════════════════════════════

def rand_phone():
    if random.random() < 0.20: return None
    if random.random() < 0.05: return random.choice(["123", "N/A", "none"])
    ac  = random.choice(["71","72","73","74","75","20","22","25","50","55","98","99"])
    num = f"{random.randint(100,999)}{random.randint(100,999)}"
    r   = random.random()
    if r < 0.20: return f"+216 {ac} {num[:3]} {num[3:]}"
    if r < 0.40: return f"{ac}{num}"
    if r < 0.55: return f"0{ac}-{num[:3]}-{num[3:]}"
    if r < 0.70: return f"+216{ac}{num}"
    if r < 0.82: return f"{ac} {num[:3]} {num[3:]}"
    if r < 0.92: return f"00216{ac}{num}"
    return f"+216{ac} {num[:3]} {num[3:]}"


def rand_email(first: str, last: str, company: str):
    if random.random() < 0.10: return None
    if random.random() < 0.05:
        return random.choice(["contact@", "@company.tn", "no email", "N/A"])
    slug = company.lower().replace(" ", "").replace("'", "")[:10]
    return f"{first[0].lower()}.{last.lower().replace(' ','')}@{slug}.tn"


_CITIES = ["Tunis", "Sfax", "Sousse", "Kairouan", "Bizerte",
           "Gabes", "Ariana", "Gafsa", "Monastir", "Ben Arous"]
_TUNIS_V = ["Tunis", "tunis", "TUNIS", "Tunis City", "Tunis, Tunisia", "TN-Tunis"]


def rand_city():
    if random.random() < 0.08: return None
    c = random.choice(_CITIES)
    if c == "Tunis" and random.random() < 0.40:
        return random.choice(_TUNIS_V + [None])
    r = random.random()
    if r < 0.10: return c.lower()
    if r < 0.17: return c.upper()
    if r < 0.22: return f"{c}, Tunisia"
    return c


def rand_country():
    if random.random() < 0.05: return None
    return random.choice(["Tunisia","Tunisie","TN","tn","Tunisia","Tunisia","Tunisie"])


_INDUSTRY_GROUPS = [
    ["Technology","Technologie","IT"],
    ["Finance","Banque","Banking"],
    ["Healthcare","Sante","Sante"],
    ["Telecom","Telecommunications"],
    ["Public Sector","Secteur Public"],
    ["Education","Enseignement"],
    ["Retail","Commerce"],
    ["Manufacturing","Industrie"],
    ["Consulting","Conseil"],
    ["Energy","Energie"],
]


def rand_industry():
    if random.random() < 0.12: return None
    return random.choice(random.choice(_INDUSTRY_GROUPS))


_CLIENT_STATUSES = [
    "prospect","Prospect","PROSPECT",
    "active","client","Client","CLIENT",
    "lead","Lead",
]

_SIZES = {
    "large":  ["Large","Grand compte","Enterprise","large","500","1000"],
    "medium": ["Medium","PME","medium","100",None,"Small"],
    "small":  ["Small","small","TPE",None,"10"],
}


def rand_size(ctype: str):
    if random.random() < 0.10: return None
    return random.choice(_SIZES[ctype])


_CLIENT_NOTES = [
    None, None, None, "TODO", "TBD", "a completer",
    "Client important, suivi regulier requis.",
    "Contact via LinkedIn. Interesse par nos services cloud.",
    "Ancien client, a relancer pour renouvellement.",
    "Prospect froid. Prendre contact en Q2.",
    "RDV de presentation planifie pour la semaine prochaine.",
    "Reference: cabinet comptable partenaire.",
    "Gros potentiel. Budget confirme pour 2025.",
    "Mise en relation via CyberPark Elghazala.",
]


# ══════════════════════════════════════════════════════════════════════════════
# ACTIVITY DESCRIPTION POOLS (bilingual, sentiment-tagged for churn signals)
# ══════════════════════════════════════════════════════════════════════════════

_DESC_POOLS = {
    "call": {
        "pos": [
            "Appel de suivi. Client tres satisfait de la derniere livraison. Renouvellement contrat discute.",
            "Follow-up call confirmed budget extension. Contract signing scheduled next week.",
            "Client demande extension perimetre projet. Opportunite upsell estimee 80k TND.",
            "Appel avec DG. Excellent feedback sur notre solution. Recommande a filiale Sfax.",
            "Renewal discussion with IT director. Contract extended 2 years. Annual value 350k TND.",
            "Call - client confirmed satisfaction with cloud migration phase 1. Phase 2 approved.",
            "Appel decouverte nouveau contact DSI. Tres interesse offre cybersecurite. RDV planifie.",
            "Client a confirme signature imminente phase 2. Bon de commande en cours.",
            "Positive call - client recommends our services to their partner network.",
            "Client demande proposition projet data warehouse 2025. Budget pre-approuve 400k TND.",
            "Follow-up: client confirmed our platform selected over competitors. Kickoff next month.",
            "Appel responsable achat. Renouvellement annuel confirme. Budget augmente 15%.",
            "Client referred us to Orange Tunisie IT department. New opportunity identified.",
        ],
        "neu": [
            "Appel de routine. Pas de nouveaux projets ce trimestre. Relation stable.",
            "Brief check-in call. No immediate needs. Will follow up next quarter.",
            "Client mentionne contraintes budgetaires H2. Decision repoussee.",
            "Call - client satisfied with current services but no expansion planned.",
            "Routine follow-up. Client stable, no growth signals. Maintain relationship.",
            "Appel mensuel. Aucun besoin identifie. Prochaine relance dans 3 semaines.",
            "Brief call - client in transition period after internal reorganization.",
            "Appel informatif - client confirme poursuite du projet selon planning initial.",
        ],
        "neg": [
            "Relance client - 3eme tentative ce mois sans reponse. Client moins reactif.",
            "Call with procurement. Client mentioned evaluating InfoSys Tunisia. Price is concern.",
            "Client exprime insatisfaction delais livraison. Escalade manager demandee en urgence.",
            "Appel difficile - client compare tarifs avec concurrent local. Notre offre 30% plus chere.",
            "Client announced budget freeze for H2. Phase 2 of project unlikely to proceed.",
            "Client unhappy with last delivery. Timeline overrun 3 weeks. Risk of contract termination.",
            "Relance paiement facture 90 jours overdue. Client evoque problemes tresorerie.",
            "Client mentionned evaluation alternative solution open source. Licence trop chere.",
            "Call - client reducing IT budget 25%. Our contract under review.",
            "Client considering not renewing. Competitor offered 40% discount. Escalate to management.",
            "Appel avec nouveau DSI - ne connait pas notre solution. Champion precedent a quitte.",
        ],
    },
    "meeting": {
        "pos": [
            "Reunion de cadrage projet migration cloud. Architecture validee. POC planifie.",
            "Executive presentation - project approved by board. Project start confirmed Q2.",
            "Workshop transformation digitale. 3 nouveaux projets identifies.",
            "Meeting with CTO - excellent BI platform demo. Full deployment decision expected.",
            "Client steering committee review. All KPIs met. Scope extension discussed.",
            "Demo presented to decision committee. Unanimous positive feedback. Contract drafted.",
            "Reunion kick-off projet ERP avec equipe client (8 personnes). Planning valide.",
            "Presentation resultats projet phase 1 au COMEX. Satisfaction totale. Phase 2 validee.",
            "Workshop with IT team - identified 5 quick wins. Client very engaged.",
            "Reunion bilan annuel. Excellent ROI demontre. Budget 800k TND alloue pour 2025.",
            "Client agreed to be reference customer for our case studies.",
        ],
        "neu": [
            "Reunion de revue trimestrielle. Relation stable, pas de croissance notable.",
            "Quarterly review - status quo. Client satisfied but no expansion plans.",
            "Meeting to discuss contract renewal - client wants same scope, no price increase.",
            "Reunion bilan - projets en cours sur track mais pipeline futur vide.",
            "Meeting with new IT contact replacing departed champion. Relationship reset needed.",
            "Client review meeting - cautious, waiting for H2 budget confirmation.",
        ],
        "neg": [
            "Reunion difficile. Client mecontent des delais. Plan de remediation demande sous 48h.",
            "Meeting with client - they brought in 2 competing vendors for comparison demo.",
            "Client a reduit perimetre projet de 40%. Budget alloue a concurrent pour volet IA.",
            "Difficult steering committee. 3 open issues unresolved. Client threatening to escalate.",
            "Client evaluation - our solution scored 3/5, competitor 4/5. Need to improve proposal.",
            "Reunion tendue. Client cible des penalites de retard. Negociation en cours.",
            "Meeting - client revealed they already signed LOI with competitor.",
            "Quarterly review - client satisfaction dropped from 8 to 5. Action plan required.",
        ],
    },
    "email": {
        "pos": [
            "Envoi proposition commerciale 350k TND pour projet data warehouse. Accuse positif recu.",
            "Received signed contract. Project kickoff scheduled next Monday. Revenue: 280k TND.",
            "Client transmitted purchase order phase 2. Amount: 180k TND. Invoice to be issued.",
            "Email confirmation: client selected our solution over 3 competitors.",
            "Received glowing feedback from CTO. Testimonial request sent.",
            "Client email: recommends our services to their subsidiary in Sfax.",
            "Envoi rapport mensuel de performance. Client tres satisfait des resultats.",
            "Received payment 250k TND within 25 days. Best payment time this year.",
            "Email from client requesting proposal new AI chatbot project. Estimated 300k TND.",
            "Client confirmed attendance at our annual user conference.",
            "Recu demande de reference pour appel d'offres banque centrale. Client ambassadeur.",
        ],
        "neu": [
            "Email de suivi mensuel envoye. Pas de retour pour l'instant.",
            "Routine email update sent. No urgent issues. Will follow up end of month.",
            "Client responded to newsletter but no commercial interest expressed.",
            "Envoi rapport trimestriel. Reponse pro forma. Pas d'engagement commercial.",
            "Email exchange about renewal - client wants to delay decision 3 months.",
            "Monthly check-in email. Client stable but no growth initiatives planned.",
        ],
        "neg": [
            "Email relance sans reponse depuis 3 semaines. Client en periode de decision critique.",
            "Received email requesting 25% price reduction. Margin not viable at that level.",
            "Client sent formal complaint about project delivery delay. Legal clause invoked.",
            "3eme relance paiement facture envoyee. Montant en souffrance: 185k TND. Escalade finance.",
            "Received email: client putting project on hold due to internal restructuring.",
            "Client email mentions poor support response time. SLA breach documented.",
            "Received notification: client budget committee reduced IT spend 30%.",
            "Email from new procurement - existing contract terms under review. Risk flag raised.",
            "Client asked for ROI justification before renewal. Relationship at risk.",
        ],
    },
    "task": {
        "pos": [
            "Preparer proposition technique detaillee phase 2. Budget estime 450k TND.",
            "Prepare executive deck for steering committee presentation next Thursday.",
            "Rediger etude de cas client pour usage marketing. Client a donne son accord.",
            "Draft contract amendment for scope extension approved in last meeting.",
            "Mettre a jour CRM avec nouvelles informations contact DSI.",
            "Prepare reference letter as requested by client for their bank tender.",
            "Planifier atelier de demarrage projet avec equipe technique client.",
        ],
        "neu": [
            "Routine CRM update - log monthly activity for pipeline reporting.",
            "Mettre a jour fiche client avec nouvelles coordonnees.",
            "Schedule quarterly review call with account.",
            "Preparer recapitulatif projets en cours pour reunion hebdomadaire.",
            "Follow up on outstanding proposal sent 3 weeks ago.",
        ],
        "neg": [
            "Preparer plan de remediation suite retards livraison signales.",
            "Escalate client complaint to senior management. Urgent response required.",
            "Prepare competitive analysis vs InfoSys Tunisia proposal received by client.",
            "Investiguer cause retards SLA signales. Rapport client attendu sous 24h.",
            "Preparer contre-proposition tarifaire pour eviter perte client.",
            "Document client churn risk factors. Schedule executive review call this week.",
        ],
    },
    "note": {
        "pos": [
            "Note: client confirmed verbally our solution is their 1st choice.",
            "Important: client CTO expressed strong interest in AI/ML platform. Budget available.",
            "Note: client recommended us to Attijari Bank. New contact: Slim Jlassi, DSI.",
            "Note de suivi: client satisfait. Mention dans leur rapport annuel prevue.",
            "Client verbally agreed 2-year contract renewal. Formal email to follow.",
            "Note: client invited us to participate in their innovation day.",
            "Note: contact principal promu DG adjoint. Excellente nouvelle pour la relation.",
            "Client shared internal roadmap. 3 projects aligned with our capabilities.",
        ],
        "neu": [
            "Note: relation stable mais sans croissance ce trimestre.",
            "Note: client in internal reorganization. Decision-making paused.",
            "Observation: competitor activity increasing in client account.",
            "Note: client budget constraints limiting project approvals in H2.",
            "Note: client engagement declining. Last meeting was 2 months ago.",
        ],
        "neg": [
            "Note: client champion a quitte la societe. Nouveau contact moins favorable.",
            "Risk flag: client mentioned InfoSys Tunisia and local competitor same conversation.",
            "Note: client unhappy with last project delivery. Relationship at risk.",
            "Alert: client has not opened any of last 4 emails. Going cold.",
            "Note: client payment pattern deteriorating. Avg delay now 75 days vs 30 days.",
            "Risk: client reducing IT headcount. Our contract might be affected.",
        ],
    },
}

_HEALTH_SENTIMENT_WEIGHTS = {
    "healthy":  [0.70, 0.20, 0.10],
    "at_risk":  [0.25, 0.50, 0.25],
    "churning": [0.10, 0.30, 0.60],
}

_OUTCOME_VARIANTS = {
    "positive":           ["positive","Positive","POSITIVE","positif"],
    "neutral":            ["neutral","Neutral","neutre","N/A"],
    "negative":           ["negative","Negative","negatif","NEGATIVE"],
    "no_response":        ["no_response","No Response","sans reponse","pas de reponse"],
    "meeting_scheduled":  ["meeting_scheduled","RDV planifie","Meeting Scheduled"],
    "proposal_requested": ["proposal_requested","devis demande","Proposal Requested"],
    "lost_to_competitor": ["lost_to_competitor","perdu concurrent","Lost to Competitor"],
    "follow_up_required": ["follow_up_required","relance necessaire","Follow Up Required"],
    "decision_pending":   ["decision_pending","decision en attente","Decision Pending"],
    "contract_signed":    ["contract_signed","contrat signe","Contract Signed"],
}

_OUTCOME_HEALTH_POOLS = {
    "healthy":  (["positive"]*35 + ["meeting_scheduled"]*20 + ["proposal_requested"]*15 +
                 ["contract_signed"]*10 + ["neutral"]*10 + ["follow_up_required"]*7 + ["decision_pending"]*3),
    "churning": (["negative"]*30 + ["no_response"]*25 + ["lost_to_competitor"]*20 +
                 ["neutral"]*10 + ["follow_up_required"]*10 + ["positive"]*5),
    "at_risk":  (["neutral"]*35 + ["follow_up_required"]*25 + ["no_response"]*15 +
                 ["negative"]*10 + ["positive"]*10 + ["decision_pending"]*5),
}


def rand_activity_desc(atype: str, health: str):
    if random.random() < 0.20:
        return random.choice([None, None, "TODO", "a remplir"])
    pool = _DESC_POOLS[atype]
    sentiment = random.choices(["pos", "neu", "neg"],
                               weights=_HEALTH_SENTIMENT_WEIGHTS[health])[0]
    return random.choice(pool[sentiment])


def rand_outcome(health: str):
    outcome = random.choice(_OUTCOME_HEALTH_POOLS[health])
    if random.random() < 0.03:
        return None
    return random.choice(_OUTCOME_VARIANTS[outcome])


def rand_duration(atype: str):
    if atype in ("email", "note"):
        return None
    if random.random() < 0.25:
        return None
    if random.random() < 0.03:
        return random.choice(["1h30", "90 minutes", "une heure", "2h"])
    base = {
        "call":    random.randint(5, 60),
        "meeting": random.randint(30, 180),
        "task":    random.randint(15, 120),
    }[atype]
    if random.random() < 0.02: return -base
    if random.random() < 0.01: return base + random.randint(500, 900)
    return base


# ══════════════════════════════════════════════════════════════════════════════
# DEAL / INVOICE DIRTY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

DEAL_TITLES = [
    "Developpement plateforme BI", "Migration cloud AWS",
    "Implementation ERP", "Audit securite informatique",
    "Developpement application mobile", "Refonte site web",
    "Integration API", "Mise en place CRM",
    "Formation et certification cloud",
    "Deploiement infrastructure DevOps",
    "Developpement chatbot IA", "Analyse de donnees",
    "Consulting transformation digitale",
    "Maintenance et support applicatif",
    "Developpement tableau de bord",
    "Migration base de donnees", "Audit RGPD",
    "Mise en place data warehouse",
    "Developpement solution IoT",
    "Implementation solution cybersecurite",
]

_SALES_REPS = {
    2023: ["Aymen Trabelsi", "Sonia Ben Salah"],
    2024: ["Aymen Trabelsi", "Sonia Ben Salah", "Karim Mansouri", "Nadia Chaabane"],
    2025: ["Aymen Trabelsi", "Sonia Ben Salah", "Karim Mansouri", "Nadia Chaabane",
           "Mehdi Gharbi", "Leila Zouari"],
    2026: ["Aymen Trabelsi", "Sonia Ben Salah", "Karim Mansouri", "Nadia Chaabane",
           "Mehdi Gharbi", "Leila Zouari"],
}

_DEAL_CFG = {
    2023: dict(n=1500, small_lo=5_000,  small_hi=50_000,  large_lo=50_000,  large_hi=200_000,  large_p=0.10, won_p=0.28, lost_p=0.35),
    2024: dict(n=2800, small_lo=8_000,  small_hi=80_000,  large_lo=80_000,  large_hi=500_000,  large_p=0.20, won_p=0.38, lost_p=0.28),
    2025: dict(n=3000, small_lo=10_000, small_hi=100_000, large_lo=100_000, large_hi=800_000,  large_p=0.30, won_p=0.50, lost_p=0.22),
    2026: dict(n=700,  small_lo=15_000, small_hi=120_000, large_lo=120_000, large_hi=600_000,  large_p=0.35, won_p=0.55, lost_p=0.15),
}

_OPEN_STAGES  = ["prospecting", "qualification", "proposal", "negotiation"]
_ALL_STAGES   = _OPEN_STAGES + ["closed_won", "closed_lost"]

_STAGE_V = {
    "prospecting":   ["prospecting","Prospecting","PROSPECTING","prospection"],
    "qualification": ["qualification","Qualification","QUALIFICATION","qualify"],
    "proposal":      ["proposal","Proposal","PROPOSAL","Propsal","devis","offre"],
    "negotiation":   ["negotiation","Negotiation","NEGOTIATION","negociation"],
    "closed_won":    ["closed_won","Closed Won","Closed-Won","Won"],
    "closed_lost":   ["closed_lost","Closed Lost","Closed-Lost","Lost"],
}

_STATUS_V = {
    "won":  ["won","Won","WIN","closed won","Closed-Won","gagne"],
    "lost": ["lost","Lost","perdu","LOST","Closed-Lost"],
    "open": ["open","en cours","Open","in progress","In Progress","en attente"],
}

_PROB_BASE = {
    "prospecting":15,"qualification":30,"proposal":50,
    "negotiation":75,"closed_won":100,"closed_lost":0,
}

_DEAL_NOTES = [
    None, None,
    "Client interesse par migration AWS. Budget confirme 150k TND. Decision attendue fin mars.",
    "RDV avec DSI Tunisie Telecom. Concurrent InfoSys Tunisia. Notre offre 20% moins chere.",
    "Prospect froid. Relancer en Q2 apres leur budget annuel.",
    "Deuxieme contact. Envoyer proposition detaillee avant fin de semaine.",
    "Client a demande une demo. Seance en ligne planifiee la semaine prochaine.",
    "Negociation en cours. Client souhaite reduction de 15%.",
    "Contrat signe. En attente de bon de commande officiel.",
    "Perdu face a concurrent local. Prix trop eleve selon client.",
    "Client a reporte la decision au prochain trimestre.",
    "Proposition envoyee. Relance prevue dans 2 semaines.",
    "Interest confirmed. Budget approved for next quarter.",
    "Lost to competitor. Client chose cheaper local option.",
    "Follow up required after summer holidays.",
    "Budget confirmed. Awaiting final procurement approval from CFO.",
    "Client tres interesse. Demo reussie. Prochaine etape: signature.",
    "Appel decouverte positif. Envoyer cas clients similaires.",
    "En attente validation budget par direction financiere.",
    "Offre technique validee. Negociation tarifaire en cours.",
    "Client mentionne evaluation InfoSys Tunisia comme concurrent principal.",
    "Risque de perte - client insatisfait delais precedent projet.",
]

_SERVICE_TYPES = ["IT Consulting","Developpement","Infrastructure","Formation","Support","Audit"]


def _deal_value_dirty(v: float):
    r = random.random()
    if r < 0.03: return None
    if r < 0.05: return random.choice(["N/A","TBD","a confirmer"])
    if r < 0.10: return str(-int(v))
    vi = int(v)
    r2 = random.random()
    if r2 < 0.30: return str(vi)
    if r2 < 0.50: return f"{vi:,}"
    if r2 < 0.63: return f"{vi:,}".replace(",",".") + " TND"
    if r2 < 0.73: return f"{vi//1000}k"
    if r2 < 0.83: return f"{vi:,}".replace(","," ")
    if r2 < 0.88:
        text_map = {
            range(4500,  5500):  "cinq mille",
            range(9500,  10500): "dix mille",
            range(19500, 20500): "vingt mille",
            range(49500, 50500): "cinquante mille",
        }
        for rng, txt in text_map.items():
            if vi in rng:
                return txt
    return str(vi)


def _deal_currency_dirty():
    r = random.random()
    if r < 0.08: return None
    return random.choice(["TND","DT","tnd","dt","TND","TND","DT","EUR","USD","TND","TND"])


def _deal_prob_dirty(stage: str):
    v = _PROB_BASE.get(stage, 50) + random.randint(-10, 10)
    v = max(0, min(v, 100))
    if random.random() < 0.15: return None
    if random.random() < 0.02: return str(random.randint(101, 200))
    r = random.random()
    if r < 0.70: return str(v)
    if r < 0.80: return f"{v}%"
    if r < 0.90: return str(round(v / 100, 2))
    return f">{(v // 10) * 10}"


_INV_NOTES = [
    None, None, None,
    "Facture 1/3 - Projet migration cloud STEG. Tranche initiale 30%.",
    "Invoice for Q2 maintenance contract. PO number: TT-2024-8821.",
    "Avoir suite annulation partielle du projet.",
    "Facture solde - Developpement plateforme BI. Livraison finale acceptee.",
    "Acompte 50% - Contrat annuel support applicatif.",
    "Facture mensuelle maintenance.",
    "Invoice for cybersecurity audit - Phase 1 completed.",
    "Regularisation facture N-1. Avoir emis en contrepartie.",
    "Retenue de garantie 10% - Liberation apres recette definitive.",
    "Frais de deplacement inclus. Voir detail en annexe.",
    "Contrat cadre 2025. Facture trimestrielle T2.",
]


def _inv_number_dirty(base: str):
    if random.random() < 0.02: return None
    if random.random() < 0.03:
        return random.choice([
            base.replace("JBM-","JBM/").replace("-","/",1),
            "INV-" + base.split("-")[-1],
            base.split("-")[0]+"/"+base.split("-")[1]+"/"+base.split("-")[2],
        ])
    return base


def _inv_tax_dirty():
    if random.random() < 0.05: return None
    r = random.random()
    if r < 0.60: return 19
    if r < 0.75: return 0.19
    if r < 0.85: return "19%"
    if r < 0.92: return "19 %"
    return random.choice([20,15,0])


def _inv_currency_dirty():
    if random.random() < 0.05: return None
    return random.choice(["TND","DT","tnd","TND","TND","EUR"])


def _inv_amount_dirty(v: float):
    r = random.random()
    if r < 0.01:  return None
    if r < 0.02:  return f"{v/1000:.0f}k TND"
    if r < 0.025: return -abs(round(v, 2))
    return round(v, 2)


def _inv_method_dirty():
    if random.random() < 0.20: return None
    return random.choice([
        "virement","Virement bancaire","bank transfer","Bank Transfer",
        "cheque","Cheque","check","Check",
        "especes","cash","Cash","Especes",
    ])


_PAY_PATTERNS = {
    "large":  dict(pay_lo=30, pay_hi=45, paid_p=0.95, overdue_p=0.00),
    "medium": dict(pay_lo=45, pay_hi=60, paid_p=0.85, overdue_p=0.05),
    "small":  dict(pay_lo=60, pay_hi=90, paid_p=0.70, overdue_p=0.15),
}

_INV_STATUS_V = {
    "paid":      ["paid","Paid","PAID","paye","paye","Payee"],
    "pending":   ["unpaid","pending","Pending","en attente","In Progress"],
    "overdue":   ["overdue","Overdue","en retard","late","OVERDUE"],
    "cancelled": ["cancelled","annule","annule","Cancelled","CANCELLED"],
}


# ══════════════════════════════════════════════════════════════════════════════
# PROGRESS TRACKER
# ══════════════════════════════════════════════════════════════════════════════

def _progress(label: str, n: int, total: int) -> None:
    if n % 10_000 == 0:
        print(f"    {label}: {n:>7,} / {total:,} rows ...")


# ══════════════════════════════════════════════════════════════════════════════
# FILE 1: raw_clients.xlsx  (~100,000 rows)
# ══════════════════════════════════════════════════════════════════════════════
# Each unique (company, contact) pair = 1 clean record.
# Each pair appears ~150-220 times (snapshots, imports, updates, duplicates).
# ~600 unique contacts across 80 companies => ~100,000 raw rows.

_RECORD_SOURCES = [
    "linkedin_export","manual_entry","trade_show_tunis2023","trade_show_tunis2024",
    "email_campaign","referral","website_form","phone_inquiry","crm_import",
    "partner_referral",
]

_RECORD_TYPE_POOL  = (["snapshot"] * 60 + ["update"] * 20 +
                      ["duplicate_import"] * 15 + ["new_entry"] * 4 +
                      ["merge_candidate"] * 1)


def build_clients() -> pd.DataFrame:
    TARGET = 100_000
    rows   = []
    cid    = 1

    for company in ALL_COMPANIES:
        ctype = COMPANY_TYPE[company]
        n_contacts = (
            random.randint(12, 18) if ctype == "large"  else
            random.randint(4,  7)  if ctype == "medium" else
            random.randint(2,  4)
        )
        for _ in range(n_contacts):
            first, last = rand_person()
            email   = rand_email(first, last, company)
            phone   = rand_phone()
            city    = rand_city()
            country = rand_country()
            ind     = rand_industry()
            size    = rand_size(ctype)
            status  = random.choice(_CLIENT_STATUSES)
            notes   = random.choice(_CLIENT_NOTES)

            n_rows = (
                random.randint(180, 260) if ctype == "large"  else
                random.randint(100, 150) if ctype == "medium" else
                random.randint(60,  100)
            )
            for ri in range(n_rows):
                cname = company if ri == 0 else dirty_name(company, prob=0.80)
                if random.random() < 0.05:
                    pos   = random.randint(1, max(len(cname) - 1, 1))
                    cname = cname[:pos] + random.choice(["###","!!!","***"]) + cname[pos:]

                rows.append({
                    "client_id":         f"CLI-{cid:06d}",
                    "company_name":      cname,
                    "contact_firstname": first,
                    "contact_lastname":  last,
                    "contact_email":     email,
                    "contact_phone":     phone,
                    "city":              city,
                    "country":           country,
                    "industry":          ind,
                    "company_size":      size,
                    "status":            status,
                    "created_date":      messy_date(rand_date(), null_prob=0.03),
                    "source":            random.choice(_RECORD_SOURCES),
                    "notes":             notes,
                    "record_source":     random.choice(_RECORD_SOURCES),
                    "record_type":       random.choice(_RECORD_TYPE_POOL),
                })
                cid   += 1
                _progress("clients", len(rows), TARGET)

    df = pd.DataFrame(rows)
    df = df.iloc[np.random.permutation(len(df))].reset_index(drop=True)
    return df


# ══════════════════════════════════════════════════════════════════════════════
# FILE 2: raw_deals.xlsx  (~80,000 rows)
# ══════════════════════════════════════════════════════════════════════════════
# 8,000 base deals  x  ~10 lifecycle events each.

def _gen_base_deals() -> list:
    """Generate 8,000 base deal records."""
    base, did = [], 1
    for year, cfg in _DEAL_CFG.items():
        reps   = _SALES_REPS[year]
        won_p  = cfg["won_p"]
        lost_p = cfg["lost_p"]
        for _ in range(cfg["n"]):
            created = rand_date_seasonal(year)
            outcome = random.choices(["won","lost","open"],
                                     weights=[won_p, lost_p, 1-won_p-lost_p])[0]
            if outcome == "won":
                final_stage = "closed_won"
                close_date  = rand_date(created, min(created+timedelta(180), PERIOD_END))
            elif outcome == "lost":
                final_stage = "closed_lost"
                close_date  = rand_date(created, min(created+timedelta(180), PERIOD_END))
            else:
                final_stage = random.choice(_OPEN_STAGES)
                close_date  = None

            is_large = random.random() < cfg["large_p"]
            lo = cfg["large_lo"] if is_large else cfg["small_lo"]
            hi = cfg["large_hi"] if is_large else cfg["small_hi"]
            value = round(random.uniform(lo, hi) / 500) * 500

            company = random.choice(ALL_COMPANIES)
            rep     = random.choice(reps)
            if random.random() < 0.05: rep = None

            base.append({
                "deal_id":     f"DEAL-{did:06d}",
                "company":     company,
                "title":       random.choice(DEAL_TITLES),
                "value":       value,
                "year":        year,
                "created":     created,
                "close_date":  close_date,
                "final_stage": final_stage,
                "outcome":     outcome,
                "rep":         rep,
            })
            did += 1
    return base


def build_deals() -> pd.DataFrame:
    TARGET = 80_000
    base   = _gen_base_deals()
    rows   = []

    for deal in base:
        stage_sequence = _OPEN_STAGES[:]

        # Build stage progression up to final stage
        if deal["final_stage"] in ("closed_won","closed_lost"):
            n_open = random.randint(2, 4)
            stages = stage_sequence[:n_open] + [deal["final_stage"]]
        else:
            idx    = _OPEN_STAGES.index(deal["final_stage"])
            stages = stage_sequence[: idx + 1]

        current_value = deal["value"]
        cur_date      = deal["created"]
        prev_stage    = None

        # Stage-change events
        for i, stage in enumerate(stages):
            cur_date = min(cur_date + timedelta(days=random.randint(5, 30)), PERIOD_END)
            outcome  = "won" if stage == "closed_won" else "lost" if stage == "closed_lost" else "open"
            rows.append({
                "deal_id":        deal["deal_id"],
                "company_name":   dirty_name(deal["company"], prob=0.15),
                "deal_title":     deal["title"],
                "deal_value":     _deal_value_dirty(current_value),
                "currency":       _deal_currency_dirty(),
                "stage":          random.choice(_STAGE_V[stage]),
                "status":         random.choice(_STATUS_V[outcome]),
                "created_date":   messy_date(deal["created"], null_prob=0.01),
                "close_date":     messy_date(deal["close_date"]) if stage in ("closed_won","closed_lost") else None,
                "assigned_to":    deal["rep"],
                "service_type":   random.choice(_SERVICE_TYPES + [None]),
                "probability":    _deal_prob_dirty(stage),
                "notes":          random.choice(_DEAL_NOTES),
                "source":         random.choice(["LinkedIn","Referral","Event","Appel entrant","Partenaire",None]),
                "event_type":     "deal_created" if i == 0 else "stage_updated",
                "previous_stage": prev_stage,
                "previous_value": None,
            })
            prev_stage = stage

        # Value-update events (0-2)
        for _ in range(random.randint(0, 2)):
            old_v = current_value
            current_value = round(current_value * random.uniform(0.80, 1.20) / 500) * 500
            rows.append({
                "deal_id":        deal["deal_id"],
                "company_name":   dirty_name(deal["company"], prob=0.10),
                "deal_title":     deal["title"],
                "deal_value":     _deal_value_dirty(current_value),
                "currency":       _deal_currency_dirty(),
                "stage":          random.choice(_STAGE_V[stages[-1]]),
                "status":         random.choice(_STATUS_V[deal["outcome"]]),
                "created_date":   messy_date(deal["created"], null_prob=0.01),
                "close_date":     messy_date(deal["close_date"]),
                "assigned_to":    deal["rep"],
                "service_type":   random.choice(_SERVICE_TYPES + [None]),
                "probability":    _deal_prob_dirty(stages[-1]),
                "notes":          random.choice(_DEAL_NOTES),
                "source":         random.choice(["LinkedIn","Referral","Event",None]),
                "event_type":     "value_updated",
                "previous_stage": None,
                "previous_value": _deal_value_dirty(old_v),
            })

        # Note events (1-3)
        for _ in range(random.randint(1, 3)):
            rows.append({
                "deal_id":        deal["deal_id"],
                "company_name":   dirty_name(deal["company"], prob=0.10),
                "deal_title":     deal["title"],
                "deal_value":     _deal_value_dirty(current_value),
                "currency":       _deal_currency_dirty(),
                "stage":          random.choice(_STAGE_V[stages[-1]]),
                "status":         random.choice(_STATUS_V[deal["outcome"]]),
                "created_date":   messy_date(deal["created"], null_prob=0.01),
                "close_date":     messy_date(deal["close_date"]),
                "assigned_to":    deal["rep"],
                "service_type":   None,
                "probability":    None,
                "notes":          random.choice(_DEAL_NOTES),
                "source":         None,
                "event_type":     "note_added",
                "previous_stage": None,
                "previous_value": None,
            })

        # Pipeline snapshot events (2-3)
        snap_end = min(cur_date + timedelta(days=60), PERIOD_END)
        for _ in range(random.randint(2, 3)):
            rows.append({
                "deal_id":        deal["deal_id"],
                "company_name":   dirty_name(deal["company"], prob=0.10),
                "deal_title":     deal["title"],
                "deal_value":     _deal_value_dirty(current_value),
                "currency":       _deal_currency_dirty(),
                "stage":          random.choice(_STAGE_V[stages[-1]]),
                "status":         random.choice(_STATUS_V[deal["outcome"]]),
                "created_date":   messy_date(deal["created"]),
                "close_date":     messy_date(deal["close_date"]),
                "assigned_to":    deal["rep"],
                "service_type":   random.choice(_SERVICE_TYPES + [None]),
                "probability":    _deal_prob_dirty(stages[-1]),
                "notes":          random.choice(_DEAL_NOTES),
                "source":         "pipeline_snapshot",
                "event_type":     "pipeline_snapshot",
                "previous_stage": None,
                "previous_value": None,
            })

        # Assigned-changed event (20%)
        if random.random() < 0.20 and deal["rep"]:
            new_rep = random.choice(_SALES_REPS[deal["year"]])
            rows.append({
                "deal_id":        deal["deal_id"],
                "company_name":   dirty_name(deal["company"], prob=0.10),
                "deal_title":     deal["title"],
                "deal_value":     _deal_value_dirty(current_value),
                "currency":       _deal_currency_dirty(),
                "stage":          random.choice(_STAGE_V[stages[-1]]),
                "status":         random.choice(_STATUS_V[deal["outcome"]]),
                "created_date":   messy_date(deal["created"]),
                "close_date":     messy_date(deal["close_date"]),
                "assigned_to":    new_rep,
                "service_type":   None,
                "probability":    None,
                "notes":          f"Reassigned from {deal['rep']} to {new_rep}",
                "source":         None,
                "event_type":     "assigned_changed",
                "previous_stage": None,
                "previous_value": None,
            })

        # Duplicate event (25%)
        if random.random() < 0.25:
            rows.append({
                "deal_id":        deal["deal_id"],
                "company_name":   dirty_name(deal["company"], prob=0.40),
                "deal_title":     deal["title"],
                "deal_value":     _deal_value_dirty(deal["value"]),
                "currency":       _deal_currency_dirty(),
                "stage":          random.choice(_STAGE_V[stages[0]]),
                "status":         random.choice(_STATUS_V["open"]),
                "created_date":   messy_date(deal["created"]),
                "close_date":     None,
                "assigned_to":    deal["rep"],
                "service_type":   None,
                "probability":    None,
                "notes":          None,
                "source":         "crm_import",
                "event_type":     "duplicate",
                "previous_stage": None,
                "previous_value": None,
            })

        # Reopened (15% of lost deals)
        if deal["final_stage"] == "closed_lost" and random.random() < 0.15:
            reopen = min(cur_date + timedelta(days=random.randint(30,180)), PERIOD_END)
            rows.append({
                "deal_id":        deal["deal_id"],
                "company_name":   dirty_name(deal["company"], prob=0.10),
                "deal_title":     deal["title"],
                "deal_value":     _deal_value_dirty(current_value * random.uniform(0.8, 1.2)),
                "currency":       _deal_currency_dirty(),
                "stage":          random.choice(_STAGE_V["qualification"]),
                "status":         random.choice(_STATUS_V["open"]),
                "created_date":   messy_date(deal["created"]),
                "close_date":     None,
                "assigned_to":    deal["rep"],
                "service_type":   None,
                "probability":    "20",
                "notes":          "Opportunite re-ouverte suite a nouveau contact.",
                "source":         None,
                "event_type":     "reopened",
                "previous_stage": "closed_lost",
                "previous_value": None,
            })

        _progress("deals", len(rows), TARGET)

    df = pd.DataFrame(rows)
    df = df.iloc[np.random.permutation(len(df))].reset_index(drop=True)
    return df


# ══════════════════════════════════════════════════════════════════════════════
# FILE 3: raw_activities.xlsx  (~200,000 rows — NEW FILE)
# ══════════════════════════════════════════════════════════════════════════════

_ACT_TYPE_WEIGHTS = [35, 30, 15, 12, 8]  # call, email, meeting, task, note
_ACT_TYPES        = ["call","email","meeting","task","note"]

_ACT_YEAR_CFG = {
    2023: 35_000,
    2024: 70_000,
    2025: 80_000,
    2026: 15_000,
}

_ACT_SOURCES = [
    "crm_manual","email_sync","calendar_sync","phone_system",
    "mobile_app","web_portal","crm_import",
]


def build_activities() -> pd.DataFrame:
    TARGET = 200_000
    rows   = []
    aid    = 1
    # Pool of recent IDs for duplicate injection
    recent_aids: list = []

    for year, n_rows in _ACT_YEAR_CFG.items():
        reps = _SALES_REPS[year]
        for _ in range(n_rows):
            atype    = random.choices(_ACT_TYPES, weights=_ACT_TYPE_WEIGHTS)[0]
            company  = random.choices(ALL_COMPANIES, weights=COMPANY_WEIGHTS)[0]
            health   = COMPANY_HEALTH[company]
            first, last = rand_person()

            act_date = rand_date_activity(year)

            # created_at (3% before activity_date = illogical)
            if random.random() < 0.03:
                created_at = act_date - timedelta(days=random.randint(1, 7))
            else:
                created_at = act_date + timedelta(days=random.randint(0, 4))

            # 3% future dates for activity_date
            if random.random() < 0.03:
                act_date = PERIOD_END + timedelta(days=random.randint(1, 60))

            # Deal reference (60% linked)
            deal_ref = (f"DEAL-{random.randint(1, 8000):06d}"
                        if random.random() < 0.60 else None)

            # Activity ID: 4% duplicate
            if random.random() < 0.04 and recent_aids:
                act_id = random.choice(recent_aids[-50:])
            else:
                act_id = f"ACT-{aid:07d}"
                recent_aids.append(act_id)
                aid += 1

            rows.append({
                "activity_id":       act_id,
                "company_name":      dirty_name(company, prob=0.20),
                "contact_name":      f"{first} {last}",
                "activity_type":     atype,
                "activity_date":     messy_date(act_date, null_prob=0.02),
                "duration_minutes":  rand_duration(atype),
                "outcome":           rand_outcome(health),
                "description":       rand_activity_desc(atype, health),
                "assigned_to":       random.choice(reps) if random.random() > 0.05 else None,
                "deal_reference":    deal_ref,
                "created_at":        messy_date(created_at, null_prob=0.01),
                "source":            random.choice(_ACT_SOURCES + [None]),
            })
            _progress("activities", len(rows), TARGET)

    df = pd.DataFrame(rows)
    # No full shuffle to save memory; rows are already random-order within years
    return df


# ══════════════════════════════════════════════════════════════════════════════
# FILE 4: raw_invoices.xlsx  (~30,000 rows)
# ══════════════════════════════════════════════════════════════════════════════
# 2,000 base invoices  x  ~15 lifecycle events each.

_INV_BASE_CFG = {
    2023: dict(n=400,  lo=3_000,  hi=150_000),
    2024: dict(n=800,  lo=5_000,  hi=300_000),
    2025: dict(n=1100, lo=8_000,  hi=600_000),
    2026: dict(n=200,  lo=10_000, hi=500_000),
}


def _gen_base_invoices() -> list:
    inv_counters = {y: 1 for y in _INV_BASE_CFG}
    base = []
    iid  = 1

    for year, cfg in _INV_BASE_CFG.items():
        for _ in range(cfg["n"]):
            issue   = rand_date_seasonal(year)
            due     = issue + timedelta(days=random.randint(30, 60))
            company = random.choice(ALL_COMPANIES)
            ctype   = COMPANY_TYPE[company]
            pat     = _PAY_PATTERNS[ctype]

            r_status = random.random()
            if r_status < 0.05:
                base_status  = "cancelled"
                payment_date = None
            elif random.random() < pat["paid_p"]:
                base_status  = "paid"
                payment_date = issue + timedelta(
                    days=random.randint(pat["pay_lo"], pat["pay_hi"]))
            else:
                base_status  = "overdue" if random.random() < pat["overdue_p"] else "pending"
                payment_date = None

            subtotal   = round(random.uniform(cfg["lo"], cfg["hi"]) / 100) * 100
            tax_rate   = 19.0
            tax_amount = round(subtotal * tax_rate / 100, 2)
            total      = round(subtotal + tax_amount, 2)

            # Math errors (8%)
            if random.random() < 0.08:
                err = random.choice(["wrong_tax","swap","off_by"])
                if err == "wrong_tax":
                    tax_amount = round(subtotal * random.choice([0.20,0.15,0.10]), 2)
                elif err == "swap":
                    subtotal, total = total, subtotal
                else:
                    total = round(total * random.uniform(0.88, 1.12), 2)

            inv_base = f"JBM-{year}-{inv_counters[year]:04d}"
            inv_counters[year] += 1

            base.append({
                "invoice_id":    f"INV-{iid:06d}",
                "inv_number":    _inv_number_dirty(inv_base),
                "inv_pool_num":  inv_base,   # clean number for duplicate injection
                "company":       company,
                "deal_ref":      f"DEAL-{random.randint(1,8000):06d}" if random.random() < 0.70 else None,
                "issue":         issue,
                "due":           due,
                "payment_date":  payment_date,
                "base_status":   base_status,
                "subtotal":      subtotal,
                "tax_rate":      tax_rate,
                "tax_amount":    tax_amount,
                "total":         total,
                "payment_method": _inv_method_dirty() if base_status == "paid" else None,
            })
            iid += 1
    return base


def build_invoices() -> pd.DataFrame:
    TARGET = 30_000
    base   = _gen_base_invoices()
    rows   = []
    inv_num_pool: list = []

    for inv in base:
        status     = inv["base_status"]
        total_amt  = inv["total"]
        paid_so_far = 0.0

        inv_num_pool.append(inv["inv_pool_num"])

        # --- Shared row builder -----------------------------------------------
        def _row(event_type, event_date, amt_paid=None, running_bal=None,
                 status_override=None):
            # 3% duplicate invoice numbers
            inv_num = inv["inv_number"]
            if random.random() < 0.03 and len(inv_num_pool) > 1:
                inv_num = _inv_number_dirty(random.choice(inv_num_pool[:-1]))

            raw_issue = inv["issue"]
            raw_due   = inv["due"]
            raw_pay   = inv["payment_date"]

            if raw_pay and random.random() < 0.04:
                raw_pay = raw_issue - timedelta(days=random.randint(1, 20))
            if random.random() < 0.03:
                raw_due = raw_issue - timedelta(days=random.randint(1, 15))
            if status == "paid" and random.random() < 0.05:
                raw_pay = None

            st = status_override or status
            return {
                "invoice_id":     inv["invoice_id"],
                "invoice_number": inv_num,
                "company_name":   dirty_name(inv["company"], prob=0.15),
                "deal_reference": inv["deal_ref"],
                "issue_date":     messy_date(raw_issue, null_prob=0.01),
                "due_date":       messy_date(raw_due,   null_prob=0.01),
                "payment_date":   messy_date(raw_pay),
                "status":         (random.choice(_INV_STATUS_V[st])
                                   if random.random() > 0.03 else None),
                "subtotal":       _inv_amount_dirty(inv["subtotal"]),
                "tax_rate":       _inv_tax_dirty(),
                "tax_amount":     _inv_amount_dirty(inv["tax_amount"]),
                "total_amount":   _inv_amount_dirty(total_amt),
                "currency":       _inv_currency_dirty(),
                "payment_method": inv["payment_method"] if event_type in ("full_payment","partial_payment") else (
                    _inv_method_dirty() if random.random() < 0.15 else None),
                "notes":          random.choice(_INV_NOTES),
                "event_type":     event_type,
                "event_date":     messy_date(event_date),
                "amount_paid":    round(amt_paid, 2) if amt_paid is not None else None,
                "running_balance": round(running_bal, 2) if running_bal is not None else None,
            }

        # invoice_created
        rows.append(_row("invoice_created", inv["issue"]))
        # invoice_sent
        rows.append(_row("invoice_sent", inv["issue"] + timedelta(days=random.randint(1, 3))))

        ev_date = inv["issue"] + timedelta(days=5)

        if status == "cancelled":
            rows.append(_row("credit_note", ev_date + timedelta(days=5)))
            rows.append(_row("cancelled",   ev_date + timedelta(days=10)))

        elif status == "paid":
            # Optional partial payment (20%)
            if random.random() < 0.20:
                partial = round(total_amt * random.uniform(0.30, 0.60), 2)
                paid_so_far += partial
                rows.append(_row("partial_payment",
                                 inv["issue"] + timedelta(days=random.randint(20, 35)),
                                 amt_paid=partial, running_bal=total_amt - paid_so_far))
            # Optional reminder (30% of paid invoices had a reminder)
            if random.random() < 0.30:
                rows.append(_row("reminder_1", inv["due"] - timedelta(days=5)))
            # Full payment
            remaining = total_amt - paid_so_far
            rows.append(_row("full_payment", inv["payment_date"] or inv["due"],
                             amt_paid=remaining, running_bal=0.0))
            # AR snapshots (8-13 monthly)
            for s in range(random.randint(8, 13)):
                snap = inv["issue"] + timedelta(days=30 * (s + 1))
                if snap > PERIOD_END: break
                rows.append(_row("ar_snapshot", snap))

        elif status == "overdue":
            rows.append(_row("reminder_1", inv["due"]))
            if random.random() < 0.80:
                rows.append(_row("reminder_2", inv["due"] + timedelta(days=15)))
            if random.random() < 0.60:
                rows.append(_row("reminder_3", inv["due"] + timedelta(days=30)))
            if random.random() < 0.10:
                rows.append(_row("disputed",   inv["due"] + timedelta(days=random.randint(10,45))))
            for s in range(random.randint(12, 22)):
                snap = inv["issue"] + timedelta(days=30 * (s + 1))
                if snap > PERIOD_END: break
                rows.append(_row("ar_snapshot", snap))

        else:  # pending
            if random.random() < 0.50:
                rows.append(_row("reminder_1", inv["due"]))
            for s in range(random.randint(8, 16)):
                snap = inv["issue"] + timedelta(days=30 * (s + 1))
                if snap > PERIOD_END: break
                rows.append(_row("ar_snapshot", snap))

        _progress("invoices", len(rows), TARGET)

    df = pd.DataFrame(rows)
    df = df.iloc[np.random.permutation(len(df))].reset_index(drop=True)
    return df


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def _save(df: pd.DataFrame, filename: str) -> None:
    path = os.path.join(DATA_DIR, filename)
    df.to_excel(path, index=False, engine="openpyxl")
    print(f"  {filename}: {len(df):>8,} rows saved")


def main():
    print("Generating raw ERP data for JBM Consulting (v2 - large volume)...\n")

    print("  [1/4] Building raw_clients.xlsx ...")
    df_clients = build_clients()
    _save(df_clients, "raw_clients.xlsx")

    print("  [2/4] Building raw_deals.xlsx ...")
    df_deals = build_deals()
    _save(df_deals, "raw_deals.xlsx")

    print("  [3/4] Building raw_activities.xlsx ...")
    df_activities = build_activities()
    _save(df_activities, "raw_activities.xlsx")

    print("  [4/4] Building raw_invoices.xlsx ...")
    df_invoices = build_invoices()
    _save(df_invoices, "raw_invoices.xlsx")

    total = len(df_clients) + len(df_deals) + len(df_activities) + len(df_invoices)

    print(f"\n{'-'*50}")
    print(f"  Total raw rows: {total:,}")
    print(f"{'-'*50}")
    print(f"\n  Estimated clean rows after ETL:")
    print(f"  Unique companies : ~600")
    print(f"  Unique deals     : ~8,000")
    print(f"  Valid activities : ~80,000")
    print(f"  Unique invoices  : ~2,000")
    print()


if __name__ == "__main__":
    main()
