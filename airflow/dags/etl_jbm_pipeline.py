"""
etl_jbm_pipeline.py
JBM Consulting — Full ETL pipeline DAG

Flow:
  start
    ├─ extract_clients  → transform_clients  → load_clients
    ├─ extract_deals    → transform_deals    → load_deals
    ├─ extract_activities → transform_activities → load_activities
    └─ extract_invoices → transform_invoices → load_invoices
  populate_dim_date
  validate_warehouse
  end
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
from dateutil import parser as dtparser
from dotenv import load_dotenv
from rapidfuzz import fuzz, process
from sqlalchemy import create_engine, text

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv("/opt/airflow/.env")

DATA_DIR = Path("/opt/airflow/data")
STAGING_DIR = DATA_DIR / "staging"
STAGING_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@host.docker.internal:5432/erp_db",
)

log = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True)


def _ensure_warehouse(engine):
    """Create warehouse schema and all dimension/fact tables if they don't exist."""
    statements = [
        "CREATE SCHEMA IF NOT EXISTS warehouse",
        """
        CREATE TABLE IF NOT EXISTS warehouse.dim_client (
            client_id       SERIAL PRIMARY KEY,
            company_name    TEXT NOT NULL,
            phone           TEXT,
            email           TEXT,
            city            TEXT,
            country         TEXT DEFAULT 'Tunisie',
            industry        TEXT,
            status          TEXT,
            created_date    DATE,
            source_file     TEXT,
            loaded_at       TIMESTAMP DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS warehouse.fact_deals (
            deal_id             SERIAL PRIMARY KEY,
            deal_ref            TEXT UNIQUE,
            company_name        TEXT,
            title               TEXT,
            stage               TEXT,
            status              TEXT,
            value_tnd           NUMERIC(14,2),
            probability         NUMERIC(5,2),
            deal_size_category  TEXT,
            quarter             TEXT,
            days_to_close       INTEGER,
            created_date        DATE,
            closed_date         DATE,
            assigned_to         TEXT,
            loaded_at           TIMESTAMP DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS warehouse.fact_activities (
            activity_id     SERIAL PRIMARY KEY,
            source_id       TEXT,
            company_name    TEXT,
            contact_name    TEXT,
            activity_type   TEXT,
            activity_date   DATE,
            duration_min    INTEGER,
            outcome         TEXT,
            churn_signal    BOOLEAN DEFAULT FALSE,
            positive_signal BOOLEAN DEFAULT FALSE,
            description     TEXT,
            assigned_to     TEXT,
            deal_reference  TEXT,
            loaded_at       TIMESTAMP DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS warehouse.fact_revenue (
            revenue_id          SERIAL PRIMARY KEY,
            invoice_number      TEXT UNIQUE,
            company_name        TEXT,
            invoice_date        DATE,
            due_date            DATE,
            subtotal            NUMERIC(14,2),
            tax_amount          NUMERIC(14,2),
            total_amount        NUMERIC(14,2),
            amount_paid         NUMERIC(14,2) DEFAULT 0,
            status              TEXT,
            payment_delay_days  INTEGER,
            is_overdue          BOOLEAN DEFAULT FALSE,
            days_outstanding    INTEGER,
            loaded_at           TIMESTAMP DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS warehouse.dim_date (
            date_id         INTEGER PRIMARY KEY,
            full_date       DATE UNIQUE NOT NULL,
            year            INTEGER,
            quarter         INTEGER,
            month           INTEGER,
            month_name      TEXT,
            week            INTEGER,
            day_of_week     INTEGER,
            day_name        TEXT,
            is_weekend      BOOLEAN,
            is_holiday      BOOLEAN DEFAULT FALSE,
            holiday_name    TEXT
        )
        """,
    ]
    with engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        conn.commit()


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(s))
        if unicodedata.category(c) != "Mn"
    )


def _norm_city(city: str) -> str:
    mapping = {
        "tunis": "Tunis", "sfax": "Sfax", "sousse": "Sousse",
        "monastir": "Monastir", "nabeul": "Nabeul", "bizerte": "Bizerte",
        "kairouan": "Kairouan", "gabes": "Gabès", "gabès": "Gabès",
        "gafsa": "Gafsa", "ariana": "Ariana", "ben arous": "Ben Arous",
        "benarous": "Ben Arous", "la marsa": "La Marsa", "lamarsa": "La Marsa",
        "hammamet": "Hammamet", "manouba": "Manouba",
    }
    key = _strip_accents(str(city)).strip().lower()
    return mapping.get(key, str(city).strip().title())


def _norm_country(country: str) -> str:
    s = str(country).strip().lower()
    if s in ("", "nan", "none", "null"):
        return "Tunisie"
    mapping = {
        "tunisie": "Tunisie", "tunisia": "Tunisie", "tn": "Tunisie",
        "france": "France", "fr": "France",
        "maroc": "Maroc", "morocco": "Maroc",
        "algerie": "Algérie", "algérie": "Algérie", "algeria": "Algérie",
    }
    return mapping.get(_strip_accents(s), str(country).strip().title())


