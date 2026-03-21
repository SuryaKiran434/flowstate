"""
Emotion Classifier — Flowstate
--------------------------------
Supervised multi-class classifier trained on high-confidence heuristic pseudo-labels.

Uses a sklearn Pipeline (StandardScaler → RandomForestClassifier) fitted on the
42-dimensional librosa feature vectors already stored in track_features.

Training data source: heuristic-classified tracks with emotion_confidence >= 0.65.
These are not ground-truth labels but are high-quality enough to bootstrap a
supervised model that generalises better than fixed energy/valence buckets.

Usage:
    clf = EmotionClassifier()
    X, y = clf.load_training_data(db)
    metrics = clf.train(X, y)
    clf.save()

    # Inference
    clf = EmotionClassifier.load()
    label, confidence = clf.predict(feature_vector)
"""

import datetime
import json
import logging
import os

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

EMOTIONS = sorted([
    "angry", "energetic", "euphoric", "focused", "happy",
    "melancholic", "neutral", "nostalgic", "peaceful", "romantic", "sad", "tense",
])
FEATURE_DIMS = 42  # mfcc_mean(13) + mfcc_std(13) + chroma_mean(12) + 4 scalars

_MODELS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "models")
)
_DEFAULT_MODEL_PATH = os.path.join(_MODELS_DIR, "emotion_classifier.joblib")
_DEFAULT_META_PATH  = os.path.join(_MODELS_DIR, "emotion_classifier_meta.json")


# ── Classifier ────────────────────────────────────────────────────────────────

