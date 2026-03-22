"""
Unit tests for ReclassifyService and the /tracks/model-status + /tracks/reclassify
endpoints.

Covers:
- reclassify_user_library: correct updated/skipped counts, label distribution
- reclassify_user_library: empty library → zero updated, no UPDATE executed
- reclassify_user_library: raises ModelNotAvailableError when model file absent
- reclassify_user_library: db.commit() called exactly once on success
- reclassify_user_library: bulk UPDATE executed after SELECT
- GET /model-status: available=True when meta + file exist
- GET /model-status: available=False when file absent
- GET /model-status: available=False when meta JSON is empty
- GET /model-status: all 7 required keys present in every response
- POST /reclassify: returns 409 when model not available
- POST /reclassify: returns status=completed on success
"""

import os
import tempfile
from collections import Counter
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import numpy as np
import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.tracks import get_model_status, reclassify_library
from app.services.emotion_classifier import EMOTIONS, EmotionClassifier
from app.services.reclassify_service import ModelNotAvailableError, ReclassifyService

USER_ID = str(uuid4())


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_feature_row(track_id: str = None, emotion: str = "happy"):
    """Return a MagicMock row whose _mapping returns a full feature dict."""
    row = MagicMock()
    row.track_id = track_id or str(uuid4())
    mapping = {
        "track_id":          row.track_id,
        "mfcc_mean":         [float(i) for i in range(13)],
        "mfcc_std":          [0.1 * i for i in range(13)],
        "chroma_mean":       [0.05 * i for i in range(12)],
        "spectral_centroid": 1500.0,
        "zero_crossing_rate": 0.05,
        "rms_energy":        0.12,
        "tempo_librosa":     120.0,
    }
    row._mapping = mapping
    return row


def _make_total_row(total: int):
    row = MagicMock()
    row.total = total
    return row


def _make_db(feat_rows, total: int = None):
    """
    Build a DB mock whose first execute().fetchall() returns feat_rows,
    second execute().fetchone() returns a total-count row,
    and subsequent execute() calls (the UPDATE) are no-ops.
    """
    db = MagicMock()
    total_val = total if total is not None else len(feat_rows)
    call_count = {"n": 0}

    def _execute(stmt, params=None):
        call_count["n"] += 1
        result = MagicMock()
        if call_count["n"] == 1:
            result.fetchall.return_value = feat_rows
        elif call_count["n"] == 2:
            result.fetchone.return_value = _make_total_row(total_val)
        return result

    db.execute.side_effect = _execute
    db.commit = MagicMock()
    return db


def _trained_clf(path: str):
    """Write a real trained EmotionClassifier to the given path using synthetic data."""
    from sklearn.datasets import make_classification
    from app.services.emotion_classifier import FEATURE_DIMS

    n_classes = len(EMOTIONS)
    X, y_idx = make_classification(
        n_samples=n_classes * 15,
        n_features=FEATURE_DIMS,
        n_classes=n_classes,
        n_informative=FEATURE_DIMS,
        n_redundant=0,
        random_state=0,
    )
    y = [EMOTIONS[i % n_classes] for i in y_idx]
    clf = EmotionClassifier()
    clf.train(X.astype(np.float32), y, n_estimators=10, cv=2)
    clf.save(path)
    return clf


# ─── ReclassifyService — happy path ───────────────────────────────────────────