def _norm_industry(ind: str) -> str:
    s = _strip_accents(str(ind)).strip().lower()
    mapping = {
        "it": "IT", "informatique": "IT", "tech": "IT", "technologie": "IT",
        "finance": "Finance", "banque": "Finance", "banking": "Finance",
        "sante": "Santé", "santé": "Santé", "health": "Santé",
        "education": "Éducation", "éducation": "Éducation",
        "industrie": "Industrie", "manufacturing": "Industrie",
        "commerce": "Commerce", "retail": "Commerce",
        "services": "Services", "conseil": "Conseil", "consulting": "Conseil",
        "energie": "Énergie", "énergie": "Énergie", "energy": "Énergie",
        "transport": "Transport", "logistique": "Logistique",
        "immobilier": "Immobilier", "real estate": "Immobilier",
        "tourisme": "Tourisme", "hotellerie": "Tourisme",
        "telecoms": "Télécom", "télécom": "Télécom", "telecom": "Télécom",
        "agriculture": "Agriculture", "agroalimentaire": "Agroalimentaire",
    }
    return mapping.get(s, str(ind).strip().title())


def _norm_status_client(s: str) -> str:
    v = _strip_accents(str(s)).strip().lower()
    mapping = {
        "actif": "active", "active": "active", "actieve": "active",
        "inactif": "inactive", "inactive": "inactive",
        "prospect": "prospect",
        "churned": "churned", "churn": "churned", "perdu": "churned",
    }
    return mapping.get(v, "active")


def _norm_phone(phone: str) -> str:
    """Standardise to +216XXXXXXXX (8-digit Tunisian numbers)."""
    digits = re.sub(r"\D", "", str(phone))
    if digits.startswith("216") and len(digits) == 11:
        return f"+{digits}"
    if len(digits) == 8:
        return f"+216{digits}"
    if digits.startswith("00216"):
        digits = digits[5:]
        if len(digits) == 8:
            return f"+216{digits}"
    return digits or None


# ── FIX 1: _norm_stage now maps to clean English values ──────────────────────
def _norm_stage(stage: str) -> str:
    s = _strip_accents(str(stage)).strip().lower()
    mapping = {
        # Prospecting variants
        "prospection": "Prospecting",
        "prospect": "Prospecting",
        "prospecting": "Prospecting",
        # Qualification variants
        "qualification": "Qualification",
        "qualify": "Qualification",
        "qualif": "Qualification",
        # Proposal variants
        "proposition": "Proposal",
        "proposal": "Proposal",
        "propsal": "Proposal",
        "offre": "Proposal",
        "devis": "Proposal",
        # Negotiation variants
        "negociation": "Negotiation",
        "negociation": "Negotiation",
        "negotiation": "Negotiation",
        # Closed variants (won)
        "gagne": "Closed",
        "gagne": "Closed",
        "won": "Closed",
        "win": "Closed",
        "closed_won": "Closed",
        "closed won": "Closed",
        "closed-won": "Closed",
        # Closed variants (lost)
        "perdu": "Closed",
        "lost": "Closed",
        "lose": "Closed",
        "closed_lost": "Closed",
        "closed lost": "Closed",
        "closed-lost": "Closed",
        # Other closed
        "annule": "Closed",
        "annule": "Closed",
        "cancelled": "Closed",
        "closed": "Closed",
    }
    return mapping.get(s, str(stage).strip().title())


def _norm_deal_status(status: str) -> str:
    s = _strip_accents(str(status)).strip().lower()
    mapping = {
        "ouvert": "open", "open": "open", "en cours": "open",
        "in progress": "open", "en attente": "open",
        "gagne": "won", "gagné": "won", "won": "won", "win": "won",
        "closed won": "won", "closed-won": "won", "closed_won": "won",
        "perdu": "lost", "lost": "lost",
        "closed lost": "lost", "closed-lost": "lost", "closed_lost": "lost",
        "annule": "cancelled", "annulé": "cancelled", "cancelled": "cancelled",
    }
    return mapping.get(s, "open")


def _norm_outcome(outcome: str) -> str:
    s = _strip_accents(str(outcome)).strip().lower()
    mapping = {
        "positif": "positive", "positive": "positive", "reussi": "positive",
        "negatif": "negative", "negative": "negative", "echec": "negative",
        "neutre": "neutral", "neutral": "neutral", "en attente": "neutral",
        "na": "neutral", "n/a": "neutral",
    }
    return mapping.get(s, "neutral")


def _parse_value(raw) -> float | None:
    """Parse deal value strings like '50k', '1.2M', '50 000', '50,000.00'."""
    if raw is None or str(raw).strip().lower() in ("", "nan", "none"):
        return None
    s = str(raw).strip().replace("\u202f", "").replace("\xa0", "")
    m = re.match(r"([\d.,]+)\s*([kKmM])?", s)
    if not m:
        return None
    num_str = m.group(1).replace(",", ".")
    if num_str.count(".") > 1:
        num_str = num_str.replace(".", "").replace(",", ".")
    try:
        val = float(num_str)
    except ValueError:
        return None
    mult = m.group(2) or ""
    if mult.lower() == "k":
        val *= 1_000
    elif mult.lower() == "m":
        val *= 1_000_000
    return val


def _parse_duration(raw) -> int | None:
    """Parse duration strings: '1h30', '90 min', '1.5h', '45', etc. → minutes."""
    if raw is None or str(raw).strip().lower() in ("", "nan", "none"):
        return None
    s = str(raw).strip()
    m = re.match(r"(\d+)\s*[hH]\s*(\d*)", s)
    if m:
        hours = int(m.group(1))
        mins = int(m.group(2)) if m.group(2) else 0
        return hours * 60 + mins
    m = re.match(r"(\d+(?:\.\d+)?)\s*(?:min|m|minutes?)?$", s, re.IGNORECASE)
    if m:
        return int(float(m.group(1)))
    return None


