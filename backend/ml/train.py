"""
Trains two text classifiers on the historical ticket dataset:
  1. category classifier  -> technical_issue / billing / access_issue / product_bug / urgent_escalation
  2. priority classifier  -> low / medium / high / critical

Both are simple TF-IDF + Logistic Regression pipelines - enough to
demonstrate a real ML workflow (train/test split, evaluation, persisted
artifacts) without needing heavy infrastructure for a POC.
"""
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "historical_tickets.csv"
ARTIFACTS_DIR = BASE_DIR / "ml" / "artifacts"


def build_pipeline() -> Pipeline:
    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(max_features=5000, ngram_range=(1, 2), stop_words="english")),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]
    )


def train_and_save(df: pd.DataFrame, label_col: str, artifact_name: str) -> list[dict]:
    """Train+save one classifier, returning per-class metrics (precision/recall/f1/support)
    as a list of dicts — the shape ml_admin.py's retrain endpoint hands back to the UI,
    so an admin-triggered retrain doesn't need to scrape the printed report text.

    Rows with a blank/missing label for `label_col` are dropped before fitting — the
    active-learning dataset (build_dataset_with_feedback.py) appends corrections that
    only ever supply ONE of the two labels, leaving the other blank."""
    labeled = df[df[label_col].notna() & (df[label_col] != "")]
    X = labeled["text"]
    y = labeled[label_col]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    report = classification_report(y_test, y_pred, zero_division=0, output_dict=True)
    print(f"\n=== {label_col} classifier report ===")
    print(classification_report(y_test, y_pred, zero_division=0))

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACTS_DIR / artifact_name
    joblib.dump(pipeline, out_path)
    print(f"Saved {label_col} model to {out_path}")

    return [
        {
            "label": label,
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "f1_score": metrics["f1-score"],
            "support": metrics["support"],
        }
        for label, metrics in report.items()
        if label not in ("accuracy", "macro avg", "weighted avg")
    ]


def load_dataset(dataset_path: Path) -> pd.DataFrame:
    if not dataset_path.exists():
        raise SystemExit(
            f"Dataset not found at {dataset_path}. Run `python ml/generate_dataset.py` first."
        )
    df = pd.read_csv(dataset_path)
    df["text"] = df["subject"].fillna("") + ". " + df["description"].fillna("")
    return df


def train_all(dataset_path: Path = DATA_PATH) -> dict:
    df = load_dataset(dataset_path)
    category_metrics = train_and_save(df, "category", "category_model.joblib")
    priority_metrics = train_and_save(df, "priority", "priority_model.joblib")
    return {"dataset_rows": len(df), "category_metrics": category_metrics, "priority_metrics": priority_metrics}


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=DATA_PATH,
        help="CSV to train on (default: the synthetic historical dataset). Point this at the "
             "augmented CSV from build_dataset_with_feedback.py to include real corrections.",
    )
    args = parser.parse_args()
    train_all(args.dataset)


if __name__ == "__main__":
    main()