class TestReclassifyServiceHappyPath:
    def _svc_with_model(self, model_path):
        svc = ReclassifyService()
        return svc, model_path

    def test_returns_updated_count_matches_feature_rows(self, tmp_path):
        model_path = str(tmp_path / "clf.joblib")
        _trained_clf(model_path)
        rows = [_make_feature_row() for _ in range(5)]
        db = _make_db(rows)
        svc = ReclassifyService()
        result = svc.reclassify_user_library(USER_ID, db, model_path=model_path)
        assert result["updated"] == 5

    def test_skipped_count_is_total_minus_feat_rows(self, tmp_path):
        model_path = str(tmp_path / "clf.joblib")
        _trained_clf(model_path)
        rows = [_make_feature_row() for _ in range(3)]
        db = _make_db(rows, total=10)  # 10 total, 3 with features
        svc = ReclassifyService()
        result = svc.reclassify_user_library(USER_ID, db, model_path=model_path)
        assert result["skipped"] == 7

    def test_label_distribution_keys_are_valid_emotions(self, tmp_path):
        model_path = str(tmp_path / "clf.joblib")
        _trained_clf(model_path)
        rows = [_make_feature_row() for _ in range(8)]
        db = _make_db(rows)
        svc = ReclassifyService()
        result = svc.reclassify_user_library(USER_ID, db, model_path=model_path)
        for key in result["label_distribution"]:
            assert key in EMOTIONS

    def test_label_distribution_sums_to_updated(self, tmp_path):
        model_path = str(tmp_path / "clf.joblib")
        _trained_clf(model_path)
        rows = [_make_feature_row() for _ in range(6)]
        db = _make_db(rows)
        svc = ReclassifyService()
        result = svc.reclassify_user_library(USER_ID, db, model_path=model_path)
        assert sum(result["label_distribution"].values()) == result["updated"]

    def test_db_commit_called_once(self, tmp_path):
        model_path = str(tmp_path / "clf.joblib")
        _trained_clf(model_path)
        rows = [_make_feature_row() for _ in range(4)]
        db = _make_db(rows)
        svc = ReclassifyService()
        svc.reclassify_user_library(USER_ID, db, model_path=model_path)
        db.commit.assert_called_once()

    def test_db_execute_called_three_times(self, tmp_path):
        """SELECT feats, SELECT total count, then UPDATE — 3 execute calls."""
        model_path = str(tmp_path / "clf.joblib")
        _trained_clf(model_path)
        rows = [_make_feature_row() for _ in range(2)]
        db = _make_db(rows)
        svc = ReclassifyService()
        svc.reclassify_user_library(USER_ID, db, model_path=model_path)
        assert db.execute.call_count == 3


class TestReclassifyServiceEmptyLibrary:
    def test_returns_zero_updated_when_no_features(self, tmp_path):
        model_path = str(tmp_path / "clf.joblib")
        _trained_clf(model_path)
        db = _make_db(feat_rows=[], total=5)
        svc = ReclassifyService()
        result = svc.reclassify_user_library(USER_ID, db, model_path=model_path)
        assert result["updated"] == 0
        assert result["skipped"] == 5

    def test_no_update_executed_when_no_features(self, tmp_path):
        model_path = str(tmp_path / "clf.joblib")
        _trained_clf(model_path)
        db = _make_db(feat_rows=[], total=0)
        svc = ReclassifyService()
        svc.reclassify_user_library(USER_ID, db, model_path=model_path)
        # Only 2 SELECTs, no UPDATE
        assert db.execute.call_count == 2

    def test_commit_not_called_when_nothing_to_update(self, tmp_path):
        model_path = str(tmp_path / "clf.joblib")
        _trained_clf(model_path)
        db = _make_db(feat_rows=[], total=0)
        svc = ReclassifyService()
        svc.reclassify_user_library(USER_ID, db, model_path=model_path)
        db.commit.assert_not_called()


class TestReclassifyServiceModelNotAvailable:
    def test_raises_when_model_file_absent(self):
        svc = ReclassifyService()
        db = _make_db([])
        with pytest.raises(ModelNotAvailableError):
            svc.reclassify_user_library(USER_ID, db, model_path="/nonexistent/clf.joblib")


# ─── GET /tracks/model-status ─────────────────────────────────────────────────

MODEL_STATUS_KEYS = {
    "model_available", "trained_at", "macro_f1", "macro_f1_std",
    "n_samples", "per_class_f1", "can_reclassify",
}

FAKE_META = {
    "macro_f1":     0.81,
    "macro_f1_std": 0.03,
    "n_samples":    1240,
    "trained_at":   "2026-03-20T11:34:00",
    "per_class_f1": {"happy": 0.87, "sad": 0.79},
}


