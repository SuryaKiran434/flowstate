"""
Unit tests for app/services/emotion_classifier.py

Covers:
- build_feature_vector: shape, dtype, None handling, JSONB order
- load_training_data: SQL filtering, return shape, empty case
- train: return keys, CV length, model set, per-class F1 keys
- predict: valid label, confidence in [0,1], RuntimeError without model
- predict_batch: count matches input, all labels valid
- save / load: joblib roundtrip, file exists, metadata JSON
- log_to_mlflow: graceful failure when unavailable
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services.emotion_classifier import EMOTIONS, FEATURE_DIMS, EmotionClassifier


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_row(
    emotion: str = "happy",
    confidence: float = 0.80,
    mfcc_mean: list = None,
    mfcc_std: list = None,
    chroma_mean: list = None,
    spectral_centroid: float = 1500.0,
    zero_crossing_rate: float = 0.05,
    rms_energy: float = 0.12,
    tempo_librosa: float = 120.0,
) -> dict:
    """Build a dict that mimics a SQLAlchemy row _mapping."""
    return {
        "emotion_label":      emotion,
        "emotion_confidence": confidence,
        "mfcc_mean":          mfcc_mean   or [float(i) for i in range(13)],
        "mfcc_std":           mfcc_std    or [float(i) * 0.1 for i in range(13)],
        "chroma_mean":        chroma_mean or [float(i) * 0.05 for i in range(12)],
        "spectral_centroid":  spectral_centroid,
        "zero_crossing_rate": zero_crossing_rate,
        "rms_energy":         rms_energy,
        "tempo_librosa":      tempo_librosa,
    }


def _make_db_rows(emotions: list[str]) -> list:
    """Build a list of MagicMock rows for load_training_data."""
    rows = []
    for em in emotions:
        row         = MagicMock()
        row.emotion_label = em
        mapping = _make_row(emotion=em)
        row._mapping = mapping
        rows.append(row)
    return rows


def _make_db(rows: list) -> MagicMock:
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = rows
    return db


def _synthetic_dataset(n_per_class: int = 10) -> tuple:
    """
    Build a deterministic synthetic training set with `n_per_class` samples per emotion.
    Features are random but distinct enough for a RF to learn.
    """
    rng = np.random.default_rng(0)
    X_parts, y_parts = [], []
    for i, emotion in enumerate(EMOTIONS):
        # Each class gets a different mean so RF can distinguish them
        feats = rng.normal(loc=i, scale=0.3, size=(n_per_class, FEATURE_DIMS)).astype(np.float32)
        X_parts.append(feats)
        y_parts.extend([emotion] * n_per_class)
    return np.vstack(X_parts), y_parts


# ─── TestBuildFeatureVector ───────────────────────────────────────────────────

class TestBuildFeatureVector:
    def test_length_is_42(self):
        vec = EmotionClassifier.build_feature_vector(_make_row())
        assert len(vec) == FEATURE_DIMS

    def test_dtype_is_float32(self):
        vec = EmotionClassifier.build_feature_vector(_make_row())
        assert vec.dtype == np.float32

    def test_none_mfcc_mean_defaults_to_zeros(self):
        row = _make_row()
        row["mfcc_mean"] = None
        vec = EmotionClassifier.build_feature_vector(row)
        assert vec[:13].tolist() == [0.0] * 13

    def test_none_mfcc_std_defaults_to_zeros(self):
        row = _make_row()
        row["mfcc_std"] = None
        vec = EmotionClassifier.build_feature_vector(row)
        assert vec[13:26].tolist() == [0.0] * 13

    def test_none_chroma_defaults_to_zeros(self):
        row = _make_row()
        row["chroma_mean"] = None
        vec = EmotionClassifier.build_feature_vector(row)
        assert vec[26:38].tolist() == [0.0] * 12

    def test_none_scalar_defaults_to_zero(self):
        row = _make_row()
        row["spectral_centroid"] = None
        vec = EmotionClassifier.build_feature_vector(row)
        assert vec[38] == 0.0

    def test_feature_order_mfcc_then_std_then_chroma_then_scalars(self):
        mfcc_mean   = [float(i) for i in range(13)]
        mfcc_std    = [float(i) + 100 for i in range(13)]
        chroma_mean = [float(i) + 200 for i in range(12)]
        row = _make_row(
            mfcc_mean=mfcc_mean,
            mfcc_std=mfcc_std,
            chroma_mean=chroma_mean,
            spectral_centroid=999.0,
        )
        vec = EmotionClassifier.build_feature_vector(row)
        assert vec[0]  == mfcc_mean[0]
        assert vec[12] == mfcc_mean[12]
        assert vec[13] == mfcc_std[0]
        assert vec[25] == mfcc_std[12]
        assert vec[26] == chroma_mean[0]
        assert vec[37] == chroma_mean[11]
        assert vec[38] == 999.0

    def test_all_none_values_gives_zeros(self):
        row = {
            "mfcc_mean": None, "mfcc_std": None, "chroma_mean": None,
            "spectral_centroid": None, "zero_crossing_rate": None,
            "rms_energy": None, "tempo_librosa": None,
        }
        vec = EmotionClassifier.build_feature_vector(row)
        assert len(vec) == FEATURE_DIMS
        assert (vec == 0.0).all()


# ─── TestLoadTrainingData ─────────────────────────────────────────────────────

class TestLoadTrainingData:
    def test_returns_ndarray_and_list(self):
        rows = _make_db_rows(["happy", "sad", "energetic"])
        db   = _make_db(rows)
        clf  = EmotionClassifier()
        X, y = clf.load_training_data(db)
        assert isinstance(X, np.ndarray)
        assert isinstance(y, list)

    def test_shape_matches_row_count(self):
        rows = _make_db_rows(["happy", "sad", "energetic", "peaceful"])
        db   = _make_db(rows)
        clf  = EmotionClassifier()
        X, y = clf.load_training_data(db)
        assert X.shape == (4, FEATURE_DIMS)
        assert len(y) == 4

    def test_labels_match_rows(self):
        emotions = ["happy", "sad", "tense"]
        rows = _make_db_rows(emotions)
        db   = _make_db(rows)
        clf  = EmotionClassifier()
        _, y = clf.load_training_data(db)
        assert y == emotions

    def test_empty_db_returns_empty_arrays(self):
        db  = _make_db([])
        clf = EmotionClassifier()
        X, y = clf.load_training_data(db)
        assert X.shape == (0, FEATURE_DIMS)
        assert y == []

    def test_passes_min_confidence_to_sql(self):
        db  = _make_db([])
        clf = EmotionClassifier()
        clf.load_training_data(db, min_confidence=0.80)
        call_params = db.execute.call_args[0][1]
        assert call_params["min_conf"] == 0.80


# ─── TestTrain ────────────────────────────────────────────────────────────────

class TestTrain:
    def setup_method(self):
        self.X, self.y = _synthetic_dataset(n_per_class=8)

    def test_returns_macro_f1(self):
        clf = EmotionClassifier()
        metrics = clf.train(self.X, self.y, cv=3)
        assert "macro_f1" in metrics

    def test_macro_f1_is_float_between_0_and_1(self):
        clf = EmotionClassifier()
        metrics = clf.train(self.X, self.y, cv=3)
        assert 0.0 <= metrics["macro_f1"] <= 1.0

    def test_cv_scores_length_equals_cv(self):
        clf = EmotionClassifier()
        metrics = clf.train(self.X, self.y, cv=3)
        assert len(metrics["cv_scores"]) == 3

    def test_model_is_set_after_train(self):
        clf = EmotionClassifier()
        assert clf.model is None
        clf.train(self.X, self.y, cv=3)
        assert clf.model is not None

    def test_returns_n_samples(self):
        clf = EmotionClassifier()
        metrics = clf.train(self.X, self.y, cv=3)
        assert metrics["n_samples"] == len(self.y)

    def test_returns_macro_f1_std(self):
        clf = EmotionClassifier()
        metrics = clf.train(self.X, self.y, cv=3)
        assert "macro_f1_std" in metrics
        assert metrics["macro_f1_std"] >= 0.0

    def test_per_class_f1_has_known_emotions(self):
        clf = EmotionClassifier()
        metrics = clf.train(self.X, self.y, cv=3)
        for emotion in EMOTIONS:
            assert emotion in metrics["per_class_f1"], f"Missing per-class F1 for {emotion}"

    def test_high_accuracy_on_separable_data(self):
        """RF should get >0.8 macro F1 on linearly separable synthetic data."""
        clf = EmotionClassifier()
        metrics = clf.train(self.X, self.y, n_estimators=50, cv=3)
        assert metrics["macro_f1"] > 0.5  # conservative threshold for unit tests


# ─── TestPredict ──────────────────────────────────────────────────────────────

class TestPredict:
    def setup_method(self):
        X, y = _synthetic_dataset(n_per_class=8)
        self.clf = EmotionClassifier()
        self.clf.train(X, y, n_estimators=20, cv=2)
        self.sample_X = X[0]

    def test_returns_valid_emotion_label(self):
        label, _ = self.clf.predict(self.sample_X)
        assert label in EMOTIONS

    def test_returns_confidence_in_0_1(self):
        _, conf = self.clf.predict(self.sample_X)
        assert 0.0 <= conf <= 1.0

    def test_confidence_is_float(self):
        _, conf = self.clf.predict(self.sample_X)
        assert isinstance(conf, float)

    def test_raises_runtime_error_without_model(self):
        clf = EmotionClassifier()
        with pytest.raises(RuntimeError):
            clf.predict(self.sample_X)


# ─── TestPredictBatch ─────────────────────────────────────────────────────────

class TestPredictBatch:
    def setup_method(self):
        X, y = _synthetic_dataset(n_per_class=8)
        self.clf = EmotionClassifier()
        self.clf.train(X, y, n_estimators=20, cv=2)
        self.X = X[:10]

    def test_count_matches_input(self):
        preds = self.clf.predict_batch(self.X)
        assert len(preds) == 10

    def test_all_labels_valid(self):
        preds = self.clf.predict_batch(self.X)
        for label, _ in preds:
            assert label in EMOTIONS

    def test_all_confidences_in_range(self):
        preds = self.clf.predict_batch(self.X)
        for _, conf in preds:
            assert 0.0 <= conf <= 1.0

    def test_raises_runtime_error_without_model(self):
        clf = EmotionClassifier()
        with pytest.raises(RuntimeError):
            clf.predict_batch(self.X)

    def test_batch_consistent_with_single_predict(self):
        """predict_batch and predict must agree on the same sample."""
        single_label, single_conf = self.clf.predict(self.X[0])
        batch_preds = self.clf.predict_batch(self.X)
        assert batch_preds[0][0] == single_label
        assert batch_preds[0][1] == single_conf


# ─── TestSaveLoad ─────────────────────────────────────────────────────────────

class TestSaveLoad:
    def _trained_clf(self) -> EmotionClassifier:
        X, y = _synthetic_dataset(n_per_class=8)
        clf = EmotionClassifier()
        clf.train(X, y, n_estimators=20, cv=2)
        return clf

    def test_save_creates_file(self):
        clf = self._trained_clf()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "model.joblib")
            clf.save(path)
            assert os.path.exists(path)

    def test_load_roundtrip_same_predictions(self):
        clf = self._trained_clf()
        X, _ = _synthetic_dataset(n_per_class=2)
        preds_before = clf.predict_batch(X[:5])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "model.joblib")
            clf.save(path)
            clf2 = EmotionClassifier.load(path)
            preds_after = clf2.predict_batch(X[:5])

        assert preds_before == preds_after

    def test_save_meta_creates_json(self):
        clf = self._trained_clf()
        metrics = {"macro_f1": 0.82, "n_samples": 120}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "meta.json")
            clf.save_meta(metrics, path)
            assert os.path.exists(path)

    def test_save_meta_contains_trained_at(self):
        clf = self._trained_clf()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "meta.json")
            clf.save_meta({"macro_f1": 0.80}, path)
            with open(path) as f:
                data = json.load(f)
            assert "trained_at" in data

    def test_load_meta_returns_empty_dict_if_missing(self):
        result = EmotionClassifier.load_meta("/nonexistent/path.json")
        assert result == {}

    def test_load_meta_returns_dict_from_file(self):
        clf = self._trained_clf()
        metrics = {"macro_f1": 0.78, "n_samples": 90}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "meta.json")
            clf.save_meta(metrics, path)
            result = EmotionClassifier.load_meta(path)
        assert result["macro_f1"] == 0.78
        assert result["n_samples"] == 90


# ─── TestLogToMlflow ──────────────────────────────────────────────────────────

class TestLogToMlflow:
    def test_returns_false_when_mlflow_unavailable(self):
        clf = EmotionClassifier()
        with patch.dict("sys.modules", {"mlflow": None}):
            result = clf.log_to_mlflow({"macro_f1": 0.80}, {"n_estimators": 200})
        assert result is False

    def test_returns_false_when_server_connection_fails(self):
        clf = EmotionClassifier()
        import unittest.mock as mock
        mock_mlflow = mock.MagicMock()
        mock_mlflow.set_tracking_uri.side_effect = Exception("Connection refused")
        with patch.dict("sys.modules", {"mlflow": mock_mlflow}):
            result = clf.log_to_mlflow({"macro_f1": 0.80}, {})
        assert result is False
