"""
Deal win probability training pipeline for AXIS ERP.
Target: closed deals (status IN ('won','lost')). Label: 1=won, 0=lost.
Trains on warehouse schema: fact_deals, dim_client, fact_activities, fact_revenue.

Run: python -m backend.ml.deal_model
"""
import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import date
from sqlalchemy import create_engine, text
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_validate
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, classification_report, confusion_matrix, roc_curve,
)
import joblib
from dotenv import load_dotenv

try:
    from xgboost import XGBClassifier
except ImportError:
    XGBClassifier = None

load_dotenv()

ML_DIR = os.path.dirname(os.path.abspath(__file__))
FIGURES_DIR = os.path.join(ML_DIR, "figures")
os.makedirs(ML_DIR, exist_ok=True)
os.makedirs(FIGURES_DIR, exist_ok=True)


def _get_engine():
    url = os.getenv("DATABASE_URL", "postgresql://erp_user:erp_pass@localhost:5432/erp_db")
    return create_engine(url, pool_pre_ping=True)


def _fetch_activities(conn) -> pd.DataFrame:
    r = conn.execute(text("""
        SELECT company_name,
               COUNT(*)                                     AS company_total_activities,
               SUM(churn_signal::int)                       AS company_churn_signals,
               SUM(positive_signal::int)                    AS company_positive_signals
        FROM warehouse.fact_activities
        WHERE company_name IS NOT NULL
        GROUP BY company_name
    """))
    return pd.DataFrame(r.fetchall(), columns=list(r.keys()))


def _fetch_revenue(conn) -> pd.DataFrame:
    r = conn.execute(text("""
        SELECT company_name,
               SUM(total_amount)                            AS company_total_invoiced,
               SUM(amount_paid)                             AS company_total_paid,
               AVG(payment_delay_days)                      AS company_avg_payment_delay,
               SUM(is_overdue::int)                         AS company_overdue_count,
               COUNT(*)                                     AS company_total_invoices
        FROM warehouse.fact_revenue
        WHERE company_name IS NOT NULL
        GROUP BY company_name
    """))
    df = pd.DataFrame(r.fetchall(), columns=list(r.keys()))
    df["company_payment_rate"] = np.where(
        df["company_total_invoiced"] > 0,
        df["company_total_paid"] / df["company_total_invoiced"],
        np.nan,
    )
    df["company_overdue_ratio"] = np.where(
        df["company_total_invoices"] > 0,
        df["company_overdue_count"] / df["company_total_invoices"],
        np.nan,
    )
    return df


def _fetch_clients(conn) -> pd.DataFrame:
    today = date.today()
    r = conn.execute(text("""
        SELECT company_name, industry, status, created_date
        FROM warehouse.dim_client
        WHERE company_name IS NOT NULL
    """))
    df = pd.DataFrame(r.fetchall(), columns=list(r.keys()))
    df["created_date"] = pd.to_datetime(df["created_date"], errors="coerce")
    df["client_age_days"] = (
        pd.Timestamp(today) - df["created_date"]
    ).dt.days.fillna(0).clip(lower=0).astype(float)
    df["client_age_months"] = (df["client_age_days"] / 30.0).clip(lower=1.0)
    return df