class TestModelStatusEndpoint:
    def test_all_keys_present_when_available(self, tmp_path):
        model_path = str(tmp_path / "clf.joblib")
        open(model_path, "w").close()  # touch the file
        with patch("app.api.v1.endpoints.tracks.EmotionClassifier.load_meta",
                   return_value=FAKE_META), \
             patch("app.api.v1.endpoints.tracks._DEFAULT_MODEL_PATH", model_path):
            result = get_model_status(user_id=USER_ID)
        assert MODEL_STATUS_KEYS == set(result.keys())

    def test_available_true_when_meta_and_file_exist(self, tmp_path):
        model_path = str(tmp_path / "clf.joblib")
        open(model_path, "w").close()
        with patch("app.api.v1.endpoints.tracks.EmotionClassifier.load_meta",
                   return_value=FAKE_META), \
             patch("app.api.v1.endpoints.tracks._DEFAULT_MODEL_PATH", model_path):
            result = get_model_status(user_id=USER_ID)
        assert result["model_available"] is True
        assert result["can_reclassify"]  is True

    def test_macro_f1_matches_meta(self, tmp_path):
        model_path = str(tmp_path / "clf.joblib")
        open(model_path, "w").close()
        with patch("app.api.v1.endpoints.tracks.EmotionClassifier.load_meta",
                   return_value=FAKE_META), \
             patch("app.api.v1.endpoints.tracks._DEFAULT_MODEL_PATH", model_path):
            result = get_model_status(user_id=USER_ID)
        assert result["macro_f1"] == FAKE_META["macro_f1"]

    def test_available_false_when_file_missing(self):
        with patch("app.api.v1.endpoints.tracks.EmotionClassifier.load_meta",
                   return_value=FAKE_META), \
             patch("app.api.v1.endpoints.tracks._DEFAULT_MODEL_PATH",
                   "/nonexistent/clf.joblib"):
            result = get_model_status(user_id=USER_ID)
        assert result["model_available"] is False
        assert result["can_reclassify"]  is False

    def test_available_false_when_meta_empty(self, tmp_path):
        model_path = str(tmp_path / "clf.joblib")
        open(model_path, "w").close()
        with patch("app.api.v1.endpoints.tracks.EmotionClassifier.load_meta",
                   return_value={}), \
             patch("app.api.v1.endpoints.tracks._DEFAULT_MODEL_PATH", model_path):
            result = get_model_status(user_id=USER_ID)
        assert result["model_available"] is False

    def test_all_keys_present_when_unavailable(self):
        with patch("app.api.v1.endpoints.tracks.EmotionClassifier.load_meta",
                   return_value={}), \
             patch("app.api.v1.endpoints.tracks._DEFAULT_MODEL_PATH",
                   "/nonexistent/clf.joblib"):
            result = get_model_status(user_id=USER_ID)
        assert MODEL_STATUS_KEYS == set(result.keys())

    def test_fields_are_none_when_unavailable(self):
        with patch("app.api.v1.endpoints.tracks.EmotionClassifier.load_meta",
                   return_value={}), \
             patch("app.api.v1.endpoints.tracks._DEFAULT_MODEL_PATH",
                   "/nonexistent/clf.joblib"):
            result = get_model_status(user_id=USER_ID)
        for field in ("macro_f1", "macro_f1_std", "n_samples", "per_class_f1", "trained_at"):
            assert result[field] is None


# ─── POST /tracks/reclassify ──────────────────────────────────────────────────

class TestReclassifyEndpoint:
    def test_returns_409_when_model_not_available(self):
        db = MagicMock()
        with patch("app.api.v1.endpoints.tracks._reclassifier.reclassify_user_library",
                   side_effect=ModelNotAvailableError("no model")):
            with pytest.raises(HTTPException) as exc:
                reclassify_library(user_id=USER_ID, db=db)
        assert exc.value.status_code == 409

    def test_returns_completed_status_on_success(self):
        db = MagicMock()
        mock_result = {"updated": 10, "skipped": 2, "label_distribution": {"happy": 10}}
        with patch("app.api.v1.endpoints.tracks._reclassifier.reclassify_user_library",
                   return_value=mock_result):
            result = reclassify_library(user_id=USER_ID, db=db)
        assert result["status"] == "completed"
        assert result["updated"] == 10
        assert result["skipped"] == 2

    def test_label_distribution_included_in_response(self):
        db = MagicMock()
        dist = {"peaceful": 5, "energetic": 3}
        mock_result = {"updated": 8, "skipped": 0, "label_distribution": dist}
        with patch("app.api.v1.endpoints.tracks._reclassifier.reclassify_user_library",
                   return_value=mock_result):
            result = reclassify_library(user_id=USER_ID, db=db)
        assert result["label_distribution"] == dist
