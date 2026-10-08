import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app import schemas
from app.services import ml_feedback_service, ml_service

# ml/ lives alongside app/ under backend/, as a standalone (non-installed) package of
# offline training scripts — add backend/ to sys.path so it's importable here, the same
# way ml_service.py locates ml/artifacts/*.joblib relative to this file.
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ml import train as ml_train  # noqa: E402
from ml import build_dataset_with_feedback  # noqa: E402

router = APIRouter(prefix="/admin/ml", tags=["admin"])


@router.get("/feedback-stats", response_model=schemas.MLFeedbackStatsOut)
def get_feedback_stats(db: Session = Depends(get_db), _=Depends(require_admin)):
    return ml_feedback_service.feedback_stats(db)


@router.post("/retrain", response_model=schemas.MLRetrainResultOut)
def retrain_models(_=Depends(require_admin)):
    """Rebuilds the training CSV (synthetic dataset + every human correction collected
    so far) and retrains both classifiers in-process — the active-learning loop closed
    on demand. Synchronous: the dataset is small enough (a PoC-scale TF-IDF + logistic
    regression fit) that this comfortably finishes within one request/response cycle."""
    dataset_path, original_count, feedback_count = build_dataset_with_feedback.build()
    result = ml_train.train_all(dataset_path)
    ml_service.reload_models()
    return schemas.MLRetrainResultOut(
        dataset_rows=result["dataset_rows"],
        feedback_rows_included=feedback_count,
        category_metrics=result["category_metrics"],
        priority_metrics=result["priority_metrics"],
    )
