"""
Churn prediction training pipeline for AXIS ERP.
Trains on warehouse schema: dim_client, fact_deals, fact_activities, fact_revenue.

Run: python -m backend.ml.churn_model
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

# Activity types to pivot into individual feature columns
ACT_COL_MAP = {
    "Appel": "act_appel",
    "Email": "act_email",
    "Réunion": "act_reunion",
    "Task": "act_task",
}
ACTIVITY_TYPES = list(ACT_COL_MAP.keys())


def _get_engine():
    url = os.getenv("DATABASE_URL", "postgresql://erp_user:erp_pass@localhost:5432/erp_db")
    return create_engine(url, pool_pre_ping=True)


def _build_features(conn, company_name: str = None) -> pd.DataFrame:
    """
    Core feature engineering from warehouse tables.
    company_name=None → all companies (training).
    company_name=<str> → single company (inference).
    Returns DataFrame with industry and status as raw strings (not yet encoded).
    """
    today = date.today()
    params = {"cn": company_name} if company_name else {}

    # ── dim_client ────────────────────────────────────────────────────────────
    client_where = "WHERE company_name = :cn" if company_name else "WHERE company_name IS NOT NULL"
    r = conn.execute(text(f"""
        SELECT company_name, industry, status, created_date
        FROM warehouse.dim_client
        {client_where}
    """), params)
    df_clients = pd.DataFrame(r.fetchall(), columns=list(r.keys()))

    if df_clients.empty:
        return pd.DataFrame()

    df_clients["created_date"] = pd.to_datetime(df_clients["created_date"], errors="coerce")
    df_clients["client_age_days"] = (
        pd.Timestamp(today) - df_clients["created_date"]
    ).dt.days.fillna(0).clip(lower=0).astype(float)
    df_clients["client_age_months"] = (df_clients["client_age_days"] / 30.0).clip(lower=1.0)

    # ── fact_activities ───────────────────────────────────────────────────────
    act_extra = "AND company_name = :cn" if company_name else ""
    r = conn.execute(text(f"""
        SELECT company_name, activity_type, activity_date,
               churn_signal::int    AS churn_signal,
               positive_signal::int AS positive_signal
        FROM warehouse.fact_activities
        WHERE company_name IS NOT NULL {act_extra}
    """), params)
    df_acts = pd.DataFrame(r.fetchall(), columns=list(r.keys()))

    act_type_cols = list(ACT_COL_MAP.values())

    if not df_acts.empty:
        df_acts["activity_date"] = pd.to_datetime(df_acts["activity_date"], errors="coerce")
        df_acts["churn_signal"] = pd.to_numeric(df_acts["churn_signal"], errors="coerce").fillna(0)
        df_acts["positive_signal"] = pd.to_numeric(df_acts["positive_signal"], errors="coerce").fillna(0)

        grp_act = df_acts.groupby("company_name").agg(
            total_activities=("activity_type", "count"),
            last_activity_date=("activity_date", "max"),
            churn_signal_count=("churn_signal", "sum"),
            positive_signal_count=("positive_signal", "sum"),
        ).reset_index()
        grp_act["days_since_last_activity"] = (
            pd.Timestamp(today) - grp_act["last_activity_date"]
        ).dt.days.fillna(9999.0).clip(lower=0.0)
        grp_act.drop(columns=["last_activity_date"], inplace=True)

        pivot_df = df_acts[df_acts["activity_type"].isin(ACTIVITY_TYPES)].copy()
        if not pivot_df.empty:
            type_counts = (
                pivot_df.groupby(["company_name", "activity_type"])
                .size()
                .unstack(fill_value=0)
                .rename(columns=ACT_COL_MAP)
            )
        else:
            type_counts = pd.DataFrame(index=pd.Index([], name="company_name"))

        for col in act_type_cols:
            if col not in type_counts.columns:
                type_counts[col] = 0

        grp_act = grp_act.merge(
            type_counts[act_type_cols].reset_index(),
            on="company_name",
            how="left",
        )
        for col in act_type_cols:
            grp_act[col] = grp_act[col].fillna(0)
    else:
        grp_act = df_clients[["company_name"]].copy()
        grp_act["total_activities"] = 0.0
        grp_act["days_since_last_activity"] = 9999.0
        grp_act["churn_signal_count"] = 0.0
        grp_act["positive_signal_count"] = 0.0
        for col in act_type_cols:
            grp_act[col] = 0.0

    # ── fact_deals ────────────────────────────────────────────────────────────
    # stage='Closed' marks terminal deals; status='won'/'lost' encodes outcome.
    deal_extra = "AND company_name = :cn" if company_name else ""
    r = conn.execute(text(f"""
        SELECT company_name, status, stage, value_tnd, days_to_close
        FROM warehouse.fact_deals
        WHERE company_name IS NOT NULL {deal_extra}
    """), params)
    df_deals = pd.DataFrame(r.fetchall(), columns=list(r.keys()))

    if not df_deals.empty:
        df_deals["value_tnd"] = pd.to_numeric(df_deals["value_tnd"], errors="coerce")
        df_deals["days_to_close"] = pd.to_numeric(df_deals["days_to_close"], errors="coerce")
        df_deals["stage_lc"] = df_deals["stage"].fillna("").str.lower().str.strip()
        df_deals["is_won"] = (df_deals["status"] == "won").astype(int)
        df_deals["is_lost"] = (df_deals["status"] == "lost").astype(int)
        df_deals["is_open"] = (df_deals["stage_lc"] != "closed").astype(int)

        grp_deal = df_deals.groupby("company_name").agg(
            total_deals=("status", "count"),
            won_deals=("is_won", "sum"),
            lost_deals=("is_lost", "sum"),
            open_deals=("is_open", "sum"),
            avg_deal_value=("value_tnd", "mean"),
            total_deal_value=("value_tnd", "sum"),
        ).reset_index()

        avg_dtc = (
            df_deals[df_deals["days_to_close"].notna()]
            .groupby("company_name")["days_to_close"]
            .mean()
            .rename("avg_days_to_close")
        )
        grp_deal = grp_deal.merge(avg_dtc, on="company_name", how="left")

        closed_sum = grp_deal["won_deals"] + grp_deal["lost_deals"]
        grp_deal["win_rate"] = np.where(
            closed_sum > 0, grp_deal["won_deals"] / closed_sum, np.nan
        )
    else:
        grp_deal = df_clients[["company_name"]].copy()
        for col in ["total_deals", "won_deals", "lost_deals", "open_deals"]:
            grp_deal[col] = 0.0
        for col in ["win_rate", "avg_deal_value", "total_deal_value", "avg_days_to_close"]:
            grp_deal[col] = np.nan

    # ── fact_revenue ──────────────────────────────────────────────────────────
    rev_extra = "AND company_name = :cn" if company_name else ""
    r = conn.execute(text(f"""
        SELECT company_name, total_amount, amount_paid,
               payment_delay_days, is_overdue::int AS is_overdue
        FROM warehouse.fact_revenue
        WHERE company_name IS NOT NULL {rev_extra}
    """), params)
    df_rev = pd.DataFrame(r.fetchall(), columns=list(r.keys()))

    if not df_rev.empty:
        df_rev["total_amount"] = pd.to_numeric(df_rev["total_amount"], errors="coerce")
        df_rev["amount_paid"] = pd.to_numeric(df_rev["amount_paid"], errors="coerce")
        df_rev["payment_delay_days"] = pd.to_numeric(df_rev["payment_delay_days"], errors="coerce")
        df_rev["is_overdue"] = pd.to_numeric(df_rev["is_overdue"], errors="coerce").fillna(0)

        grp_rev = df_rev.groupby("company_name").agg(
            total_invoiced=("total_amount", "sum"),
            total_paid=("amount_paid", "sum"),
            avg_payment_delay=("payment_delay_days", "mean"),
            overdue_count=("is_overdue", "sum"),
            total_invoices=("total_amount", "count"),
        ).reset_index()

        grp_rev["payment_rate"] = np.where(
            grp_rev["total_invoiced"] > 0,
            grp_rev["total_paid"] / grp_rev["total_invoiced"],
            np.nan,
        )
        grp_rev["overdue_ratio"] = np.where(
            grp_rev["total_invoices"] > 0,
            grp_rev["overdue_count"] / grp_rev["total_invoices"],
            np.nan,
        )
    else:
        grp_rev = df_clients[["company_name"]].copy()
        for col in ["total_invoiced", "total_paid", "overdue_count", "total_invoices"]:
            grp_rev[col] = 0.0
        for col in ["payment_rate", "avg_payment_delay", "overdue_ratio"]:
            grp_rev[col] = np.nan

    # ── Merge all sources ─────────────────────────────────────────────────────
    df = (
        df_clients[["company_name", "industry", "status", "client_age_days", "client_age_months"]]
        .merge(grp_act, on="company_name", how="left")
        .merge(grp_deal, on="company_name", how="left")
        .merge(grp_rev, on="company_name", how="left")
    )

    df["activity_frequency"] = df["total_activities"] / df["client_age_months"]
    df["churn_signal_ratio"] = np.where(
        df["total_activities"] > 0,
        df["churn_signal_count"] / df["total_activities"],
        np.nan,
    )

    return df


def build_feature_matrix(engine) -> pd.DataFrame:
    """Build feature matrix for all companies (used by training pipeline)."""
    with engine.connect() as conn:
        return _build_features(conn, company_name=None)


def build_single_company_features(company_name: str, engine) -> pd.DataFrame:
    """Build feature row for a single company (used by predictor)."""
    with engine.connect() as conn:
        return _build_features(conn, company_name=company_name)


# ── Training helpers ──────────────────────────────────────────────────────────

def _compute_churn_labels(df: pd.DataFrame, threshold: int) -> pd.Series:
    inactivity = df["days_since_last_activity"].fillna(9999) > threshold
    high_churn = df["churn_signal_ratio"].fillna(0) > 0.3
    inactive_status = df["status"].fillna("") == "inactive"
    # win_rate NaN (no closed deals) fills to 1.0 so this condition stays False
    zero_wins = (df["win_rate"].fillna(1.0) == 0.0) & (df["total_deals"].fillna(0) >= 2)
    return (inactivity | high_churn | inactive_status | zero_wins).astype(int)


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
    classes = ["Not Churned", "Churned"]
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
    path = os.path.join(FIGURES_DIR, f"cm_{model_name}.png")
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
    path = os.path.join(FIGURES_DIR, f"roc_{model_name}.png")
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
                                target_names=["Not Churned", "Churned"],
                                zero_division=0))
    _save_confusion_matrix(y_test, y_pred, model_name)
    _save_roc_curve(model, X_test_sc, y_test, model_name)
    return metrics


# ── Training entrypoint ───────────────────────────────────────────────────────

if __name__ == "__main__":
    engine = _get_engine()

    # ── Step 1: Feature engineering ──────────────────────────────────────────
    print("Building feature matrix from warehouse...")
    df_raw = build_feature_matrix(engine)
    if df_raw.empty:
        print("ERROR: No data in warehouse. Run ETL first.")
        sys.exit(1)
    print(f"Raw feature matrix shape: {df_raw.shape}")

    # ── Step 2: Filter companies with < 2 total interactions ─────────────────
    df_raw["total_interactions"] = (
        df_raw["total_activities"].fillna(0)
        + df_raw["total_deals"].fillna(0)
        + df_raw["total_invoices"].fillna(0)
    )
    df_filtered = df_raw[df_raw["total_interactions"] >= 2].copy()
    print(f"\nFiltered dataset shape (>= 2 interactions): {df_filtered.shape}")

    numeric_cols = df_filtered.select_dtypes(include=[np.number]).columns.tolist()
    df_filtered[numeric_cols] = df_filtered[numeric_cols].fillna(0)

    # ── Step 3: Churn label with threshold auto-adjustment ───────────────────
    threshold = 180
    for _ in range(30):
        labels = _compute_churn_labels(df_filtered, threshold)
        rate = labels.mean()
        if 0.20 <= rate <= 0.35:
            break
        if rate < 0.20:
            threshold = max(threshold - 15, 30)
        else:
            threshold = min(threshold + 20, 365)

    df_filtered["churn"] = labels
    print(f"Final inactivity threshold: {threshold} days")
    print(f"Class distribution:\n{df_filtered['churn'].value_counts()}")
    print(f"Churn rate: {df_filtered['churn'].mean():.1%}")

    # ── One-hot encode categorical columns ────────────────────────────────────
    df_encoded = pd.get_dummies(
        df_filtered, columns=["industry", "status"],
        prefix=["industry", "status"], dummy_na=False,
    )

    _drop = {"company_name", "client_age_months", "total_interactions", "churn", "days_since_last_activity"}
    feature_cols = [c for c in df_encoded.columns if c not in _drop]

    X = df_encoded[feature_cols].astype(float)
    y = df_encoded["churn"].astype(int)

    print(f"Feature count: {X.shape[1]}")
    print(f"Churn distribution: {y.value_counts().to_dict()}")

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
    n_neg = int((y_train == 0).sum())
    n_pos = int((y_train == 1).sum())
    spw = float(n_neg) / max(float(n_pos), 1.0)

    models_to_train = {
        "LogisticRegression": LogisticRegression(
            max_iter=1000, class_weight="balanced", random_state=42
        ),
        "RandomForest": RandomForestClassifier(
            n_estimators=200, class_weight="balanced", random_state=42
        ),
    }
    if XGBClassifier is not None:
        models_to_train["XGBoost"] = XGBClassifier(
            n_estimators=200, scale_pos_weight=spw,
            random_state=42, eval_metric="logloss",
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

    best_name = results_df["f1"].idxmax()
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

    model_path = os.path.join(ML_DIR, "churn_model.joblib")
    scaler_path = os.path.join(ML_DIR, "scaler.joblib")
    feat_path = os.path.join(ML_DIR, "feature_names.joblib")

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
    fig_path = os.path.join(FIGURES_DIR, "feature_importance.png")
    plt.savefig(fig_path, dpi=150)
    plt.close()
    print(f"Saved: {fig_path}")

    print(f"\nTRAINING COMPLETE — Best model: {best_name} | F1: {best_f1:.4f}")