class EmotionClassifier:
    """
    Wraps a sklearn Pipeline for 12-class emotion prediction from librosa features.

    Attributes:
        model: fitted sklearn Pipeline (StandardScaler + RandomForestClassifier),
               or None before train()/load() is called.
    """

    def __init__(self):
        self.model = None  # set by train() or load()

    # ── Feature engineering ───────────────────────────────────────────────────

    @staticmethod
    def build_feature_vector(row: dict) -> np.ndarray:
        """
        Flatten a DB row (or dict) into a 42-dim float32 array.

        Column order:
            mfcc_mean[0..12]  (13)
            mfcc_std[0..12]   (13)
            chroma_mean[0..11](12)
            spectral_centroid (1)
            zero_crossing_rate(1)
            rms_energy        (1)
            tempo_librosa     (1)

        Missing / None values default to 0.0 so the vector is always 42-dim.
        """
        mfcc_mean   = row.get("mfcc_mean")   or [0.0] * 13
        mfcc_std    = row.get("mfcc_std")    or [0.0] * 13
        chroma_mean = row.get("chroma_mean") or [0.0] * 12
        scalars = [
            row.get("spectral_centroid")  or 0.0,
            row.get("zero_crossing_rate") or 0.0,
            row.get("rms_energy")         or 0.0,
            row.get("tempo_librosa")      or 0.0,
        ]
        vec = list(mfcc_mean) + list(mfcc_std) + list(chroma_mean) + scalars
        return np.array(vec, dtype=np.float32)

    # ── Data loading ──────────────────────────────────────────────────────────

    def load_training_data(
        self,
        db,
        min_confidence: float = 0.65,
    ) -> tuple:
        """
        Query high-confidence heuristic labels from track_features as training data.

        Only includes rows where:
          - emotion_label  IS NOT NULL
          - emotion_confidence >= min_confidence   (default 0.65)
          - mfcc_mean      IS NOT NULL             (features extracted)

        Returns:
            (X: np.ndarray shape [n, 42], y: list[str])
            Both are empty when the DB has no qualifying rows.
        """
        rows = db.execute(text("""
            SELECT
                mfcc_mean, mfcc_std, chroma_mean,
                spectral_centroid, zero_crossing_rate, rms_energy, tempo_librosa,
                emotion_label, emotion_confidence
            FROM track_features
            WHERE emotion_label      IS NOT NULL
              AND emotion_confidence >= :min_conf
              AND mfcc_mean          IS NOT NULL
        """), {"min_conf": min_confidence}).fetchall()

        if not rows:
            return np.empty((0, FEATURE_DIMS), dtype=np.float32), []

        X = np.array(
            [self.build_feature_vector(dict(r._mapping)) for r in rows],
            dtype=np.float32,
        )
        y = [r.emotion_label for r in rows]
        return X, y

    # ── Training ──────────────────────────────────────────────────────────────

    def train(
        self,
        X: np.ndarray,
        y: list,
        n_estimators: int = 200,
        cv: int = 5,
    ) -> dict:
        """
        Train a Pipeline(StandardScaler → RandomForest) with stratified K-fold CV.

        Runs cross-validation first to get honest macro-F1 estimates, then fits
        on the full dataset. Sets self.model on completion.

        Args:
            X:            Feature matrix [n_samples, 42].
            y:            Emotion label list [n_samples].
            n_estimators: Trees in the forest (default 200).
            cv:           Number of CV folds (default 5).

        Returns:
            dict with keys: macro_f1, macro_f1_std, cv_scores, per_class_f1, n_samples
        """
        pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf",    RandomForestClassifier(
                n_estimators=n_estimators,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            )),
        ])

        skf       = StratifiedKFold(n_splits=cv, shuffle=True, random_state=42)
        cv_scores = cross_val_score(pipeline, X, y, cv=skf, scoring="f1_macro")

        # Final fit on all data
        pipeline.fit(X, y)
        self.model = pipeline

        y_pred = pipeline.predict(X)
        report = classification_report(y, y_pred, output_dict=True, zero_division=0)

        per_class = {
            label: round(report[label]["f1-score"], 4)
            for label in EMOTIONS
            if label in report
        }

        return {
            "macro_f1":     float(cv_scores.mean()),
            "macro_f1_std": float(cv_scores.std()),
            "cv_scores":    cv_scores.tolist(),
            "per_class_f1": per_class,
            "n_samples":    len(y),
        }

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict(self, features: np.ndarray) -> tuple:
        """
        Predict emotion label + confidence for a single 42-dim feature vector.

        Returns:
            (emotion_label: str, confidence: float)  — confidence is predict_proba max

        Raises:
            RuntimeError if model not loaded.
        """
        if self.model is None:
            raise RuntimeError("Model not loaded — call train() or load() first")
        proba = self.model.predict_proba(features.reshape(1, -1))[0]
        idx   = int(proba.argmax())
        return self.model.classes_[idx], round(float(proba[idx]), 4)

    def predict_batch(self, X: np.ndarray) -> list:
        """
        Vectorized batch prediction.

        Returns:
            list of (emotion_label, confidence) tuples, same length as X.

        Raises:
            RuntimeError if model not loaded.
        """
        if self.model is None:
            raise RuntimeError("Model not loaded — call train() or load() first")
        probas  = self.model.predict_proba(X)
        indices = probas.argmax(axis=1)
        return [
            (self.model.classes_[i], round(float(probas[r, i]), 4))
            for r, i in enumerate(indices)
        ]

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str = None) -> None:
        """Serialize the fitted pipeline to disk with joblib."""
        path = path or _DEFAULT_MODEL_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump(self.model, path)
        log.info("EmotionClassifier saved to %s", path)

    def save_meta(self, metrics: dict, path: str = None) -> None:
        """
        Write a JSON sidecar with metrics + timestamp.
        Used by the DAG quality gate (checks macro_f1 before running reclassification).
        """
        path = path or _DEFAULT_META_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        meta = {
            **metrics,
            "trained_at": datetime.datetime.utcnow().isoformat(),
        }
        with open(path, "w") as f:
            json.dump(meta, f, indent=2)
        log.info("EmotionClassifier metadata saved to %s", path)

    @classmethod
    def load(cls, path: str = None) -> "EmotionClassifier":
        """Deserialize a previously saved classifier."""
        inst = cls()
        inst.model = joblib.load(path or _DEFAULT_MODEL_PATH)
        return inst

    @staticmethod
    def load_meta(path: str = None) -> dict:
        """
        Load metadata JSON sidecar. Returns empty dict if file not found.
        Used by the DAG quality gate.
        """
        p = path or _DEFAULT_META_PATH
        if not os.path.exists(p):
            return {}
        with open(p) as f:
            return json.load(f)

    # ── MLflow ────────────────────────────────────────────────────────────────

    def log_to_mlflow(self, metrics: dict, params: dict) -> bool:
        """
        Log training metrics and params to MLflow experiment "emotion_classifier".

        Returns True on success, False if MLflow server is unavailable or import fails.
        Never raises — graceful offline mode.
        """
        try:
            import mlflow
            tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5001")
            mlflow.set_tracking_uri(tracking_uri)
            mlflow.set_experiment("emotion_classifier")
            with mlflow.start_run():
                # Only log scalar values as metrics
                scalar_metrics = {
                    k: v for k, v in metrics.items()
                    if isinstance(v, (int, float))
                }
                mlflow.log_metrics(scalar_metrics)
                mlflow.log_params(params)
            return True
        except Exception as exc:
            log.debug("MLflow logging skipped: %s", exc)
            return False
