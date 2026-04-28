"""Batch ML prediction helpers for predictive chart tools."""
import logging
from typing import List, Dict
import os
import numpy as np
import pandas as pd
import joblib

from backend.models.database import get_session

logger = logging.getLogger(__name__)


def get_all_churn_predictions() -> List[Dict]:
    """
    Load churn model artifacts once, build feature matrix for ALL warehouse companies
    with >= 2 total interactions, run predict_proba in a single batch call.
    Returns [{company, churn_probability, risk_level}] sorted by probability desc.
    Skips companies that fail silently.
    """
    from backend.ml.churn_model import build_feature_matrix, _get_engine, ML_DIR

    try:
        model = joblib.load(os.path.join(ML_DIR, "churn_model.joblib"))
        scaler = joblib.load(os.path.join(ML_DIR, "scaler.joblib"))
        feature_names = joblib.load(os.path.join(ML_DIR, "feature_names.joblib"))
    except Exception:
        return []

    try:
        engine = _get_engine()
        df_raw = build_feature_matrix(engine)
    except Exception:
        return []

    if df_raw.empty:
        return []

    # Same interaction filter as training pipeline
    df_raw["_total_interactions"] = (
        df_raw["total_activities"].fillna(0)
        + df_raw["total_deals"].fillna(0)
        + df_raw["total_invoices"].fillna(0)
    )
    df = df_raw[df_raw["_total_interactions"] >= 2].copy().reset_index(drop=True)

    if df.empty:
        return []

    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].fillna(0)

    # Same one-hot encoding as training
    df_encoded = pd.get_dummies(
        df, columns=["industry", "status"],
        prefix=["industry", "status"], dummy_na=False,
    ).reset_index(drop=True)

    for col in feature_names:
        if col not in df_encoded.columns:
            df_encoded[col] = 0.0

    X = df_encoded[feature_names].astype(float).fillna(0.0)
    X_scaled = scaler.transform(X)
    probs_arr = model.predict_proba(X_scaled)[:, 1]
    probs_arr = 0.5 + (probs_arr - 0.5) * 0.75

    results = []
    for idx in range(len(df)):
        prob = round(float(probs_arr[idx]), 4)
        risk_level = "High" if prob > 0.7 else ("Medium" if prob >= 0.4 else "Low")
        results.append({
            "company": str(df.at[idx, "company_name"]),
            "churn_probability": prob,
            "risk_level": risk_level,
        })

    results.sort(key=lambda x: x["churn_probability"], reverse=True)
    return results


