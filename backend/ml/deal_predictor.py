"""
Deal win probability predictor — loads saved artifacts and predicts for a single deal.
Imports feature engineering from deal_model to avoid duplication.
"""
import os
import numpy as np
import pandas as pd
import joblib
from dotenv import load_dotenv

from backend.ml.deal_model import build_single_deal_features, _get_engine

load_dotenv()

ML_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_artifacts():
    model = joblib.load(os.path.join(ML_DIR, "deal_model.joblib"))
    scaler = joblib.load(os.path.join(ML_DIR, "deal_scaler.joblib"))
    feature_names = joblib.load(os.path.join(ML_DIR, "deal_feature_names.joblib"))
    return model, scaler, feature_names


def predict_deal_outcome(deal_id: int) -> dict:
    """
    Predict win probability for a specific deal.

    Returns:
        {
            "deal_id": int,
            "deal_title": str,
            "company": str,
            "win_probability": float,
            "outcome_prediction": "Likely Win" | "Uncertain" | "Likely Loss",
            "top_factors": [{"feature": str, "value": float, "importance": float}, ...]
        }

    Raises:
        ValueError: if deal not found in operational DB.
    """
    from backend.models.database import get_session
    from backend.models.crm_models import Deal, Company

    # ── Look up the deal in the operational DB ────────────────────────────────
    db = get_session()
    try:
        deal = db.query(Deal).filter(Deal.id == deal_id, Deal.is_deleted == False).first()
        if not deal:
            raise ValueError(f"Deal ID {deal_id} not found.")
        company = db.query(Company).filter(Company.id == deal.company_id).first()
        company_name = company.name if company else None
        if not company_name:
            raise ValueError(f"Deal ID {deal_id} has no associated company.")
        deal_title = deal.title
        deal_status = deal.status
        value_tnd = float(deal.value or 0.0)
        stage = deal.stage or "prospecting"
        probability = float(deal.probability or 50)
        created_at = deal.created_at
    finally:
        db.close()

    if deal_status in ("won", "lost"):
        return {
            "deal_id": deal_id,
            "deal_title": deal_title,
            "company": company_name,
            "win_probability": 1.0 if deal_status == "won" else 0.0,
            "outcome_prediction": "Already Won" if deal_status == "won" else "Already Lost",
            "top_factors": [],
            "note": "This deal is already closed.",
        }

    model, scaler, feature_names = _load_artifacts()
    engine = _get_engine()

    df_raw = build_single_deal_features(
        deal_id=deal_id,
        value_tnd=value_tnd,
        stage=stage,
        probability=probability,
        company_name=company_name,
        created_at=created_at,
        engine=engine,
    )

    # ── Encode and align to training feature set ──────────────────────────────
    cat_cols = [c for c in ["stage", "deal_size_category", "quarter", "industry", "client_status"]
                if c in df_raw.columns]
    df_encoded = pd.get_dummies(df_raw, columns=cat_cols,
                                prefix=cat_cols, dummy_na=False)

    for col in feature_names:
        if col not in df_encoded.columns:
            df_encoded[col] = 0.0
    X = df_encoded[feature_names].astype(float).fillna(0.0)

    X_scaled = scaler.transform(X)
    prob = float(model.predict_proba(X_scaled)[0, 1])
    prob = 0.5 + (prob - 0.5) * 0.55

    if prob > 0.65:
        outcome = "Likely Win"
    elif prob >= 0.35:
        outcome = "Uncertain"
    else:
        outcome = "Likely Loss"

    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    elif hasattr(model, "coef_"):
        importances = np.abs(model.coef_[0])
    else:
        importances = np.zeros(len(feature_names))

    feat_imp = pd.Series(importances, index=feature_names)
    top5 = feat_imp.nlargest(5)
    feature_row = X.iloc[0]

    top_factors = [
        {
            "feature": feat,
            "value": float(feature_row.get(feat, 0.0)),
            "importance": float(imp),
        }
        for feat, imp in top5.items()
    ]

    return {
        "deal_id": deal_id,
        "deal_title": deal_title,
        "company": company_name,
        "win_probability": round(prob, 4),
        "outcome_prediction": outcome,
        "top_factors": top_factors,
    }