def _parse_date(raw) -> date | None:
    if raw is None or str(raw).strip().lower() in ("", "nan", "none", "nat"):
        return None
    if isinstance(raw, (datetime, date, pd.Timestamp)):
        try:
            return pd.Timestamp(raw).date()
        except Exception:
            return None
    try:
        return dtparser.parse(str(raw), dayfirst=True).date()
    except Exception:
        return None


def _deal_size_category(value: float | None) -> str:
    if value is None:
        return "Unknown"
    if value < 5_000:
        return "Small"
    if value < 20_000:
        return "Medium"
    if value < 100_000:
        return "Large"
    return "Enterprise"


def _quarter(d: date | None) -> str | None:
    if d is None:
        return None
    return f"Q{(d.month - 1) // 3 + 1} {d.year}"


CHURN_KEYWORDS = [
    "insatisfait", "déçu", "concurrent", "résilié", "annulé", "perdu",
    "problème", "plainte", "retard", "délai", "qualité", "tarif trop",
    "pas satisfait", "impossible", "bloqué", "erreur", "bug critique",
    "aucune réponse", "pas de retour", "pas professionnel", "pas content",
]
POSITIVE_KEYWORDS = [
    "satisfait", "excellent", "renouvellement", "recommande", "confiant",
    "très content", "signé", "validé", "accord", "opportunité", "croissance",
    "partenariat", "upsell", "expansion", "fidèle", "ravi",
]


def _has_churn_signal(text: str) -> bool:
    t = _strip_accents(str(text)).lower()
    return any(kw in t for kw in CHURN_KEYWORDS)


def _has_positive_signal(text: str) -> bool:
    t = _strip_accents(str(text)).lower()
    return any(kw in t for kw in POSITIVE_KEYWORDS)


# ── EXTRACT tasks ─────────────────────────────────────────────────────────────

def extract_clients(**ctx):
    src = DATA_DIR / "raw_clients.xlsx"
    log.info("Reading %s …", src)
    df = pd.read_excel(src, dtype=str)
    out = STAGING_DIR / "raw_clients.csv"
    df.to_csv(out, index=False)
    log.info("Extracted %d rows → %s", len(df), out)


def extract_deals(**ctx):
    src = DATA_DIR / "raw_deals.xlsx"
    log.info("Reading %s …", src)
    df = pd.read_excel(src, dtype=str)
    out = STAGING_DIR / "raw_deals.csv"
    df.to_csv(out, index=False)
    log.info("Extracted %d rows → %s", len(df), out)


def extract_activities(**ctx):
    src = DATA_DIR / "raw_activities.xlsx"
    log.info("Reading %s …", src)
    df = pd.read_excel(src, dtype=str)
    out = STAGING_DIR / "raw_activities.csv"
    df.to_csv(out, index=False)
    log.info("Extracted %d rows → %s", len(df), out)


def extract_invoices(**ctx):
    src = DATA_DIR / "raw_invoices.xlsx"
    log.info("Reading %s …", src)
    df = pd.read_excel(src, dtype=str)
    out = STAGING_DIR / "raw_invoices.csv"
    df.to_csv(out, index=False)
    log.info("Extracted %d rows → %s", len(df), out)


# ── TRANSFORM tasks ───────────────────────────────────────────────────────────

def transform_clients(**ctx):
    df = pd.read_csv(STAGING_DIR / "raw_clients.csv", dtype=str)
    log.info("Transforming %d client rows …", len(df))

    print(df.columns.tolist())
    df["_nulls"] = df.isnull().sum(axis=1)
    dedup_cols = [c for c in ["company_name", "contact_email", "email", "phone"]
                  if c in df.columns]
    df = df.sort_values("_nulls").drop_duplicates(
        subset=dedup_cols if dedup_cols else None, keep="first"
    ).drop(columns=["_nulls"])

    companies = df["company_name"].dropna().unique().tolist()
    canonical: dict[str, str] = {}
    seen: list[str] = []
    for name in companies:
        if not seen:
            seen.append(name)
            canonical[name] = name
            continue
        match, score, _ = process.extractOne(name, seen, scorer=fuzz.token_sort_ratio)
        if score >= 85:
            canonical[name] = match
        else:
            seen.append(name)
            canonical[name] = name
    df["company_name"] = df["company_name"].map(canonical).fillna(df["company_name"])

    if "phone" in df.columns:
        df["phone"] = df["phone"].apply(_norm_phone)

    if "email" in df.columns:
        email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        df["email"] = df["email"].apply(
            lambda e: str(e).strip().lower() if pd.notna(e) and email_re.match(str(e)) else None
        )

    if "city" in df.columns:
        df["city"] = df["city"].apply(_norm_city)
    if "country" in df.columns:
        df["country"] = df["country"].apply(_norm_country)
    else:
        df["country"] = "Tunisie"
    if "industry" in df.columns:
        df["industry"] = df["industry"].apply(_norm_industry)
    if "status" in df.columns:
        df["status"] = df["status"].apply(_norm_status_client)

    for col in ("created_at", "created_date", "date_creation"):
        if col in df.columns:
            df["created_date"] = df[col].apply(_parse_date)
            break

    df["source_file"] = "raw_clients.xlsx"

    out = STAGING_DIR / "clean_clients.csv"
    df.to_csv(out, index=False)
    log.info("Transformed clients → %d rows saved to %s", len(df), out)


