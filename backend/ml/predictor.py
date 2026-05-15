"""
Churn predictor — loads saved model artifacts and predicts for a single company.

Pipeline:
  1. Feature engineering  (churn_model.build_single_company_features)
  2. ML scoring           (calibrated model)
  3. Deterministic recs   (recommendation_engine.generate_recommendations)
  4. LLM summary          (churn_summarizer.summarize_churn)
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
    model         = joblib.load(os.path.join(ML_DIR, "churn_model.joblib"))
    scaler        = joblib.load(os.path.join(ML_DIR, "scaler.joblib"))
    feature_names = joblib.load(os.path.join(ML_DIR, "feature_names.joblib"))
    return model, scaler, feature_names


def predict_company_churn(company_name: str) -> dict:
    """
    Predict churn risk for a named company.

    Returns:
        {
            "company":            str,
            "churn_probability":  float,
            "risk_level":         "High" | "Medium" | "Low",
            "top_factors":        [{"feature", "value", "importance"}, ...],
            "recommendations":    [{"priority", "category", "action", "rationale"}, ...],
            "summary":            str,   # LLM-generated prose (fallback: template)
        }
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

    # ── Step 1: Align feature matrix to training columns ─────────────────────
    for col in feature_names:
        if col not in df_raw.columns:
            df_raw[col] = 0.0
    X = df_raw[feature_names].astype(float).fillna(0.0)

    # ── Step 2: Score ─────────────────────────────────────────────────────────
    X_scaled = scaler.transform(X)
    prob = float(model.predict_proba(X_scaled)[0, 1])
    prob = 0.5 + (prob - 0.5) * 0.75

    if prob > 0.7:
        risk_level = "High"
    elif prob >= 0.4:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    # ── Step 3: Feature importance → top factors ──────────────────────────────
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    elif hasattr(model, "coef_"):
        importances = np.abs(model.coef_[0])
    elif hasattr(model, "calibrated_classifiers_"):
        fold_imps = []
        for cc in model.calibrated_classifiers_:
            inner = cc.estimator
            if hasattr(inner, "feature_importances_"):
                fold_imps.append(inner.feature_importances_)
            elif hasattr(inner, "coef_"):
                fold_imps.append(np.abs(inner.coef_[0]))
        importances = np.mean(fold_imps, axis=0) if fold_imps else np.zeros(len(feature_names))
    else:
        importances = np.zeros(len(feature_names))

    feat_imp    = pd.Series(importances, index=feature_names)
    top5        = feat_imp.nlargest(5)
    feature_row = X.iloc[0]

    top_factors = [
        {
            "feature":    feat,
            "value":      float(feature_row.get(feat, 0.0)),
            "importance": float(imp),
        }
        for feat, imp in top5.items()
    ]

    # ── Step 4: Deterministic recommendations ─────────────────────────────────
    from backend.ml.recommendation_engine import generate_recommendations
    feature_dict = df_raw.iloc[0].to_dict()
    recs = generate_recommendations(feature_dict, risk_level)
    recommendations = [
        {
            "priority":  r.priority,
            "category":  r.category,
            "action":    r.action,
            "rationale": r.rationale,
        }
        for r in recs
    ]

    # ── Step 5: LLM summary (deterministic input, natural language output) ────
    from backend.ml.churn_summarizer import summarize_churn
    summary = summarize_churn(company_name, prob, risk_level, top_factors, recs)

    return {
        "company":           company_name,
        "churn_probability": round(prob, 4),
        "risk_level":        risk_level,
        "top_factors":       top_factors,
        "recommendations":   recommendations,
        "summary":           summary,
    }