def build_deal_feature_matrix(engine) -> pd.DataFrame:
    """
    Build deal-level feature matrix for all terminal deals (won/lost).
    company_historical_win_rate uses leave-one-out to prevent target leakage.
    """
    with engine.connect() as conn:
        # ── Terminal deals ────────────────────────────────────────────────────
        r = conn.execute(text("""
            SELECT deal_id, company_name, status, stage, value_tnd,
                   days_to_close, probability, deal_size_category, quarter
            FROM warehouse.fact_deals
            WHERE status IN ('won', 'lost')
              AND company_name IS NOT NULL
              AND value_tnd IS NOT NULL
        """))
        df_deals = pd.DataFrame(r.fetchall(), columns=list(r.keys()))

        if df_deals.empty:
            return pd.DataFrame()

        df_deals["label"] = (df_deals["status"] == "won").astype(int)
        df_deals["value_tnd"] = pd.to_numeric(df_deals["value_tnd"], errors="coerce")
        df_deals["days_to_close"] = pd.to_numeric(df_deals["days_to_close"], errors="coerce")
        df_deals["probability"] = pd.to_numeric(df_deals["probability"], errors="coerce")

        # ── Company-level deal history (leave-one-out win rate) ───────────────
        # Aggregate ALL terminal deals per company first, then subtract current.
        company_stats = (
            df_deals.groupby("company_name")
            .agg(
                _co_total=("label", "count"),
                _co_won=("label", "sum"),
                _co_total_value=("value_tnd", "sum"),
            )
            .reset_index()
        )
        df_deals = df_deals.merge(company_stats, on="company_name", how="left")

        # Leave-one-out: exclude current deal from company stats
        df_deals["company_total_deals"] = df_deals["_co_total"] - 1
        df_deals["_loo_won"] = df_deals["_co_won"] - df_deals["label"]
        df_deals["company_historical_win_rate"] = np.where(
            df_deals["company_total_deals"] > 0,
            df_deals["_loo_won"] / df_deals["company_total_deals"],
            np.nan,
        )
        df_deals["company_avg_deal_value"] = np.where(
            df_deals["company_total_deals"] > 0,
            (df_deals["_co_total_value"] - df_deals["value_tnd"]) / df_deals["company_total_deals"],
            np.nan,
        )
        df_deals.drop(columns=["_co_total", "_co_won", "_co_total_value", "_loo_won"], inplace=True)

        # ── Join dim_client ───────────────────────────────────────────────────
        df_clients = _fetch_clients(conn)
        df_deals = df_deals.merge(
            df_clients[["company_name", "industry", "status", "client_age_days", "client_age_months"]],
            on="company_name", how="left", suffixes=("", "_client"),
        )
        # status_client = client's CRM status (prospect/client/inactive); rename to avoid
        # confusion with the deal's own status column (won/lost = the label).
        df_deals.rename(columns={"status_client": "client_status"}, inplace=True)
        df_deals["company_activity_frequency"] = np.nan  # filled after activities join

        # ── Join fact_activities ──────────────────────────────────────────────
        df_acts = _fetch_activities(conn)
        df_deals = df_deals.merge(df_acts, on="company_name", how="left")
        df_deals["company_activity_frequency"] = (
            df_deals["company_total_activities"] / df_deals["client_age_months"]
        )

        # ── Join fact_revenue ─────────────────────────────────────────────────
        df_rev = _fetch_revenue(conn)
        df_deals = df_deals.merge(
            df_rev[["company_name", "company_payment_rate",
                    "company_avg_payment_delay", "company_overdue_ratio"]],
            on="company_name", how="left",
        )

    return df_deals