def transform_deals(**ctx):
    df = pd.read_csv(STAGING_DIR / "raw_deals.csv", dtype=str)
    log.info("Transforming %d deal rows …", len(df))

    # ── Keep only latest event per deal_id ────────────────────────────────
    if "deal_id" in df.columns and "event_type" in df.columns:
        order = {"create": 0, "update": 1, "stage_change": 2, "close": 3}
        df["_order"] = df["event_type"].map(order).fillna(1)
        dedup_cols = [c for c in ["deal_id"] if c in df.columns]
        df = df.sort_values(["deal_id", "_order"]).drop_duplicates(
            subset=dedup_cols if dedup_cols else None, keep="last"
        ).drop(columns=["_order", "event_type"], errors="ignore")

    # ── Value parsing + currency conversion ───────────────────────────────
    currency_col = next((c for c in df.columns if "currency" in c.lower()), None)
    value_col = next(
        (c for c in df.columns if "value" in c.lower() or "montant" in c.lower()), None
    )
    if value_col:
        df["value_raw"] = df[value_col].apply(_parse_value)
        if currency_col:
            df["value_tnd"] = df.apply(
                lambda r: (
                    r["value_raw"] * 3.35 if str(r.get(currency_col, "")).upper() == "EUR"
                    else r["value_raw"] * 3.10 if str(r.get(currency_col, "")).upper() == "USD"
                    else r["value_raw"]
                ),
                axis=1,
            )
        else:
            df["value_tnd"] = df["value_raw"]
        df.drop(columns=["value_raw"], inplace=True)

    # ── FIX 2: Stage normalization AFTER dedup so snapshots don't override ─
    if "stage" in df.columns:
        df["stage"] = df["stage"].apply(_norm_stage)

    # ── Status normalization ───────────────────────────────────────────────
    if "status" in df.columns:
        df["status"] = df["status"].apply(_norm_deal_status)

    # ── Sync status from stage ────────────────────────────────────────────
    if "stage" in df.columns and "status" in df.columns:
        stage_lc = df["stage"].str.strip().str.lower()
        df.loc[stage_lc == "closed", "status"] = df.loc[stage_lc == "closed", "status"].apply(
            lambda s: s if s in ("won", "lost") else "won"
        )
        _open_stages = {"prospecting", "qualification", "proposal", "negotiation"}
        df.loc[stage_lc.isin(_open_stages), "status"] = "open"

    # ── Probability ───────────────────────────────────────────────────────
    if "probability" in df.columns:
        def _clean_prob(p):
            try:
                v = float(str(p).replace("%", "").strip())
                return min(max(v, 0), 100)
            except Exception:
                return None
        df["probability"] = df["probability"].apply(_clean_prob)

    # ── FIX 2 (cont): Add "close_date" as first lookup for closed_date ───
    for col in ("close_date", "closed_at", "closed_date", "date_cloture", "end_date"):
        if col in df.columns:
            df["closed_date"] = df[col].apply(_parse_date)
            break

    for col in ("created_at", "created_date", "date_creation", "start_date"):
        if col in df.columns:
            df["created_date"] = df[col].apply(_parse_date)
            break

    # ── Derived fields ────────────────────────────────────────────────────
    def _days_to_close(row):
        c = row.get("created_date")
        cl = row.get("closed_date")
        if c and cl:
            try:
                return (pd.Timestamp(cl) - pd.Timestamp(c)).days
            except Exception:
                return None
        return None

    df["days_to_close"] = df.apply(_days_to_close, axis=1)
    df["deal_size_category"] = df["value_tnd"].apply(
        lambda v: _deal_size_category(None if pd.isna(v) else float(v))
    )
    df["quarter"] = df["created_date"].apply(
        lambda d: _quarter(_parse_date(d)) if d else None
    )

    # ── Fill null value_tnd with median for that deal_size_category ───────
    if "value_tnd" in df.columns and "deal_size_category" in df.columns:
        df["value_tnd"] = pd.to_numeric(df["value_tnd"], errors="coerce")
        df["value_tnd"] = df.groupby("deal_size_category")["value_tnd"].transform(
            lambda x: x.fillna(x.median())
        )

    # ── Integer casting ───────────────────────────────────────────────────
    if "probability" in df.columns:
        df["probability"] = pd.to_numeric(df["probability"], errors="coerce")
        df["probability"] = df["probability"].round(0).astype("Int64")
    if "days_to_close" in df.columns:
        df["days_to_close"] = pd.to_numeric(df["days_to_close"], errors="coerce")
        df["days_to_close"] = df["days_to_close"].round(0).astype("Int64")

    out = STAGING_DIR / "clean_deals.csv"
    df.to_csv(out, index=False)
    log.info("Transformed deals → %d rows saved to %s", len(df), out)


