"""
Unit tests for GET /tracks/readiness in app/api/v1/endpoints/tracks.py

Verifies that:
- state="empty" when total_tracks == 0
- state="processing" when tracks exist but no emotions yet
- state="ready" when tracks with emotions exist
- ready_for_arc is False for empty/processing, True for ready
- All 6 required keys are present in every response
- message is non-empty for all states
"""

from unittest.mock import MagicMock, patch

import pytest

import app.api.v1.endpoints.tracks as tracks_module
from app.api.v1.endpoints.tracks import get_library_readiness

REQUIRED_KEYS = {
    "state",
    "total_tracks",
    "tracks_with_features",
    "tracks_with_emotions",
    "ready_for_arc",
    "message",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_db_row(total: int, features: int, emotions: int):
    """Return a MagicMock row with the three count columns."""
    row = MagicMock()
    row.total_tracks = total
    row.tracks_with_features = features
    row.tracks_with_emotions = emotions
    return row


def _make_db(total: int, features: int, emotions: int):
    """Return a MagicMock DB session that returns the given counts."""
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = _make_db_row(total, features, emotions)
    return db


def _call_readiness(total: int, features: int, emotions: int) -> dict:
    db = _make_db(total, features, emotions)
    return get_library_readiness(user_id="uid-1", db=db)


# ─── State logic ──────────────────────────────────────────────────────────────

class TestReadinessStates:
    def test_empty_state_when_no_tracks(self):
        result = _call_readiness(total=0, features=0, emotions=0)
        assert result["state"] == "empty"

    def test_processing_state_tracks_no_emotions(self):
        result = _call_readiness(total=10, features=5, emotions=0)
        assert result["state"] == "processing"

    def test_ready_state_when_emotions_present(self):
        result = _call_readiness(total=20, features=20, emotions=15)
        assert result["state"] == "ready"

    def test_processing_even_if_no_features(self):
        """Tracks exist but zero features and zero emotions → still processing."""
        result = _call_readiness(total=5, features=0, emotions=0)
        assert result["state"] == "processing"


# ─── ready_for_arc flag ────────────────────────────────────────────────────────

class TestReadyForArc:
    def test_false_when_empty(self):
        assert _call_readiness(total=0, features=0, emotions=0)["ready_for_arc"] is False

    def test_false_when_processing(self):
        assert _call_readiness(total=5, features=0, emotions=0)["ready_for_arc"] is False

    def test_true_when_ready(self):
        assert _call_readiness(total=10, features=10, emotions=8)["ready_for_arc"] is True


# ─── Message ──────────────────────────────────────────────────────────────────

class TestReadinessMessage:
    def test_message_non_empty_for_empty_state(self):
        result = _call_readiness(total=0, features=0, emotions=0)
        assert isinstance(result["message"], str)
        assert len(result["message"]) > 0

    def test_message_non_empty_for_processing_state(self):
        result = _call_readiness(total=5, features=0, emotions=0)
        assert isinstance(result["message"], str)
        assert len(result["message"]) > 0

    def test_message_non_empty_for_ready_state(self):
        result = _call_readiness(total=10, features=10, emotions=10)
        assert isinstance(result["message"], str)
        assert len(result["message"]) > 0

    def test_processing_message_contains_track_count(self):
        result = _call_readiness(total=42, features=0, emotions=0)
        assert "42" in result["message"]

    def test_ready_message_contains_emotion_count(self):
        result = _call_readiness(total=50, features=50, emotions=37)
        assert "37" in result["message"]


# ─── Response shape ───────────────────────────────────────────────────────────

class TestResponseShape:
    def test_all_required_keys_present_for_empty(self):
        result = _call_readiness(total=0, features=0, emotions=0)
        assert REQUIRED_KEYS.issubset(result.keys())

    def test_all_required_keys_present_for_processing(self):
        result = _call_readiness(total=5, features=2, emotions=0)
        assert REQUIRED_KEYS.issubset(result.keys())

    def test_all_required_keys_present_for_ready(self):
        result = _call_readiness(total=10, features=10, emotions=10)
        assert REQUIRED_KEYS.issubset(result.keys())

    def test_count_values_match_db_row(self):
        result = _call_readiness(total=7, features=4, emotions=3)
        assert result["total_tracks"] == 7
        assert result["tracks_with_features"] == 4
        assert result["tracks_with_emotions"] == 3

    def test_state_is_string(self):
        for t, f, e in [(0, 0, 0), (5, 0, 0), (10, 10, 8)]:
            result = _call_readiness(total=t, features=f, emotions=e)
            assert isinstance(result["state"], str)