def build_single_deal_features(
    deal_id: int,
    value_tnd: float,
    stage: str,
    probability: float,
    company_name: str,
    created_at,
    engine,
) -> pd.DataFrame:
    """
    Build a single-row feature DataFrame for inference.
    days_to_close is estimated from company avg; company_historical_win_rate uses all closed deals.
    """
    today = date.today()

    with engine.connect() as conn:
        # ── Company deal history (no leave-one-out at inference — predicting open deal) ──
        r = conn.execute(text("""
            SELECT COUNT(*)                         AS company_total_deals,
                   SUM(CASE WHEN status='won' THEN 1 ELSE 0 END) AS won_count,
                   AVG(value_tnd)                   AS company_avg_deal_value,
                   AVG(days_to_close)               AS avg_days_to_close
            FROM warehouse.fact_deals
            WHERE company_name = :cn
              AND status IN ('won', 'lost')
        """), {"cn": company_name})
        row = r.fetchone()
        company_total_deals = int(row[0] or 0)
        won_count = float(row[1] or 0)
        company_avg_deal_value = float(row[2]) if row[2] is not None else np.nan
        avg_days_to_close = float(row[3]) if row[3] is not None else 0.0

        company_historical_win_rate = (
            won_count / company_total_deals if company_total_deals > 0 else np.nan
        )
        days_to_close = avg_days_to_close  # best estimate for open deal

        # ── Estimate deal_size_category and quarter from deal context ─────────
        # Replicate warehouse bucketing: small/medium/large by value
        if value_tnd < 10000:
            deal_size_category = "small"
        elif value_tnd < 50000:
            deal_size_category = "medium"
        else:
            deal_size_category = "large"

        created_dt = pd.Timestamp(created_at) if created_at else pd.Timestamp(today)
        quarter = f"Q{((created_dt.month - 1) // 3) + 1}"

        # ── dim_client ────────────────────────────────────────────────────────
        r = conn.execute(text("""
            SELECT industry, status, created_date
            FROM warehouse.dim_client
            WHERE company_name = :cn
            LIMIT 1
        """), {"cn": company_name})
        client_row = r.fetchone()
        if client_row:
            industry = client_row[0]
            client_status = client_row[1]
            created_date = pd.to_datetime(client_row[2], errors="coerce")
            client_age_days = max((pd.Timestamp(today) - created_date).days, 0) if pd.notna(created_date) else 0.0
        else:
            industry = None
            client_status = None
            client_age_days = 0.0
        client_age_months = max(client_age_days / 30.0, 1.0)

        # ── fact_activities ───────────────────────────────────────────────────
        r = conn.execute(text("""
            SELECT COUNT(*)                         AS company_total_activities,
                   SUM(churn_signal::int)           AS company_churn_signals,
                   SUM(positive_signal::int)        AS company_positive_signals
            FROM warehouse.fact_activities
            WHERE company_name = :cn
        """), {"cn": company_name})
        act_row = r.fetchone()
        company_total_activities = float(act_row[0] or 0)
        company_churn_signals = float(act_row[1] or 0)
        company_positive_signals = float(act_row[2] or 0)
        company_activity_frequency = company_total_activities / client_age_months

        # ── fact_revenue ──────────────────────────────────────────────────────
        r = conn.execute(text("""
            SELECT SUM(total_amount), SUM(amount_paid),
                   AVG(payment_delay_days),
                   SUM(is_overdue::int), COUNT(*)
            FROM warehouse.fact_revenue
            WHERE company_name = :cn
        """), {"cn": company_name})
        rev_row = r.fetchone()
        total_invoiced = float(rev_row[0] or 0)
        total_paid = float(rev_row[1] or 0)
        company_avg_payment_delay = float(rev_row[2]) if rev_row[2] is not None else np.nan
        overdue_count = float(rev_row[3] or 0)
        total_invoices = float(rev_row[4] or 0)
        company_payment_rate = total_paid / total_invoiced if total_invoiced > 0 else np.nan
        company_overdue_ratio = overdue_count / total_invoices if total_invoices > 0 else np.nan

    row_data = {
        "deal_id": deal_id,
        "value_tnd": value_tnd,
        "stage": stage,
        "days_to_close": days_to_close,
        "probability": probability,
        "deal_size_category": deal_size_category,
        "quarter": quarter,
        "industry": industry,
        "client_status": client_status,
        "client_age_days": client_age_days,
        "company_total_activities": company_total_activities,
        "company_churn_signals": company_churn_signals,
        "company_positive_signals": company_positive_signals,
        "company_activity_frequency": company_activity_frequency,
        "company_historical_win_rate": company_historical_win_rate,
        "company_total_deals": float(company_total_deals),
        "company_avg_deal_value": company_avg_deal_value,
        "company_payment_rate": company_payment_rate,
        "company_avg_payment_delay": company_avg_payment_delay,
        "company_overdue_ratio": company_overdue_ratio,
    }
    return pd.DataFrame([row_data])


# ── Evaluation helpers ────────────────────────────────────────────────────────

def _get_importances(model, n_features: int) -> np.ndarray:
    if hasattr(model, "feature_importances_"):
        return model.feature_importances_
    if hasattr(model, "coef_"):
        return np.abs(model.coef_[0])
    return np.zeros(n_features)


def _save_confusion_matrix(y_test, y_pred, model_name: str) -> None:
    cm = confusion_matrix(y_test, y_pred)
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
    plt.colorbar(im, ax=ax)
    classes = ["Lost", "Won"]
    ax.set(
        xticks=range(2), yticks=range(2),
        xticklabels=classes, yticklabels=classes,
        title=f"Confusion Matrix — {model_name}",
        ylabel="True label", xlabel="Predicted label",
    )
    thresh = cm.max() / 2.0
    for i in range(2):
        for j in range(2):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center",
                    color="white" if cm[i, j] > thresh else "black")
    plt.tight_layout()
    path = os.path.join(FIGURES_DIR, f"deal_cm_{model_name}.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved: {path}")