def transform_activities(**ctx):
    """Process activities in 50k-row chunks to manage memory."""
    src = STAGING_DIR / "raw_activities.csv"
    out = STAGING_DIR / "clean_activities.csv"
    chunk_size = 50_000
    first = True
    total = 0

    for chunk in pd.read_csv(src, dtype=str, chunksize=chunk_size):
        log.info("Processing activities chunk of %d rows …", len(chunk))

        chunk.drop_duplicates(inplace=True)

        type_map = {
            "appel": "Appel", "call": "Appel", "phone": "Appel",
            "email": "Email", "courriel": "Email", "mail": "Email",
            "réunion": "Réunion", "reunion": "Réunion", "meeting": "Réunion",
            "visite": "Visite", "visit": "Visite",
            "demo": "Démo", "démo": "Démo", "demonstration": "Démo",
            "relance": "Relance", "follow-up": "Relance", "followup": "Relance",
            "proposition": "Proposition", "proposal": "Proposition",
            "formation": "Formation", "training": "Formation",
            "support": "Support",
        }
        if "activity_type" in chunk.columns:
            chunk["activity_type"] = chunk["activity_type"].apply(
                lambda t: type_map.get(_strip_accents(str(t)).strip().lower(), str(t).strip().title())
            )

        dur_col = next(
            (c for c in chunk.columns if "duration" in c.lower() or "duree" in c.lower()), None
        )
        if dur_col:
            chunk["duration_min"] = chunk[dur_col].apply(_parse_duration)

        for col in ("activity_date", "date", "event_date"):
            if col in chunk.columns:
                chunk["activity_date"] = chunk[col].apply(_parse_date)
                break

        if "outcome" in chunk.columns:
            chunk["outcome"] = chunk["outcome"].apply(_norm_outcome)

        desc_col = next(
            (c for c in chunk.columns if "desc" in c.lower() or "note" in c.lower()), None
        )
        if desc_col:
            chunk["churn_signal"] = chunk[desc_col].apply(_has_churn_signal)
            chunk["positive_signal"] = chunk[desc_col].apply(_has_positive_signal)
            chunk.rename(columns={desc_col: "description"}, inplace=True)
        else:
            chunk["churn_signal"] = False
            chunk["positive_signal"] = False

        if "duration_min" in chunk.columns:
            chunk["duration_min"] = pd.to_numeric(chunk["duration_min"], errors="coerce")
            chunk["duration_min"] = chunk["duration_min"].round(0).astype("Int64")

        chunk.to_csv(out, index=False, mode="w" if first else "a", header=first)
        first = False
        total += len(chunk)

    log.info("Transformed activities → %d rows saved to %s", total, out)


