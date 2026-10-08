from pathlib import Path

import joblib

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "ml" / "artifacts"

_category_model = None
_priority_model = None


def _load_models():
    global _category_model, _priority_model
    if _category_model is None:
        category_path = ARTIFACTS_DIR / "category_model.joblib"
        priority_path = ARTIFACTS_DIR / "priority_model.joblib"
        if not category_path.exists() or not priority_path.exists():
            raise RuntimeError(
                "ML models not found. Run `python ml/generate_dataset.py && python ml/train.py` "
                "from the backend/ directory first."
            )
        _category_model = joblib.load(category_path)
        _priority_model = joblib.load(priority_path)


def predict(subject: str, description: str) -> dict:
    """Predict category + priority for a ticket, with confidence scores."""
    _load_models()
    text = f"{subject}. {description}"

    category_probs = _category_model.predict_proba([text])[0]
    category_classes = _category_model.classes_
    category_idx = category_probs.argmax()

    priority_probs = _priority_model.predict_proba([text])[0]
    priority_classes = _priority_model.classes_
    priority_idx = priority_probs.argmax()

    return {
        "category": category_classes[category_idx],
        "category_confidence": round(float(category_probs[category_idx]), 4),
        "priority": priority_classes[priority_idx],
        "priority_confidence": round(float(priority_probs[priority_idx]), 4),
    }


def models_available() -> bool:
    return (ARTIFACTS_DIR / "category_model.joblib").exists() and (
        ARTIFACTS_DIR / "priority_model.joblib"
    ).exists()


def reload_models() -> None:
    """Drop the cached in-process models so the next predict() call re-reads the .joblib
    files from disk — called after an admin-triggered retrain (routers/ml_admin.py) so a
    freshly retrained model takes effect immediately, without restarting the API process."""
    global _category_model, _priority_model
    _category_model = None
    _priority_model = None