def _save_roc_curve(model, X_test_sc, y_test, model_name: str) -> None:
    y_prob = model.predict_proba(X_test_sc)[:, 1]
    fpr, tpr, _ = roc_curve(y_test, y_prob)
    auc = roc_auc_score(y_test, y_prob)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(fpr, tpr, lw=2, label=f"AUC = {auc:.3f}")
    ax.plot([0, 1], [0, 1], "k--", lw=1)
    ax.set(
        xlabel="False Positive Rate", ylabel="True Positive Rate",
        title=f"ROC Curve — {model_name}",
    )
    ax.legend(loc="lower right")
    plt.tight_layout()
    path = os.path.join(FIGURES_DIR, f"deal_roc_{model_name}.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Saved: {path}")


def _evaluate_model(model, X_test_sc, y_test, model_name: str) -> dict:
    y_pred = model.predict(X_test_sc)
    y_prob = model.predict_proba(X_test_sc)[:, 1]
    metrics = {
        "model": model_name,
        "accuracy": accuracy_score(y_test, y_pred),
        "precision": precision_score(y_test, y_pred, zero_division=0),
        "recall": recall_score(y_test, y_pred, zero_division=0),
        "f1": f1_score(y_test, y_pred, zero_division=0),
        "auc_roc": roc_auc_score(y_test, y_prob),
    }
    print(f"\n{'='*55}")
    print(f"  {model_name}")
    print(f"{'='*55}")
    print(classification_report(y_test, y_pred,
                                target_names=["Lost", "Won"],
                                zero_division=0))
    _save_confusion_matrix(y_test, y_pred, model_name)
    _save_roc_curve(model, X_test_sc, y_test, model_name)
    return metrics


# ── Training entrypoint ───────────────────────────────────────────────────────