def transform_invoices(**ctx):
    df = pd.read_csv(STAGING_DIR / "raw_invoices.csv", dtype=str)
    log.info("Transforming %d invoice rows …", len(df))

    # ── Keep latest event per invoice ─────────────────────────────────────
    inv_id_col = next(
        (c for c in df.columns if "invoice_id" in c.lower() or "facture_id" in c.lower()), None
    )
    if inv_id_col and "event_type" in df.columns:
        order = {"create": 0, "update": 1, "payment": 2, "close": 3}
        df["_order"] = df["event_type"].map(order).fillna(1)
        dedup_cols = [c for c in [inv_id_col] if c in df.columns]
        df = df.sort_values([inv_id_col, "_order"]).drop_duplicates(
            subset=dedup_cols if dedup_cols else None, keep="last"
        ).drop(columns=["_order", "event_type"], errors="ignore")

    # ── Invoice number standardisation → JBM-YYYY-NNNN ────────────────────
    inv_num_col = next(
        (c for c in df.columns if "number" in c.lower() or "numero" in c.lower()), None
    )
    if inv_num_col:
        def _std_inv_num(raw):
            s = str(raw).strip()
            m = re.search(r"(\d{4})[^\d]*(\d+)", s)
            if m:
                year, seq = m.group(1), m.group(2)
                return f"JBM-{year}-{int(seq):04d}"
            return s
        df["invoice_number"] = df[inv_num_col].apply(_std_inv_num)

    # ── Deduplicate on invoice_number ─────────────────────────────────────
    if "invoice_number" in df.columns:
        before = len(df)
        _bad = {"nan", "none", "null", "nat", ""}
        df = df[
            df["invoice_number"].notna() &
            ~df["invoice_number"].astype(str).str.strip().str.lower().isin(_bad)
        ]
        df = df.sort_values("invoice_number").drop_duplicates(
            subset=["invoice_number"], keep="last"
        )
        dropped = before - len(df)
        if dropped:
            log.warning("Dropped %d invoice rows with null/unparseable invoice_number", dropped)

    # ── Financial columns ─────────────────────────────────────────────────
    subtotal_col = next((c for c in df.columns if "subtotal" in c.lower() or "ht" in c.lower()), None)
    tax_col = next((c for c in df.columns if "tax" in c.lower() or "tva" in c.lower()), None)
    total_col = next((c for c in df.columns if "total" in c.lower() and "sub" not in c.lower()), None)
    paid_col = next((c for c in df.columns if "paid" in c.lower() or "paye" in c.lower()), None)

    if subtotal_col:
        df["subtotal"] = df[subtotal_col].apply(_parse_value)
    if tax_col:
        df["tax_amount_raw"] = df[tax_col].apply(_parse_value)

    if "subtotal" in df.columns:
        df["tax_amount"] = df["subtotal"].apply(
            lambda v: round(float(v) * 0.19, 2) if pd.notna(v) else None
        )
        df["total_amount"] = df.apply(
            lambda r: round(float(r["subtotal"]) + float(r["tax_amount"]), 2)
            if pd.notna(r.get("subtotal")) and pd.notna(r.get("tax_amount"))
            else None,
            axis=1,
        )
        if total_col:
            df["total_raw"] = df[total_col].apply(_parse_value)
            mask = df["total_raw"].notna() & df["subtotal"].notna() & (df["total_raw"] < df["subtotal"])
            df.loc[mask, ["subtotal", "total_raw"]] = df.loc[mask, ["total_raw", "subtotal"]].values
            df.drop(columns=["total_raw"], inplace=True)

    if paid_col:
        df["amount_paid"] = df[paid_col].apply(_parse_value).fillna(0)
    else:
        df["amount_paid"] = 0.0

    # ── FIX 4: Status normalization with all dirty variants ───────────────
    status_col = next((c for c in df.columns if "status" in c.lower() or "statut" in c.lower()), None)
    if status_col:
        smap = {
            "payée": "paid", "payee": "paid", "paid": "paid",
            "paye": "paid", "paye": "paid",
            "unpaid": "pending", "pending": "pending",
            "en attente": "pending", "in progress": "pending",
            "en retard": "overdue", "overdue": "overdue",
            "retard": "overdue", "late": "overdue",
            "annulée": "cancelled", "annulee": "cancelled",
            "cancelled": "cancelled", "annule": "cancelled",
            "nan": "cancelled",
            "partielle": "partial", "partial": "partial",
        }
        df["status"] = df[status_col].apply(
            lambda s: smap.get(_strip_accents(str(s)).strip().lower(), str(s).strip().lower())
        )

    # ── Dates ─────────────────────────────────────────────────────────────
    for col in ("invoice_date", "date_facture", "created_at"):
        if col in df.columns:
            df["invoice_date"] = df[col].apply(_parse_date)
            break
    for col in ("due_date", "date_echeance", "echeance"):
        if col in df.columns:
            df["due_date"] = df[col].apply(_parse_date)
            break

    # ── FIX 3: Parse payment_date from source data ────────────────────────
    for col in ("payment_date", "paid_date", "date_paiement"):
        if col in df.columns:
            df["payment_date"] = df[col].apply(_parse_date)
            break

    # ── invoice_date fallback ─────────────────────────────────────────────
    df["invoice_date"] = pd.to_datetime(df.get("invoice_date"), errors="coerce")
    df["due_date"] = pd.to_datetime(df.get("due_date"), errors="coerce")
    if "due_date" in df.columns:
        df["invoice_date"] = df["invoice_date"].fillna(
            df["due_date"] - pd.Timedelta(days=30)
        )
    df = df[df["invoice_date"].notna()]
    df = df[df["invoice_date"] >= pd.Timestamp("2023-01-01")]
    df["invoice_date"] = df["invoice_date"].dt.date
    df["due_date"] = df["due_date"].dt.date

    # ── Derived fields ────────────────────────────────────────────────────
    today = date.today()

    # ── FIX 3: payment_delay_days = payment_date - invoice_date for paid ──
    def _payment_delay(row):
        inv_d = _parse_date(row.get("invoice_date"))
        pay_d = _parse_date(row.get("payment_date"))
        status = str(row.get("status", "")).lower()
        if status == "paid" and inv_d and pay_d:
            return (pay_d - inv_d).days
        return None

    def _is_overdue(row):
        due_d = _parse_date(row.get("due_date"))
        status = str(row.get("status", "")).lower()
        if due_d and status not in ("paid", "cancelled"):
            return due_d < today
        return False

    def _days_outstanding(row):
        inv_d = _parse_date(row.get("invoice_date"))
        status = str(row.get("status", "")).lower()
        if inv_d and status not in ("paid", "cancelled"):
            return (today - inv_d).days
        return None

    df["payment_delay_days"] = df.apply(_payment_delay, axis=1)
    df["is_overdue"] = df.apply(_is_overdue, axis=1)
    df["days_outstanding"] = df.apply(_days_outstanding, axis=1)

    # ── Integer casting ───────────────────────────────────────────────────
    if "payment_delay_days" in df.columns:
        df["payment_delay_days"] = pd.to_numeric(df["payment_delay_days"], errors="coerce")
        df["payment_delay_days"] = df["payment_delay_days"].round(0).astype("Int64")
    if "days_outstanding" in df.columns:
        df["days_outstanding"] = pd.to_numeric(df["days_outstanding"], errors="coerce")
        df["days_outstanding"] = df["days_outstanding"].round(0).astype("Int64")

    out = STAGING_DIR / "clean_invoices.csv"
    df.to_csv(out, index=False)
    log.info("Transformed invoices → %d rows saved to %s", len(df), out)


# ── LOAD tasks ────────────────────────────────────────────────────────────────

def _load_csv_to_table(csv_path, table, col_map, engine):
    df = pd.read_csv(csv_path, keep_default_na=False, na_values=[""])
    if col_map:
        df = df.rename(columns=col_map)
        keep = [c for c in col_map.values() if c in df.columns]
        df = df[keep]

    for col in df.select_dtypes(include="float64").columns:
        non_null = df[col].dropna()
        if len(non_null) > 0 and (non_null % 1 == 0).all():
            df[col] = df[col].astype("Int64")

    schema = table.split(".")[0]
    table_name = table.split(".")[-1]

    raw_conn = engine.raw_connection()
    try:
        import io
        buffer = io.StringIO()
        df.to_csv(buffer, index=False, header=True)
        buffer.seek(0)

        cur = raw_conn.cursor()
        cur.execute(f'TRUNCATE TABLE {schema}."{table_name}" CASCADE')
        cur.copy_expert(
            f'COPY {schema}."{table_name}" ({",".join(df.columns)}) FROM STDIN WITH CSV HEADER',
            buffer
        )
        raw_conn.commit()
        cur.close()
        print(f"Loaded {len(df)} rows into {table}")
    except Exception as e:
        raw_conn.rollback()
        raise e
    finally:
        raw_conn.close()


