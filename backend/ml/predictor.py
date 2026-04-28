"""
Churn predictor — loads saved model artifacts and predicts for a single company.
Imports feature engineering from churn_model to avoid duplication.
"""
import os
import numpy as np
import pandas as pd
import joblib
from dotenv import load_dotenv

from backend.ml.churn_model import build_single_company_features, _get_engine

load_dotenv()

ML_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_artifacts():
    model = joblib.load(os.path.join(ML_DIR, "churn_model.joblib"))
    scaler = joblib.load(os.path.join(ML_DIR, "scaler.joblib"))
    feature_names = joblib.load(os.path.join(ML_DIR, "feature_names.joblib"))
    return model, scaler, feature_names


def predict_company_churn(company_name: str) -> dict:
    """
    Predict churn risk for a named company.

    Returns:
        {
            "company": str,
            "churn_probability": float,
            "risk_level": "High" | "Medium" | "Low",
            "top_factors": [
                {"feature": str, "value": float, "importance": float},
                ...  (top 5)
            ],
        }

    Raises:
        ValueError: if company not found in warehouse.dim_client.
    """
    model, scaler, feature_names = _load_artifacts()
    engine = _get_engine()

    df_raw = build_single_company_features(company_name, engine)
    if df_raw.empty:
        with engine.connect() as conn:
            from sqlalchemy import text
            row = conn.execute(text(
                "SELECT company_name FROM warehouse.dim_client "
                "WHERE LOWER(company_name) LIKE LOWER(:pattern) LIMIT 1"
            ), {"pattern": f"%{company_name}%"}).fetchone()
        if row:
            company_name = row[0]
            df_raw = build_single_company_features(company_name, engine)
        if df_raw.empty:
            raise ValueError(
                f"Company '{company_name}' not found in warehouse.dim_client. "
                "Ensure ETL has been run and the name matches exactly."
            )

    # Same encoding as training
    df_encoded = pd.get_dummies(
        df_raw, columns=["industry", "status"],
        prefix=["industry", "status"], dummy_na=False,
    )

    # Align to the training feature set (add missing dummies as 0, drop extras)
    for col in feature_names:
        if col not in df_encoded.columns:
            df_encoded[col] = 0.0
    X = df_encoded[feature_names].astype(float).fillna(0.0)

    X_scaled = scaler.transform(X)
    prob = float(model.predict_proba(X_scaled)[0, 1])
    prob = 0.5 + (prob - 0.5) * 0.75

    if prob > 0.7:
        risk_level = "High"
    elif prob >= 0.4:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    # Feature importance from the best model
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
        "company": company_name,  # resolved name (may differ from input after fuzzy match)
        "churn_probability": round(prob, 4),
        "risk_level": risk_level,
        "top_factors": top_factors,
    }