def get_all_deal_predictions() -> List[Dict]:
    """
    Load deal model artifacts once, fetch all open deals + company-level warehouse
    features in batch, run predict_proba in a single call.
    Returns [{deal_id, title, company, value, stage, win_probability, outcome_prediction}]
    sorted by win_probability desc. Skips failures silently.
    """
    from datetime import date as _date
    from sqlalchemy import text as sa_text
    from backend.ml.deal_model import (
        _get_engine as _deal_get_engine,
        _fetch_activities, _fetch_revenue, _fetch_clients,
        ML_DIR as DEAL_ML_DIR,
    )
    from backend.models.crm_models import Deal, Company

    try:
        model = joblib.load(os.path.join(DEAL_ML_DIR, "deal_model.joblib"))
        scaler = joblib.load(os.path.join(DEAL_ML_DIR, "deal_scaler.joblib"))
        feature_names = joblib.load(os.path.join(DEAL_ML_DIR, "deal_feature_names.joblib"))
    except Exception:
        return []

    db = get_session()
    try:
        rows = (
            db.query(Deal.id, Deal.title, Deal.value, Deal.stage,
                     Deal.probability, Deal.created_at, Company.name)
            .join(Company, Deal.company_id == Company.id)
            .filter(Deal.status == "open", Deal.is_deleted == False)
            .all()
        )
    finally:
        db.close()

    if not rows:
        return []

    today = _date.today()

    # Build deal-level base DataFrame — deal-specific features only
    deal_records = []
    for deal_id, title, value, stage, probability, created_at, company_name in rows:
        value_tnd = float(value or 0)
        stage_str = stage or "prospecting"
        if value_tnd < 10000:
            deal_size_category = "small"
        elif value_tnd < 50000:
            deal_size_category = "medium"
        else:
            deal_size_category = "large"
        created_dt = pd.Timestamp(created_at) if created_at else pd.Timestamp(today)
        quarter = f"Q{((created_dt.month - 1) // 3) + 1}"
        deal_records.append({
            "deal_id": deal_id,
            "title": title,
            "company_name": company_name,
            "value_tnd": value_tnd,
            "stage": stage_str,
            "deal_size_category": deal_size_category,
            "quarter": quarter,
        })

    df_deals = pd.DataFrame(deal_records).reset_index(drop=True)

    # Batch-fetch all company-level warehouse features in four queries
    try:
        wh_engine = _deal_get_engine()
        with wh_engine.connect() as conn:
            r = conn.execute(sa_text("""
                SELECT company_name,
                       COUNT(*)                                          AS company_total_deals,
                       SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END)  AS won_count,
                       AVG(value_tnd)                                    AS company_avg_deal_value,
                       AVG(days_to_close)                               AS avg_days_to_close
                FROM warehouse.fact_deals
                WHERE status IN ('won', 'lost') AND company_name IS NOT NULL
                GROUP BY company_name
            """))
            df_hist = pd.DataFrame(r.fetchall(), columns=list(r.keys()))
            df_hist["company_historical_win_rate"] = np.where(
                df_hist["company_total_deals"] > 0,
                df_hist["won_count"].astype(float) / df_hist["company_total_deals"].astype(float),
                np.nan,
            )
            df_hist.drop(columns=["won_count"], inplace=True)

            df_clients = _fetch_clients(conn)
            df_acts = _fetch_activities(conn)
            df_rev = _fetch_revenue(conn)
    except Exception:
        return []

    # Merge company features onto deals — left join so unmatched deals get NaN
    df = (
        df_deals
        .merge(df_hist[["company_name", "company_total_deals", "company_avg_deal_value",
                        "avg_days_to_close", "company_historical_win_rate"]],
               on="company_name", how="left")
        .merge(df_clients[["company_name", "industry", "status",
                            "client_age_days", "client_age_months"]],
               on="company_name", how="left")
        .merge(df_acts, on="company_name", how="left")
        .merge(df_rev[["company_name", "company_payment_rate",
                       "company_avg_payment_delay", "company_overdue_ratio"]],
               on="company_name", how="left")
        .reset_index(drop=True)
    )

    # "status" here is the client's CRM status (prospect/client/inactive);
    # rename to match the training feature name and avoid confusion with deal status.
    df.rename(columns={"status": "client_status"}, inplace=True)

    # days_to_close: use company average from warehouse as best estimate for open deals
    df["days_to_close"] = df["avg_days_to_close"].fillna(0)
    df["company_activity_frequency"] = (
        df["company_total_activities"].fillna(0)
        / df["client_age_months"].fillna(1).clip(lower=1)
    )

    # Same categorical encoding as training
    cat_cols = [c for c in ["stage", "deal_size_category", "quarter", "industry", "client_status"]
                if c in df.columns]
    df_encoded = pd.get_dummies(
        df, columns=cat_cols, prefix=cat_cols, dummy_na=False,
    ).reset_index(drop=True)

    for col in feature_names:
        if col not in df_encoded.columns:
            df_encoded[col] = 0.0

    numeric_enc = df_encoded.select_dtypes(include=[np.number]).columns
    df_encoded[numeric_enc] = df_encoded[numeric_enc].fillna(0)

    X = df_encoded[feature_names].astype(float)
    X_scaled = scaler.transform(X)
    probs_arr = model.predict_proba(X_scaled)[:, 1]
    probs_arr = 0.5 + (probs_arr - 0.5) * 0.55
    logger.debug(f"deal probs — min={probs_arr.min():.4f} max={probs_arr.max():.4f} unique={len(np.unique(probs_arr.round(4)))}")

    results = []
    for idx in range(len(df)):
        prob = round(float(probs_arr[idx]), 4)
        if prob > 0.65:
            outcome = "Likely Win"
        elif prob >= 0.35:
            outcome = "Uncertain"
        else:
            outcome = "Likely Loss"
        results.append({
            "deal_id": int(df.at[idx, "deal_id"]),
            "title": str(df.at[idx, "title"]),
            "company": str(df.at[idx, "company_name"]),
            "value": float(df.at[idx, "value_tnd"]),
            "stage": str(df.at[idx, "stage"]),
            "win_probability": prob,
            "outcome_prediction": outcome,
        })

    results.sort(key=lambda x: x["win_probability"], reverse=True)
    return results
