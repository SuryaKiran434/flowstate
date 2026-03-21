"""
Unit tests for POST /arc/replan — skip-driven arc re-planning.

Covers:
- resolve_replan_source: picks best neighbor toward target
- replan endpoint: correct source when skips < 2 (stays at current emotion)
- replan endpoint: bypasses current emotion when consecutive_skips >= 2
- replan endpoint: excludes already-played tracks from pool
- replan endpoint: 404 on missing/unowned session
- load_track_pool_from_db: excluded_spotify_ids filtering
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.arc import replan_arc, ReplanRequest
from app.services.arc_planner import ArcPlanner, EMOTION_GRAPH


# ─── Helpers ──────────────────────────────────────────────────────────────────

USER_ID    = str(uuid4())
SESSION_ID = uuid4()


def _make_session(source="tense", target="peaceful"):
    s = MagicMock()
    s.id          = SESSION_ID
    s.user_id     = USER_ID
    s.source_emotion = source
    s.target_emotion = target
    return s


def _make_st(position, emotion="tense", skipped=False, played=False, track_id="t1"):
    st = MagicMock()
    st.position      = position
    st.emotion_label = emotion
    st.skipped       = skipped
    st.played        = played
    st.track_id      = track_id
    return st


def _make_db(session, session_tracks):
    db = MagicMock()

    # First query: SessionModel → returns session
    # Second query: SessionTrack → returns ordered list
    q1 = MagicMock()
    q1.filter.return_value.first.return_value = session

    q2 = MagicMock()
    q2.filter.return_value.order_by.return_value.all.return_value = session_tracks

    db.query.side_effect = [q1, q2]
    return db


def _stub_arc_result(source="focused", target="peaceful"):
    return {
        "arc_path":          [source, target],
        "segments":          [
            {"emotion": source, "segment_index": 0, "energy_direction": "descending", "track_count": 2,
             "tracks": [MagicMock(spotify_id="n1", title="New 1", artist="A", duration_ms=200000,
                                  emotion_label=source, emotion_confidence=0.8, energy=0.5, valence=0.5, tempo=100)]},
        ],
        "tracks":            [],
        "total_tracks":      2,
        "total_duration_ms": 400000,
        "readiness": {"has_gaps": False, "missing_emotions": [], "pool_size": 100},
    }


# ─── Tests: ArcPlanner.resolve_replan_source ──────────────────────────────────

class TestResolveReplanSource:
    def test_returns_neighbor_closest_to_target(self):
        planner = ArcPlanner()
        # tense neighbors: energetic, neutral, focused, angry
        # Path from focused → peaceful is 2 steps (focused → peaceful)
        # Path from neutral → peaceful is 2 steps (neutral → peaceful)
        # Path from energetic → peaceful is longer
        result = planner.resolve_replan_source("tense", "peaceful")
        assert result in EMOTION_GRAPH["tense"]  # must be a valid neighbor
        path = planner.find_emotional_path(result, "peaceful")
        assert len(path) <= 3  # should pick a short path

    def test_stays_put_if_no_neighbors(self):
        planner = ArcPlanner(graph={"lonely": {}})
        result = planner.resolve_replan_source("lonely", "peaceful")
        assert result == "lonely"

    def test_known_good_path(self):
        planner = ArcPlanner()
        # From sad, skipping sad → should go to melancholic or neutral (closer to peaceful)
        result = planner.resolve_replan_source("sad", "peaceful")
        assert result in EMOTION_GRAPH["sad"]


# ─── Tests: load_track_pool_from_db with excluded_spotify_ids ─────────────────

class TestLoadTrackPoolExclusion:
    def test_excludes_specified_spotify_ids(self):
        from app.services.arc_planner import TrackCandidate

        row1 = MagicMock()
        row1.track_id           = "uuid-1"
        row1.spotify_id         = "sp1"
        row1.name               = "Track 1"
        row1.artist_names       = "Artist A"
        row1.duration_ms        = 200000
        row1.energy             = 0.8
        row1.valence            = 0.7
        row1.emotion_label      = "energetic"
        row1.emotion_confidence = 0.9
        row1.tempo_librosa      = 140.0

        row2 = MagicMock()
        row2.track_id           = "uuid-2"
        row2.spotify_id         = "sp2"
        row2.name               = "Track 2"
        row2.artist_names       = "Artist B"
        row2.duration_ms        = 180000
        row2.energy             = 0.3
        row2.valence            = 0.4
        row2.emotion_label      = "peaceful"
        row2.emotion_confidence = 0.85
        row2.tempo_librosa      = 80.0

        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [row1, row2]

        planner = ArcPlanner()
        pool = planner.load_track_pool_from_db(db, USER_ID, excluded_spotify_ids={"sp1"})

        assert len(pool) == 1
        assert pool[0].spotify_id == "sp2"

    def test_no_exclusions_returns_all(self):
        row = MagicMock()
        row.track_id           = "uuid-1"
        row.spotify_id         = "sp1"
        row.name               = "Track"
        row.artist_names       = "Artist"
        row.duration_ms        = 200000
        row.energy             = 0.5
        row.valence            = 0.5
        row.emotion_label      = "neutral"
        row.emotion_confidence = 0.75
        row.tempo_librosa      = 100.0

        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [row]

        planner = ArcPlanner()
        pool = planner.load_track_pool_from_db(db, USER_ID)
        assert len(pool) == 1


# ─── Tests: POST /arc/replan endpoint ─────────────────────────────────────────

class TestReplanArc:
    async def test_404_when_session_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc:
            await replan_arc(
                request=ReplanRequest(session_id=SESSION_ID, current_position=2),
                user_id=USER_ID,
                db=db,
            )
        assert exc.value.status_code == 404

    async def test_no_bypass_when_fewer_than_2_consecutive_skips(self):
        session = _make_session("tense", "peaceful")
        # Only 1 skip before position 2
        tracks = [
            _make_st(0, "tense", skipped=False, track_id="t0"),
            _make_st(1, "tense", skipped=True,  track_id="t1"),  # 1 skip
            _make_st(2, "tense", skipped=False, track_id="t2"),  # current
        ]
        db = _make_db(session, tracks)

        stub = _stub_arc_result("tense", "peaceful")
        with patch("app.api.v1.endpoints.arc.planner.plan_from_db", return_value=stub):
            result = await replan_arc(
                request=ReplanRequest(session_id=SESSION_ID, current_position=2),
                user_id=USER_ID,
                db=db,
            )

        assert result["source_emotion"] == "tense"   # no bypass
        assert result["skips_detected"] == 1

    async def test_bypasses_emotion_with_2_consecutive_skips(self):
        session = _make_session("tense", "peaceful")
        tracks = [
            _make_st(0, "tense", skipped=False, track_id="t0"),
            _make_st(1, "tense", skipped=True,  track_id="t1"),
            _make_st(2, "tense", skipped=True,  track_id="t2"),
            _make_st(3, "tense", skipped=False, track_id="t3"),  # current
        ]
        db = _make_db(session, tracks)

        stub = _stub_arc_result("focused", "peaceful")
        captured_source = {}

        def capture_plan(source, target, duration_minutes, db, user_id, excluded_spotify_ids=None):
            captured_source["source"] = source
            return stub

        with patch("app.api.v1.endpoints.arc.planner.plan_from_db", side_effect=capture_plan):
            result = await replan_arc(
                request=ReplanRequest(session_id=SESSION_ID, current_position=3),
                user_id=USER_ID,
                db=db,
            )

        assert result["skips_detected"] == 2
        assert captured_source["source"] != "tense"   # emotion was bypassed

    async def test_excludes_already_seen_tracks(self):
        session = _make_session("tense", "peaceful")
        tracks = [
            _make_st(0, "tense", skipped=False, track_id="sp_prev0"),
            _make_st(1, "tense", skipped=False, track_id="sp_prev1"),
            _make_st(2, "tense", skipped=False, track_id="sp_cur"),  # current
        ]
        db = _make_db(session, tracks)

        stub = _stub_arc_result("tense", "peaceful")
        captured_excl = {}

        def capture_plan(source, target, duration_minutes, db, user_id, excluded_spotify_ids=None):
            captured_excl["ids"] = excluded_spotify_ids
            return stub

        with patch("app.api.v1.endpoints.arc.planner.plan_from_db", side_effect=capture_plan):
            await replan_arc(
                request=ReplanRequest(session_id=SESSION_ID, current_position=2),
                user_id=USER_ID,
                db=db,
            )

        # All tracks at positions 0, 1, 2 should be excluded
        assert "sp_prev0" in captured_excl["ids"]
        assert "sp_prev1" in captured_excl["ids"]
        assert "sp_cur"   in captured_excl["ids"]

    async def test_returns_arc_shape_matching_generate(self):
        session = _make_session("tense", "peaceful")
        tracks = [_make_st(0, "tense", track_id="t0")]
        db = _make_db(session, tracks)

        stub = _stub_arc_result("neutral", "peaceful")
        with patch("app.api.v1.endpoints.arc.planner.plan_from_db", return_value=stub):
            result = await replan_arc(
                request=ReplanRequest(session_id=SESSION_ID, current_position=0),
                user_id=USER_ID,
                db=db,
            )

        # Must have all keys that frontend expects from /arc/generate
        for key in ("arc_path", "segments", "tracks", "total_tracks",
                    "total_duration_ms", "source_emotion", "target_emotion",
                    "warnings", "replan_reason"):
            assert key in result, f"Missing key: {key}"
