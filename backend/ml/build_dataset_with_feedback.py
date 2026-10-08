"""
Augments the synthetic historical dataset with real agent/customer corrections
collected in the `ml_feedback` table (see app/services/ml_feedback_service.py) —
the active-learning loop: every time a human overrides the ML classifier's
suggested category/priority, that correction becomes a labeled training example
the next retrain can learn from, instead of being discarded.

Each correction only tells us the true value of the field that was corrected
(category XOR priority) — the other column is left blank, and train.py drops
rows with a blank label before fitting that particular classifier.

Usage: `python ml/build_dataset_with_feedback.py` (run from `backend/`, same as
train.py/generate_dataset.py) — writes data/historical_tickets_augmented.csv.
Can also be called as a function (`build()`) by the admin-triggered retrain
endpoint (app/routers/ml_admin.py) without shelling out to a subprocess.
"""
from pathlib import Path

import pandas as pd

from app.database import SessionLocal
from app.services import ml_feedback_service

BASE_DIR = Path(__file__).resolve().parent.parent
ORIGINAL_DATASET = BASE_DIR / "data" / "historical_tickets.csv"
AUGMENTED_DATASET = BASE_DIR / "data" / "historical_tickets_augmented.csv"


def build() -> tuple[Path, int, int]:
    """Returns (output_path, original_row_count, feedback_row_count)."""
    original = pd.read_csv(ORIGINAL_DATASET)

    db = SessionLocal()
    try:
        feedback_rows = ml_feedback_service.export_training_rows(db)
    finally:
        db.close()

    feedback_df = pd.DataFrame(feedback_rows, columns=["subject", "description", "category", "priority"])
    combined = pd.concat([original, feedback_df], ignore_index=True)
    combined.to_csv(AUGMENTED_DATASET, index=False)

    return AUGMENTED_DATASET, len(original), len(feedback_df)


if __name__ == "__main__":
    path, original_count, feedback_count = build()
    print(f"Wrote {len(pd.read_csv(path))} rows ({original_count} original + {feedback_count} feedback) to {path}")