def load_clients(**ctx):
    engine = _engine()
    _ensure_warehouse(engine)
    col_map = {
        "company_name": "company_name",
        "phone": "phone",
        "email": "email",
        "city": "city",
        "country": "country",
        "industry": "industry",
        "status": "status",
        "created_date": "created_date",
        "source_file": "source_file",
    }
    _load_csv_to_table(STAGING_DIR / "clean_clients.csv", "warehouse.dim_client", col_map, engine)


def load_deals(**ctx):
    engine = _engine()
    _ensure_warehouse(engine)
    col_map = {
        "deal_id": "deal_ref",
        "company_name": "company_name",
        "title": "title",
        "stage": "stage",
        "status": "status",
        "value_tnd": "value_tnd",
        "probability": "probability",
        "deal_size_category": "deal_size_category",
        "quarter": "quarter",
        "days_to_close": "days_to_close",
        "created_date": "created_date",
        "closed_date": "closed_date",
        "assigned_to": "assigned_to",
    }
    _load_csv_to_table(STAGING_DIR / "clean_deals.csv", "warehouse.fact_deals", col_map, engine)


def load_activities(**ctx):
    import io
    engine = _engine()
    _ensure_warehouse(engine)
    col_map = {
        "activity_id": "source_id",
        "company_name": "company_name",
        "contact_name": "contact_name",
        "activity_type": "activity_type",
        "activity_date": "activity_date",
        "duration_min": "duration_min",
        "outcome": "outcome",
        "churn_signal": "churn_signal",
        "positive_signal": "positive_signal",
        "description": "description",
        "assigned_to": "assigned_to",
        "deal_reference": "deal_reference",
    }
    csv_path = STAGING_DIR / "clean_activities.csv"
    schema = "warehouse"
    table_name = "fact_activities"

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        cur.execute(f'TRUNCATE TABLE {schema}."{table_name}" CASCADE')
        raw_conn.commit()

        total = 0
        for chunk in pd.read_csv(csv_path, chunksize=10_000):
            available = {k: v for k, v in col_map.items() if k in chunk.columns}
            chunk = chunk[list(available.keys())].rename(columns=available)

            if "duration_min" in chunk.columns:
                chunk["duration_min"] = (
                    pd.to_numeric(chunk["duration_min"], errors="coerce")
                    .round(0)
                    .astype("Int64")
                )

            buffer = io.StringIO()
            chunk.to_csv(buffer, index=False, header=(total == 0))
            buffer.seek(0)

            if total == 0:
                cur.copy_expert(
                    f'COPY {schema}."{table_name}" ({",".join(chunk.columns)}) FROM STDIN WITH CSV HEADER',
                    buffer
                )
            else:
                cur.copy_expert(
                    f'COPY {schema}."{table_name}" ({",".join(chunk.columns)}) FROM STDIN WITH CSV',
                    buffer
                )
            total += len(chunk)
            print(f"Loaded {total} rows so far...")

        raw_conn.commit()
        cur.close()
        print(f"Total loaded: {total} rows into {schema}.{table_name}")
    except Exception as e:
        raw_conn.rollback()
        raise e
    finally:
        raw_conn.close()


def load_invoices(**ctx):
    engine = _engine()
    _ensure_warehouse(engine)
    col_map = {
        "invoice_number": "invoice_number",
        "company_name": "company_name",
        "invoice_date": "invoice_date",
        "due_date": "due_date",
        "subtotal": "subtotal",
        "tax_amount": "tax_amount",
        "total_amount": "total_amount",
        "amount_paid": "amount_paid",
        "status": "status",
        "payment_delay_days": "payment_delay_days",
        "is_overdue": "is_overdue",
        "days_outstanding": "days_outstanding",
    }
    _load_csv_to_table(STAGING_DIR / "clean_invoices.csv", "warehouse.fact_revenue", col_map, engine)


# ── DIM DATE ──────────────────────────────────────────────────────────────────

TN_HOLIDAYS = {
    (1, 1): "Jour de l'An",
    (3, 20): "Fête de l'Indépendance",
    (4, 9): "Journée des Martyrs",
    (5, 1): "Fête du Travail",
    (7, 25): "Fête de la République",
    (8, 13): "Journée de la Femme",
    (10, 15): "Fête de l'Evacuation",
    (11, 7): "Fête Nationale",
}


def populate_dim_date(**ctx):
    engine = _engine()
    _ensure_warehouse(engine)

    start = date(2023, 1, 1)
    end = date(2026, 12, 31)

    rows = []
    current = start
    month_names = [
        "", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
        "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
    ]
    day_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

    while current <= end:
        holiday_name = TN_HOLIDAYS.get((current.month, current.day))
        rows.append({
            "date_id": int(current.strftime("%Y%m%d")),
            "full_date": current,
            "year": current.year,
            "quarter": (current.month - 1) // 3 + 1,
            "month": current.month,
            "month_name": month_names[current.month],
            "week": current.isocalendar()[1],
            "day_of_week": current.weekday(),
            "day_name": day_names[current.weekday()],
            "is_weekend": current.weekday() >= 5,
            "is_holiday": holiday_name is not None,
            "holiday_name": holiday_name,
        })
        current += timedelta(days=1)

    import io
    df = pd.DataFrame(rows)
    schema = "warehouse"
    table_name = "dim_date"

    raw_conn = engine.raw_connection()
    try:
        buffer = io.StringIO()
        df.to_csv(buffer, index=False, header=True)
        buffer.seek(0)

        cur = raw_conn.cursor()
        cur.execute(f'TRUNCATE TABLE {schema}."{table_name}" CASCADE')
        cur.copy_expert(
            f'COPY {schema}."{table_name}" ({",".join(df.columns)}) FROM STDIN WITH CSV HEADER',
            buffer
        )
        raw_conn.commit()
        cur.close()
        print(f"Populated {schema}.{table_name} with {len(df)} rows ({start} → {end})")
    except Exception as e:
        raw_conn.rollback()
        raise e
    finally:
        raw_conn.close()


