"""
Reclassify Service — Flowstate
--------------------------------
Applies the trained EmotionClassifier model to a user's track library,
overwriting heuristic emotion_label / emotion_confidence values with model
predictions.

Intended to be called:
  - Via POST /tracks/reclassify (on-demand by the user)
  - By the Airflow DAG quality-gate step after a successful training run

The service is stateless: it loads the model fresh on each call to avoid
serving stale predictions if the model is retrained between calls.
"""

import logging
from typing import Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.emotion_classifier import (
    EmotionClassifier,
    _DEFAULT_MODEL_PATH,
)

log = logging.getLogger(__name__)


# ── Typed error ────────────────────────────────────────────────────────────────

class ModelNotAvailableError(Exception):
    """Raised when the classifier .joblib file is absent or cannot be loaded."""


# ── Service ───────────────────────────────────────────────────────────────────

class ReclassifyService:
    """
    Batch-reclassify a user's track library using the trained EmotionClassifier.

    Usage:
        svc = ReclassifyService()
        result = svc.reclassify_user_library(user_id, db)
        # {"updated": 847, "skipped": 12, "label_distribution": {"happy": 134, ...}}
    """

    def reclassify_user_library(
        self,
        user_id: str,
        db: Session,
        model_path: Optional[str] = None,
    ) -> dict:
        """
        Load the trained model and apply it to all tracks in the user's library
        that have extracted audio features (mfcc_mean IS NOT NULL).

        Args:
            user_id:    JWT user UUID string.
            db:         Active SQLAlchemy session.
            model_path: Override model path (used in tests). Defaults to the
                        canonical path next to the backend models/ directory.

        Returns:
            {
                "updated":            int,   # rows written back to track_features
                "skipped":            int,   # tracks with no extracted features
                "label_distribution": dict,  # {emotion: count} for updated rows
            }

        Raises:
            ModelNotAvailableError if the .joblib file does not exist.
        """
        # ── Load model ────────────────────────────────────────────────────────
        try:
            clf = EmotionClassifier.load(path=model_path or _DEFAULT_MODEL_PATH)
        except Exception as exc:
            raise ModelNotAvailableError(
                f"Classifier model not found at {model_path or _DEFAULT_MODEL_PATH}. "
                "Run `python scripts/train_classifier.py` to train it."
            ) from exc

        # ── Load user tracks with extracted features ──────────────────────────
        feat_rows = db.execute(text("""
            SELECT
                tf.track_id,
                tf.mfcc_mean, tf.mfcc_std, tf.chroma_mean,
                tf.spectral_centroid, tf.zero_crossing_rate,
                tf.rms_energy, tf.tempo_librosa
            FROM user_tracks ut
            JOIN track_features tf ON ut.track_id = tf.track_id
            WHERE ut.user_id    = cast(:uid AS uuid)
              AND tf.mfcc_mean  IS NOT NULL
        """), {"uid": user_id}).fetchall()

        # Count total user tracks (including those without features) for skipped calc
        total_row = db.execute(text("""
            SELECT COUNT(DISTINCT ut.track_id) AS total
            FROM user_tracks ut
            LEFT JOIN track_features tf ON ut.track_id = tf.track_id
            WHERE ut.user_id = cast(:uid AS uuid)
        """), {"uid": user_id}).fetchone()
        total_tracks = total_row.total if total_row else 0

        if not feat_rows:
            return {
                "updated":            0,
                "skipped":            total_tracks,
                "label_distribution": {},
            }

        # ── Build feature matrix ───────────────────────────────────────────────
        track_ids = [r.track_id for r in feat_rows]
        X = np.array(
            [EmotionClassifier.build_feature_vector(dict(r._mapping)) for r in feat_rows],
            dtype=np.float32,
        )

        # ── Batch predict ─────────────────────────────────────────────────────
        predictions = clf.predict_batch(X)   # list of (label, confidence)

        # ── Bulk UPDATE using VALUES clause ───────────────────────────────────
        # Build a Python list of dicts for executemany — one round trip per chunk.
        # SQLAlchemy's execute() with a list of dicts uses server-side batching.
        update_params = [
            {"label": label, "confidence": float(conf), "tid": str(track_id)}
            for (label, conf), track_id in zip(predictions, track_ids)
        ]

        db.execute(
            text("""
                UPDATE track_features
                SET    emotion_label      = :label,
                       emotion_confidence = :confidence
                WHERE  track_id = :tid
            """),
            update_params,
        )
        db.commit()

        # ── Build label distribution ───────────────────────────────────────────
        distribution: dict[str, int] = {}
        for label, _ in predictions:
            distribution[label] = distribution.get(label, 0) + 1

        skipped = max(0, total_tracks - len(feat_rows))

        log.info(
            "Reclassified %d tracks for user %s (skipped %d without features)",
            len(feat_rows), user_id, skipped,
        )

        return {
            "updated":            len(feat_rows),
            "skipped":            skipped,
            "label_distribution": distribution,
        }
