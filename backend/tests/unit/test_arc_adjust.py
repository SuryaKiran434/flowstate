"""
Unit tests for POST /arc/adjust — mid-session natural language arc adjustment.

Covers:
- MoodParser.parse_adjustment: Claude success path
- MoodParser.parse_adjustment: keyword fallback (calm, energy, sad, happy, etc.)
- MoodParser.parse_adjustment: empty command returns original target unchanged
- MoodParser._fallback_adjustment: all keyword branches
- /arc/adjust endpoint: 404 on missing session
- /arc/adjust endpoint: calls parse_adjustment with correct context
- /arc/adjust endpoint: re-plans from current emotion to new target
- /arc/adjust endpoint: returns command_interpretation in response
- /arc/adjust endpoint: source == new_target falls back to session target
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.arc import adjust_arc, AdjustRequest
from app.services.mood_parser import MoodParser


# ─── Helpers ──────────────────────────────────────────────────────────────────

USER_ID    = str(uuid4())
SESSION_ID = uuid4()


def _make_session(source="tense", target="peaceful"):
    s = MagicMock()
    s.id             = SESSION_ID
    s.user_id        = USER_ID
    s.source_emotion = source
    s.target_emotion = target
    return s


def _make_st(position, emotion="tense", track_id="t1"):
    st = MagicMock()
    st.position      = position
    st.emotion_label = emotion
    st.track_id      = track_id
    return st


def _make_db(session, session_tracks):
    db  = MagicMock()
    q1  = MagicMock()
    q1.filter.return_value.first.return_value = session
    q2  = MagicMock()
    q2.filter.return_value.order_by.return_value.all.return_value = session_tracks
    db.query.side_effect = [q1, q2]
    return db


def _stub_arc(source="neutral", target="peaceful"):
    return {
        "arc_path":          [source, target],
        "segments":          [
            {"emotion": source, "segment_index": 0, "energy_direction": "descending",
             "track_count": 1,
             "tracks": [MagicMock(spotify_id="n1", title="T", artist="A",
                                  duration_ms=200000, emotion_label=source,
                                  emotion_confidence=0.8, energy=0.5, valence=0.5, tempo=100)]}
        ],
        "tracks":            [],
        "total_tracks":      1,
        "total_duration_ms": 200000,
        "readiness":         {"has_gaps": False, "missing_emotions": [], "pool_size": 50},
    }


# ─── MoodParser.parse_adjustment ──────────────────────────────────────────────

class TestParseAdjustment:
    async def test_empty_command_returns_original_target(self):
        parser = MoodParser()
        result = await parser.parse_adjustment("tense", "peaceful", "")
        assert result["new_target"] == "peaceful"
        assert result["method"] == "passthrough"

    async def test_whitespace_only_command_returns_original_target(self):
        parser = MoodParser()
        result = await parser.parse_adjustment("tense", "peaceful", "   ")
        assert result["new_target"] == "peaceful"
        assert result["method"] == "passthrough"

    async def test_claude_success_returns_parsed_target(self):
        parser = MoodParser()
        parser.settings = MagicMock()
        parser.settings.anthropic_api_key = "test-key"

        mock_result = {
            "new_target":     "sad",
            "interpretation": "Steering toward heavier territory",
            "action":         "change_target",
        }
        with patch.object(parser, "_call_claude_adjust", new=AsyncMock(return_value=mock_result)):
            result = await parser.parse_adjustment("tense", "peaceful", "make it sadder")

        assert result["new_target"] == "sad"
        assert result["method"] == "claude"
        assert "interpretation" in result

    async def test_claude_failure_falls_back_to_keywords(self):
        parser = MoodParser()
        parser.settings = MagicMock()
        parser.settings.anthropic_api_key = "test-key"

        with patch.object(parser, "_call_claude_adjust", new=AsyncMock(side_effect=Exception("API down"))):
            result = await parser.parse_adjustment("tense", "peaceful", "slow this down")

        assert result["new_target"] == "peaceful"
        assert result["method"] == "fallback"

    async def test_no_api_key_uses_fallback(self):
        parser = MoodParser()
        parser.settings = MagicMock()
        parser.settings.anthropic_api_key = None

        result = await parser.parse_adjustment("tense", "peaceful", "I want more energy")
        assert result["new_target"] == "energetic"
        assert result["method"] == "fallback"


class TestFallbackAdjustment:
    def setup_method(self):
        self.parser = MoodParser()

    def test_calm_keywords(self):
        for word in ["slow", "calm", "relax", "chill", "peaceful", "wind down"]:
            result = self.parser._fallback_adjustment(word, "energetic")
            assert result["new_target"] == "peaceful", f"Failed for word: {word}"

    def test_energy_keywords(self):
        for word in ["energy", "faster", "pump", "intense", "hype"]:
            result = self.parser._fallback_adjustment(word, "peaceful")
            assert result["new_target"] == "energetic", f"Failed for word: {word}"

    def test_sad_keywords(self):
        for word in ["sad", "cry", "depress", "heartbreak", "heavy"]:
            result = self.parser._fallback_adjustment(word, "peaceful")
            assert result["new_target"] == "sad", f"Failed for word: {word}"

    def test_happy_keywords(self):
        for word in ["happy", "upbeat", "better", "positive", "joy"]:
            result = self.parser._fallback_adjustment(word, "sad")
            assert result["new_target"] == "happy", f"Failed for word: {word}"

    def test_nostalgic_keywords(self):
        result = self.parser._fallback_adjustment("nostalgic memories", "happy")
        assert result["new_target"] == "nostalgic"

    def test_romantic_keywords(self):
        result = self.parser._fallback_adjustment("something romantic and intimate", "happy")
        assert result["new_target"] == "romantic"

    def test_focused_keywords(self):
        result = self.parser._fallback_adjustment("I need to focus and study", "happy")
        assert result["new_target"] == "focused"

    def test_unknown_command_keeps_original_target(self):
        result = self.parser._fallback_adjustment("xyzzy unknown gibberish", "melancholic")
        assert result["new_target"] == "melancholic"


# ─── POST /arc/adjust endpoint ────────────────────────────────────────────────

class TestAdjustArc:
    async def test_404_when_session_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc:
            await adjust_arc(
                request=AdjustRequest(
                    session_id=SESSION_ID,
                    current_position=0,
                    command="slow down",
                ),
                user_id=USER_ID,
                db=db,
            )
        assert exc.value.status_code == 404

    async def test_uses_current_track_emotion_as_source(self):
        session = _make_session("tense", "peaceful")
        tracks  = [_make_st(0, "tense", "t0"), _make_st(1, "focused", "t1")]
        db      = _make_db(session, tracks)

        captured = {}
        mock_adj = {"new_target": "sad", "interpretation": "Going sad", "action": "change_target", "method": "claude"}

        def capture_plan(source, target, duration_minutes, db, user_id, excluded_spotify_ids=None):
            captured["source"] = source
            return _stub_arc(source, target)

        with patch("app.api.v1.endpoints.arc.parser.parse_adjustment", new=AsyncMock(return_value=mock_adj)), \
             patch("app.api.v1.endpoints.arc.planner.plan_from_db", side_effect=capture_plan):
            await adjust_arc(
                request=AdjustRequest(session_id=SESSION_ID, current_position=1, command="sadder"),
                user_id=USER_ID,
                db=db,
            )

        # Position 1 → emotion "focused"
        assert captured["source"] == "focused"

    async def test_returns_command_interpretation(self):
        session = _make_session("tense", "peaceful")
        tracks  = [_make_st(0, "tense", "t0")]
        db      = _make_db(session, tracks)

        mock_adj = {
            "new_target":     "nostalgic",
            "interpretation": "Steering toward warm nostalgia",
            "action":         "change_target",
            "method":         "claude",
        }

        with patch("app.api.v1.endpoints.arc.parser.parse_adjustment", new=AsyncMock(return_value=mock_adj)), \
             patch("app.api.v1.endpoints.arc.planner.plan_from_db", return_value=_stub_arc("tense", "nostalgic")):
            result = await adjust_arc(
                request=AdjustRequest(session_id=SESSION_ID, current_position=0, command="nostalgic"),
                user_id=USER_ID,
                db=db,
            )

        assert result["command_interpretation"] == "Steering toward warm nostalgia"
        assert result["target_emotion"] == "nostalgic"
        assert result["command"] == "nostalgic"

    async def test_falls_back_to_session_target_when_new_target_equals_source(self):
        session = _make_session("peaceful", "energetic")
        tracks  = [_make_st(0, "peaceful", "t0")]
        db      = _make_db(session, tracks)

        # Claude returns same emotion as current
        mock_adj = {"new_target": "peaceful", "interpretation": "...", "action": "change_target", "method": "claude"}

        captured = {}

        def capture_plan(source, target, duration_minutes, db, user_id, excluded_spotify_ids=None):
            captured["target"] = target
            return _stub_arc(source, target)

        with patch("app.api.v1.endpoints.arc.parser.parse_adjustment", new=AsyncMock(return_value=mock_adj)), \
             patch("app.api.v1.endpoints.arc.planner.plan_from_db", side_effect=capture_plan):
            await adjust_arc(
                request=AdjustRequest(session_id=SESSION_ID, current_position=0, command="stay peaceful"),
                user_id=USER_ID,
                db=db,
            )

        # Should fall back to original session target
        assert captured["target"] == "energetic"

    async def test_excludes_seen_tracks_from_pool(self):
        session = _make_session("tense", "peaceful")
        tracks  = [_make_st(0, "tense", "seen1"), _make_st(1, "tense", "seen2"), _make_st(2, "tense", "cur")]
        db      = _make_db(session, tracks)

        mock_adj = {"new_target": "peaceful", "interpretation": "...", "action": "change_target", "method": "fallback"}
        captured = {}

        def capture_plan(source, target, duration_minutes, db, user_id, excluded_spotify_ids=None):
            captured["excl"] = excluded_spotify_ids
            return _stub_arc(source, target)

        with patch("app.api.v1.endpoints.arc.parser.parse_adjustment", new=AsyncMock(return_value=mock_adj)), \
             patch("app.api.v1.endpoints.arc.planner.plan_from_db", side_effect=capture_plan):
            await adjust_arc(
                request=AdjustRequest(session_id=SESSION_ID, current_position=2, command="calmer"),
                user_id=USER_ID,
                db=db,
            )

        assert "seen1" in captured["excl"]
        assert "seen2" in captured["excl"]
        assert "cur"   in captured["excl"]

    async def test_response_has_all_required_keys(self):
        session = _make_session("tense", "peaceful")
        tracks  = [_make_st(0, "tense", "t0")]
        db      = _make_db(session, tracks)

        mock_adj = {"new_target": "peaceful", "interpretation": "ok", "action": "change_target", "method": "fallback"}

        with patch("app.api.v1.endpoints.arc.parser.parse_adjustment", new=AsyncMock(return_value=mock_adj)), \
             patch("app.api.v1.endpoints.arc.planner.plan_from_db", return_value=_stub_arc("tense", "peaceful")):
            result = await adjust_arc(
                request=AdjustRequest(session_id=SESSION_ID, current_position=0, command="calm"),
                user_id=USER_ID,
                db=db,
            )

        for key in ("command", "command_interpretation", "parse_method", "source_emotion",
                    "target_emotion", "arc_path", "segments", "tracks", "total_tracks",
                    "total_duration_ms", "warnings"):
            assert key in result, f"Missing key: {key}"
