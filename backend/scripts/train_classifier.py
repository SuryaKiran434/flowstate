"""
Train Emotion Classifier — Flowstate
--------------------------------------
Loads high-confidence heuristic-labeled tracks from PostgreSQL, trains a
RandomForest emotion classifier, evaluates with 5-fold stratified CV, and saves
the model to backend/models/emotion_classifier.joblib.

Usage:
    cd backend
    DATABASE_URL=postgresql://flowstate:flowstate@localhost:5432/flowstate \\
        python scripts/train_classifier.py

Options:
    --min-confidence  Minimum emotion_confidence for training samples (default: 0.65)
    --n-estimators    Trees in the RandomForest (default: 200)
    --cv              Number of CV folds (default: 5)
    --model-path      Override output path (default: models/emotion_classifier.joblib)
"""

import argparse
import os
import sys

# Add the backend/ directory to sys.path so `app.*` imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sklearn.metrics import classification_report
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.emotion_classifier import EMOTIONS, EmotionClassifier

_DEFAULT_MODEL_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
_DEFAULT_MODEL_PATH = os.path.join(_DEFAULT_MODEL_DIR, "emotion_classifier.joblib")
_DEFAULT_META_PATH  = os.path.join(_DEFAULT_MODEL_DIR, "emotion_classifier_meta.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train the Flowstate emotion classifier from DB pseudo-labels",
    )
    parser.add_argument(
        "--min-confidence", type=float, default=0.65,
        help="Minimum heuristic emotion_confidence to include in training set (default: 0.65)",
    )
    parser.add_argument(
        "--n-estimators", type=int, default=200,
        help="Number of trees in the RandomForest (default: 200)",
    )
    parser.add_argument(
        "--cv", type=int, default=5,
        help="Number of stratified K-fold splits for evaluation (default: 5)",
    )
    parser.add_argument(
        "--model-path", type=str, default=_DEFAULT_MODEL_PATH,
        help=f"Output path for the saved model (default: {_DEFAULT_MODEL_PATH})",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to database…")
    engine  = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    db      = Session()

    print(f"Loading training data (min_confidence={args.min_confidence})…")
    clf = EmotionClassifier()
    X, y = clf.load_training_data(db, min_confidence=args.min_confidence)

    if len(y) < 50:
        print(
            f"WARNING: Only {len(y)} qualifying samples found. "
            f"Need at least 50 to train a meaningful model.",
            file=sys.stderr,
        )
        print("Tip: Lower --min-confidence or run the Airflow DAG to generate more labels.")
        db.close()
        sys.exit(1)

    unique_classes = sorted(set(y))
    print(f"Training on {len(y)} samples  |  {len(unique_classes)} emotion classes")
    print(f"Class distribution:")
    for emotion in unique_classes:
        count = y.count(emotion)
        pct   = 100.0 * count / len(y)
        print(f"    {emotion:<15s}  {count:>4d}  ({pct:.1f}%)")

    print(f"\nFitting RandomForest(n_estimators={args.n_estimators}) with {args.cv}-fold CV…")
    metrics = clf.train(X, y, n_estimators=args.n_estimators, cv=args.cv)

    print(f"\n{'='*55}")
    print(f"  Macro F1 (CV)  : {metrics['macro_f1']:.4f} ± {metrics['macro_f1_std']:.4f}")
    print(f"  CV fold scores : {[round(s, 4) for s in metrics['cv_scores']]}")
    print(f"{'='*55}")

    print("\nPer-class F1 (train set, not CV):")
    for emotion in EMOTIONS:
        f1 = metrics["per_class_f1"].get(emotion, 0.0)
        bar = "█" * int(f1 * 20)
        print(f"    {emotion:<15s}  {f1:.3f}  {bar}")

    # Save model + metadata
    meta_path = args.model_path.replace(".joblib", "_meta.json")
    clf.save(args.model_path)
    clf.save_meta(metrics, meta_path)
    print(f"\nModel saved     : {args.model_path}")
    print(f"Metadata saved  : {meta_path}")

    # Log to MLflow (non-fatal if unavailable)
    logged = clf.log_to_mlflow(
        metrics={
            "macro_f1":     metrics["macro_f1"],
            "macro_f1_std": metrics["macro_f1_std"],
            "n_samples":    metrics["n_samples"],
            **{f"f1_{k}": v for k, v in metrics["per_class_f1"].items()},
        },
        params={
            "min_confidence": args.min_confidence,
            "n_estimators":   args.n_estimators,
            "cv_folds":       args.cv,
        },
    )
    if logged:
        print("MLflow run logged.")
    else:
        print("MLflow unavailable — skipped (not an error).")

    db.close()

    if metrics["macro_f1"] >= 0.75:
        print(f"\nTarget met: macro F1 {metrics['macro_f1']:.3f} >= 0.75")
    else:
        print(
            f"\nNote: macro F1 {metrics['macro_f1']:.3f} < 0.75 target. "
            "Consider more training data or lowering --min-confidence."
        )


if __name__ == "__main__":
    main()