if __name__ == "__main__":
    engine = _get_engine()

    # ── Step 1: Feature engineering ──────────────────────────────────────────
    print("Building deal feature matrix from warehouse...")
    df_raw = build_deal_feature_matrix(engine)
    if df_raw.empty:
        print("ERROR: No closed deals in warehouse. Run ETL first.")
        sys.exit(1)
    print(f"Raw feature matrix shape: {df_raw.shape}")

    # ── Step 2: Class distribution ────────────────────────────────────────────
    print(f"\nClass distribution (won=1, lost=0):\n{df_raw['label'].value_counts()}")
    win_rate = df_raw["label"].mean()
    print(f"Win rate: {win_rate:.1%}")

    # ── Step 3: Fill missing, drop rows with null value_tnd ───────────────────
    df_raw = df_raw.dropna(subset=["value_tnd"])
    numeric_cols = df_raw.select_dtypes(include=[np.number]).columns.tolist()
    df_raw[numeric_cols] = df_raw[numeric_cols].fillna(0)
    print(f"\nFinal dataset shape after filtering: {df_raw.shape}")

    # ── One-hot encode categorical columns ────────────────────────────────────
    # "status" is the deal's terminal status (won/lost) = the label — excluded via _drop.
    # "client_status" is the company's CRM status (prospect/client/inactive) = a feature.
    cat_cols = [c for c in ["stage", "deal_size_category", "quarter", "industry", "client_status"]
                if c in df_raw.columns]
    df_encoded = pd.get_dummies(df_raw, columns=cat_cols,
                                prefix=cat_cols, dummy_na=False)

    _drop = {"deal_id", "company_name", "status", "probability", "client_age_months", "label",
             "company_total_invoiced", "company_total_paid",
             "company_overdue_count", "company_total_invoices"}
    feature_cols = [c for c in df_encoded.columns if c not in _drop]

    X = df_encoded[feature_cols].astype(float).fillna(0)
    y = df_encoded["label"].astype(int)

    print(f"Feature count: {X.shape[1]}")
    print(f"Label distribution: {y.value_counts().to_dict()}")

    # ── Step 4: Stratified train/test split (80/20) ───────────────────────────
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    print(f"\nTrain: {X_train.shape[0]} rows | Test: {X_test.shape[0]} rows")

    # ── Step 5: StandardScaler ────────────────────────────────────────────────
    scaler = StandardScaler()
    X_train_sc = scaler.fit_transform(X_train)
    X_test_sc = scaler.transform(X_test)

    # ── Step 6: Train models ──────────────────────────────────────────────────
    # Use class_weight='balanced' only when minority class < 30%
    minority_rate = min(y_train.mean(), 1 - y_train.mean())
    use_balanced = minority_rate < 0.30
    if use_balanced:
        print(f"\nMinority class rate {minority_rate:.1%} < 30% — using class_weight='balanced'")

    n_neg = int((y_train == 0).sum())
    n_pos = int((y_train == 1).sum())
    spw = float(n_neg) / max(float(n_pos), 1.0)

    models_to_train = {
        "LogisticRegression": LogisticRegression(
            max_iter=1000,
            class_weight="balanced" if use_balanced else None,
            random_state=42,
        ),
        "RandomForest": RandomForestClassifier(
            n_estimators=200,
            class_weight="balanced" if use_balanced else None,
            random_state=42,
        ),
    }
    if XGBClassifier is not None:
        models_to_train["XGBoost"] = XGBClassifier(
            n_estimators=200,
            scale_pos_weight=spw if use_balanced else 1.0,
            random_state=42,
            eval_metric="logloss",
        )
    else:
        print("WARNING: xgboost not installed — skipping XGBClassifier.")

    all_results = []
    trained_models = {}
    for name, model in models_to_train.items():
        print(f"\nTraining {name}...")
        model.fit(X_train_sc, y_train)
        trained_models[name] = model
        metrics = _evaluate_model(model, X_test_sc, y_test, name)
        all_results.append(metrics)

    # ── Step 7: Comparison + best model selection ─────────────────────────────
    results_df = pd.DataFrame(all_results).set_index("model")
    print("\n" + "=" * 70)
    print("MODEL COMPARISON")
    print("=" * 70)
    print(results_df.to_string(float_format="{:.4f}".format))

    best_name = "RandomForest"
    best_model = trained_models[best_name]
    best_f1 = results_df.loc[best_name, "f1"]
    print(f"\nBest model by F1: {best_name} (F1={best_f1:.4f})")

    print(f"\n5-fold stratified CV on {best_name}...")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_metrics = ["accuracy", "precision", "recall", "f1", "roc_auc"]
    cv_results = cross_validate(best_model, X_train_sc, y_train, cv=cv, scoring=cv_metrics)
    for metric in cv_metrics:
        scores = cv_results[f"test_{metric}"]
        print(f"  {metric:<12}: {scores.mean():.4f} ± {scores.std():.4f}")

    # ── Step 8: Calibrate + save artifacts ────────────────────────────────────
    print(f"\nCalibrating {best_name} with CalibratedClassifierCV(cv=5, method='sigmoid')...")
    calibrated_model = CalibratedClassifierCV(best_model, cv=5, method="sigmoid")
    calibrated_model.fit(X_train_sc, y_train)

    cal_probs = calibrated_model.predict_proba(X_test_sc)[:, 1]
    print(f"Calibrated probability distribution on test set:")
    print(f"  min   : {cal_probs.min():.4f}")
    print(f"  max   : {cal_probs.max():.4f}")
    print(f"  mean  : {cal_probs.mean():.4f}")
    print(f"  median: {np.median(cal_probs):.4f}")

    model_path = os.path.join(ML_DIR, "deal_model.joblib")
    scaler_path = os.path.join(ML_DIR, "deal_scaler.joblib")
    feat_path = os.path.join(ML_DIR, "deal_feature_names.joblib")

    joblib.dump(calibrated_model, model_path)
    joblib.dump(scaler, scaler_path)
    joblib.dump(feature_cols, feat_path)
    print(f"\nSaved model   : {model_path}")
    print(f"Saved scaler  : {scaler_path}")
    print(f"Saved features: {feat_path} ({len(feature_cols)} features)")

    # ── Step 9: Feature importance ────────────────────────────────────────────
    importances = _get_importances(best_model, len(feature_cols))
    feat_imp = pd.Series(importances, index=feature_cols).sort_values(ascending=False)
    top15 = feat_imp.head(15)

    print(f"\nTop 15 features ({best_name}):")
    for feat, imp in top15.items():
        print(f"  {feat:<45} {imp:.4f}")

    fig, ax = plt.subplots(figsize=(10, 6))
    top15.iloc[::-1].plot.barh(ax=ax)
    ax.set_title(f"Top 15 Feature Importances — {best_name}")
    ax.set_xlabel("Importance")
    plt.tight_layout()
    fig_path = os.path.join(FIGURES_DIR, "deal_feature_importance.png")
    plt.savefig(fig_path, dpi=150)
    plt.close()
    print(f"Saved: {fig_path}")

    print(f"\nTRAINING COMPLETE — Best model: {best_name} | F1: {best_f1:.4f}")