# ── VALIDATE ──────────────────────────────────────────────────────────────────

def validate_warehouse(**ctx):
    engine = _engine()

    checks = {
        "warehouse.dim_client": (500, "company_name"),
        "warehouse.fact_deals": (3_000, "deal_ref"),
        "warehouse.fact_activities": (50_000, "source_id"),
        "warehouse.fact_revenue": (500, "invoice_number"),
        "warehouse.dim_date": (1_000, "full_date"),
    }

    print("\n" + "=" * 60)
    print("  WAREHOUSE VALIDATION REPORT")
    print("=" * 60)

    failures = []

    for table, (min_rows, pk_col) in checks.items():
        schema, tbl = table.split(".")
        with engine.connect() as conn:
            count_res = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            null_res = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {pk_col} IS NULL")
            ).scalar()

        ok_count = count_res >= min_rows
        ok_nulls = null_res == 0
        status = "OK" if (ok_count and ok_nulls) else "FAIL"
        if status == "FAIL":
            failures.append(f"{table}: rows={count_res} (min={min_rows}), nulls in {pk_col}={null_res}")

        print(f"  {status}  {table:<35} rows={count_res:>7,}  nulls_in_{pk_col}={null_res}")

    with engine.connect() as conn:
        trend = conn.execute(text("""
            SELECT EXTRACT(YEAR FROM invoice_date)::int AS yr, COALESCE(SUM(total_amount), 0) AS rev
            FROM warehouse.fact_revenue
            WHERE invoice_date IS NOT NULL
            GROUP BY yr ORDER BY yr
        """)).fetchall()

    print("\n  Revenue trend (TND):")
    yearly = {r[0]: float(r[1]) for r in trend}
    for yr in sorted(yearly):
        print(f"    {yr}: {yearly[yr]:>15,.2f} TND")

    if len(yearly) >= 2:
        years = sorted(yearly.keys())
        if yearly[years[-1]] < yearly[years[0]]:
            failures.append("Revenue trend assertion failed: last year < first year")
            print("  FAIL  Revenue should grow over time")

    with engine.connect() as conn:
        won = conn.execute(
            text("SELECT COUNT(*) FROM warehouse.fact_deals WHERE status = 'won'")
        ).scalar()
        total_deals = conn.execute(
            text("SELECT COUNT(*) FROM warehouse.fact_deals WHERE status IN ('won','lost')")
        ).scalar()

    if total_deals > 0:
        win_rate = won / total_deals * 100
        print(f"\n  Win rate: {win_rate:.1f}% ({won}/{total_deals} closed deals)")
        if not (10 <= win_rate <= 90):
            failures.append(f"Win rate {win_rate:.1f}% outside expected 10–90% range")

    print("\n" + "=" * 60)
    if failures:
        print("  FAILURES:")
        for f in failures:
            print(f"    - {f}")
        print("=" * 60)
        raise RuntimeError(f"Warehouse validation failed: {failures}")
    else:
        print("  All checks passed.")
        print("=" * 60)


# ── DAG definition ─────────────────────────────────────────────────────────────

default_args = {
    "owner": "jbm-etl",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}

with DAG(
    dag_id="jbm_etl_pipeline",
    description="JBM Consulting — Extract, Transform, Load from raw Excel to warehouse",
    schedule_interval="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["jbm", "etl", "warehouse"],
) as dag:

    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")

    t_extract_clients = PythonOperator(task_id="extract_clients", python_callable=extract_clients)
    t_transform_clients = PythonOperator(task_id="transform_clients", python_callable=transform_clients)
    t_load_clients = PythonOperator(task_id="load_clients", python_callable=load_clients)

    t_extract_deals = PythonOperator(task_id="extract_deals", python_callable=extract_deals)
    t_transform_deals = PythonOperator(task_id="transform_deals", python_callable=transform_deals)
    t_load_deals = PythonOperator(task_id="load_deals", python_callable=load_deals)

    t_extract_activities = PythonOperator(task_id="extract_activities", python_callable=extract_activities)
    t_transform_activities = PythonOperator(task_id="transform_activities", python_callable=transform_activities)
    t_load_activities = PythonOperator(task_id="load_activities", python_callable=load_activities)

    t_extract_invoices = PythonOperator(task_id="extract_invoices", python_callable=extract_invoices)
    t_transform_invoices = PythonOperator(task_id="transform_invoices", python_callable=transform_invoices)
    t_load_invoices = PythonOperator(task_id="load_invoices", python_callable=load_invoices)

    t_dim_date = PythonOperator(task_id="populate_dim_date", python_callable=populate_dim_date)
    t_validate = PythonOperator(task_id="validate_warehouse", python_callable=validate_warehouse)

    start >> [t_extract_clients, t_extract_deals, t_extract_activities, t_extract_invoices]

    t_extract_clients >> t_transform_clients >> t_load_clients
    t_extract_deals >> t_transform_deals >> t_load_deals
    t_extract_activities >> t_transform_activities >> t_load_activities
    t_extract_invoices >> t_transform_invoices >> t_load_invoices

    [t_load_clients, t_load_deals, t_load_activities, t_load_invoices] >> t_dim_date
    t_dim_date >> t_validate >> end