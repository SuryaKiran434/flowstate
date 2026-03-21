"""
Unit tests for context_seeder.py — context-aware arc suggestion.

Covers:
- _time_bucket: correct labels for all hours
- _load_recent_sessions: DB query + serialisation
- _heuristic: correct source/target per time bucket
- _heuristic: adjusts when last session ended on high-energy target
- suggest: Claude success path returns correct fields
- suggest: Claude failure falls back to heuristic
- suggest: no API key uses heuristic directly
- GET /arc/suggest endpoint: returns suggestion shape
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.context_seeder import ContextSeeder, _TIME_HEURISTICS


USER_ID = str(uuid4())


# ─── _time_bucket ─────────────────────────────────────────────────────────────

class TestTimeBucket:
    def test_early_morning(self):
        assert ContextSeeder._time_bucket(7)  == "early morning"
        assert ContextSeeder._time_bucket(6)  == "early morning"
        assert ContextSeeder._time_bucket(9)  == "early morning"

    def test_late_morning(self):
        assert ContextSeeder._time_bucket(10) == "late morning"
        assert ContextSeeder._time_bucket(12) == "late morning"

    def test_afternoon(self):
        assert ContextSeeder._time_bucket(13) == "afternoon"
        assert ContextSeeder._time_bucket(16) == "afternoon"

    def test_early_evening(self):
        assert ContextSeeder._time_bucket(17) == "early evening"
        assert ContextSeeder._time_bucket(19) == "early evening"

    def test_late_evening(self):
        assert ContextSeeder._time_bucket(20) == "late evening"
        assert ContextSeeder._time_bucket(22) == "late evening"

    def test_night(self):
        assert ContextSeeder._time_bucket(23) == "night"
        assert ContextSeeder._time_bucket(0)  == "night"
        assert ContextSeeder._time_bucket(5)  == "night"


# ─── _load_recent_sessions ────────────────────────────────────────────────────

class TestLoadRecentSessions:
    def test_returns_list_from_db(self):
        now  = datetime.now(timezone.utc)
        row  = MagicMock()
        row.source_emotion = "tense"
        row.target_emotion = "peaceful"
        row.status         = "completed"
        row.started_at     = now - timedelta(minutes=30)
        row.completed_at   = now

        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [row]

        seeder  = ContextSeeder()
        result  = seeder._load_recent_sessions(db, USER_ID)

        assert len(result) == 1
        assert result[0]["source"]   == "tense"
        assert result[0]["target"]   == "peaceful"
        assert result[0]["status"]   == "completed"
        assert result[0]["duration"] == 30

    def test_returns_empty_list_on_db_error(self):
        db = MagicMock()
        db.execute.side_effect = Exception("DB down")
        seeder = ContextSeeder()
        assert seeder._load_recent_sessions(db, USER_ID) == []

    def test_handles_null_timestamps(self):
        row = MagicMock()
        row.source_emotion = "happy"
        row.target_emotion = "energetic"
        row.status         = "generated"
        row.started_at     = None
        row.completed_at   = None

        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [row]
        seeder = ContextSeeder()
        result = seeder._load_recent_sessions(db, USER_ID)
        assert result[0]["duration"] is None


# ─── _heuristic ───────────────────────────────────────────────────────────────

class TestHeuristic:
    def test_all_time_buckets_return_valid_emotions(self):
        from app.services.mood_parser import VALID_EMOTIONS
        seeder = ContextSeeder()
        for label in _TIME_HEURISTICS:
            result = seeder._heuristic(label, [], [label])
            assert result["source"] in VALID_EMOTIONS, f"Invalid source for {label}"
            assert result["target"] in VALID_EMOTIONS, f"Invalid target for {label}"
            assert result["source"] != result["target"]

    def test_adjusts_for_high_energy_last_session(self):
        seeder = ContextSeeder()
        recent = [{"source": "tense", "target": "energetic", "status": "completed", "duration": 25}]
        result = seeder._heuristic("late evening", recent, ["late evening"])
        # Post-energetic session → should wind down
        assert result["target"] == "peaceful"
        assert result["source"] == "energetic"

    def test_no_adjustment_for_low_energy_last_session(self):
        seeder   = ContextSeeder()
        recent   = [{"source": "sad", "target": "neutral", "status": "completed", "duration": 20}]
        result   = seeder._heuristic("early morning", recent, ["early morning"])
        # "neutral" is not high-energy → no override, use time heuristic
        expected_source, _ = _TIME_HEURISTICS["early morning"]
        assert result["source"] == expected_source

    def test_method_is_heuristic(self):
        seeder = ContextSeeder()
        result = seeder._heuristic("afternoon", [], ["afternoon"])
        assert result["method"] == "heuristic"

    def test_returns_all_required_keys(self):
        seeder = ContextSeeder()
        result = seeder._heuristic("night", [], ["night"])
        for key in ("source", "target", "interpretation", "confidence", "context_signals", "method"):
            assert key in result


# ─── suggest ──────────────────────────────────────────────────────────────────

class TestSuggest:
    async def test_claude_success_returns_suggestion(self):
        seeder = ContextSeeder()
        seeder.settings = MagicMock()
        seeder.settings.anthropic_api_key = "test-key"

        claude_result = {
            "source":         "tense",
            "target":         "peaceful",
            "interpretation": "It's late evening — time to decompress",
            "confidence":     0.88,
        }
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []

        with patch.object(seeder, "_call_claude", new=AsyncMock(return_value=claude_result)):
            result = await seeder.suggest(USER_ID, db)

        assert result["source"]         == "tense"
        assert result["target"]         == "peaceful"
        assert result["method"]         == "claude"
        assert "context_signals" in result

    async def test_claude_failure_falls_back_to_heuristic(self):
        seeder = ContextSeeder()
        seeder.settings = MagicMock()
        seeder.settings.anthropic_api_key = "test-key"

        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []

        with patch.object(seeder, "_call_claude", new=AsyncMock(side_effect=Exception("API timeout"))):
            result = await seeder.suggest(USER_ID, db)

        assert result["method"] == "heuristic"
        assert "source" in result and "target" in result

    async def test_no_api_key_uses_heuristic(self):
        seeder = ContextSeeder()
        seeder.settings = MagicMock()
        seeder.settings.anthropic_api_key = None

        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []

        result = await seeder.suggest(USER_ID, db)
        assert result["method"] == "heuristic"

    async def test_never_raises(self):
        """suggest() must always return a dict, never raise."""
        seeder = ContextSeeder()
        seeder.settings = MagicMock()
        seeder.settings.anthropic_api_key = None

        db = MagicMock()
        db.execute.side_effect = Exception("complete DB failure")

        result = await seeder.suggest(USER_ID, db)
        assert "source" in result
        assert "target" in result


# ─── GET /arc/suggest endpoint ────────────────────────────────────────────────

class TestSuggestEndpoint:
    async def test_returns_suggestion_shape(self):
        from app.api.v1.endpoints.arc import suggest_arc

        stub = {
            "source":          "neutral",
            "target":          "peaceful",
            "interpretation":  "Afternoon chill",
            "confidence":      0.7,
            "context_signals": ["afternoon"],
            "method":          "heuristic",
        }

        db = MagicMock()
        with patch("app.api.v1.endpoints.arc.seeder.suggest", new=AsyncMock(return_value=stub)):
            result = await suggest_arc(user_id=USER_ID, db=db)

        assert result["source"]         == "neutral"
        assert result["target"]         == "peaceful"
        assert result["method"]         == "heuristic"
        assert result["context_signals"] == ["afternoon"]
