"""
Unit tests for session endpoints in app/api/v1/endpoints/sessions.py

Covers:
- POST /sessions    → creates session + session_tracks, returns session_id
- PATCH /sessions/{id} → valid and invalid status transitions
- POST /sessions/{id}/events → play, skip, complete; ownership check
"""

from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.sessions import (
    create_session,
    update_session_status,
    record_track_event,
    CreateSessionRequest,
    PatchSessionRequest,
    TrackEventRequest,
    TrackIn,
)
from app.models.session import Session, SessionTrack


# ─── Helpers ──────────────────────────────────────────────────────────────────

USER_ID = str(uuid4())
SESSION_ID = uuid4()


def _make_db():
    db = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()
    db.add = MagicMock()
    return db


def _make_session(status="generated", session_id=None):
    s = MagicMock(spec=Session)
    s.id = session_id or SESSION_ID
    s.user_id = USER_ID
    s.status = status
    s.started_at = None
    s.completed_at = None
    return s


def _make_track(position=0, played=False, skipped=False, played_at=None):
    t = MagicMock(spec=SessionTrack)
    t.position = position
    t.played = played
    t.skipped = skipped
    t.played_at = played_at
    return t


# ─── POST /sessions ────────────────────────────────────────────────────────────

class TestCreateSession:
    async def test_creates_session_and_tracks(self):
        db = _make_db()

        # Capture the Session object that gets added so we can set its id
        added_objects = []
        def capture_add(obj):
            if isinstance(obj, Session):
                obj.id = SESSION_ID
            added_objects.append(obj)

        db.add.side_effect = capture_add

        body = CreateSessionRequest(
            source_emotion="sad",
            target_emotion="happy",
            duration_mins=30,
            arc_path=["sad", "neutral", "happy"],
            tracks=[
                TrackIn(track_id="t1", position=0, emotion_label="sad", arc_segment=0),
                TrackIn(track_id="t2", position=1, emotion_label="neutral", arc_segment=1),
            ],
        )

        result = await create_session(body=body, user_id=USER_ID, db=db)

        assert result["session_id"] == str(SESSION_ID)
        assert db.add.call_count == 3  # 1 Session + 2 SessionTracks
        db.flush.assert_called_once()
        db.commit.assert_called_once()

    async def test_session_status_defaults_to_generated(self):
        db = _make_db()
        sessions_added = []

        def capture(obj):
            if isinstance(obj, Session):
                obj.id = SESSION_ID
                sessions_added.append(obj)

        db.add.side_effect = capture

        body = CreateSessionRequest(
            source_emotion="tense",
            target_emotion="peaceful",
            duration_mins=20,
            arc_path=["tense", "peaceful"],
            tracks=[TrackIn(track_id="t1", position=0)],
        )

        await create_session(body=body, user_id=USER_ID, db=db)

        assert sessions_added[0].status == "generated"


# ─── PATCH /sessions/{id} ──────────────────────────────────────────────────────

class TestUpdateSessionStatus:
    def _db_with_session(self, session):
        db = _make_db()
        db.query.return_value.filter.return_value.first.return_value = session
        return db

    async def test_generated_to_active_sets_started_at(self):
        session = _make_session("generated")
        db = self._db_with_session(session)

        result = await update_session_status(
            session_id=SESSION_ID,
            body=PatchSessionRequest(status="active"),
            user_id=USER_ID,
            db=db,
        )

        assert result["status"] == "active"
        assert session.started_at is not None
        db.commit.assert_called_once()

    async def test_active_to_completed_sets_completed_at(self):
        session = _make_session("active")
        db = self._db_with_session(session)

        result = await update_session_status(
            session_id=SESSION_ID,
            body=PatchSessionRequest(status="completed"),
            user_id=USER_ID,
            db=db,
        )

        assert result["status"] == "completed"
        assert session.completed_at is not None

    async def test_active_to_abandoned_sets_completed_at(self):
        session = _make_session("active")
        db = self._db_with_session(session)

        await update_session_status(
            session_id=SESSION_ID,
            body=PatchSessionRequest(status="abandoned"),
            user_id=USER_ID,
            db=db,
        )

        assert session.status == "abandoned"
        assert session.completed_at is not None

    async def test_invalid_transition_raises_422(self):
        session = _make_session("generated")  # cannot skip directly to completed
        db = self._db_with_session(session)

        with pytest.raises(HTTPException) as exc:
            await update_session_status(
                session_id=SESSION_ID,
                body=PatchSessionRequest(status="completed"),
                user_id=USER_ID,
                db=db,
            )

        assert exc.value.status_code == 422

    async def test_completed_to_active_raises_422(self):
        session = _make_session("completed")
        db = self._db_with_session(session)

        with pytest.raises(HTTPException) as exc:
            await update_session_status(
                session_id=SESSION_ID,
                body=PatchSessionRequest(status="active"),
                user_id=USER_ID,
                db=db,
            )

        assert exc.value.status_code == 422

    async def test_404_when_session_not_found(self):
        db = _make_db()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc:
            await update_session_status(
                session_id=SESSION_ID,
                body=PatchSessionRequest(status="active"),
                user_id=USER_ID,
                db=db,
            )

        assert exc.value.status_code == 404


# ─── POST /sessions/{id}/events ───────────────────────────────────────────────

class TestRecordTrackEvent:
    def _db_with(self, session, track):
        db = _make_db()
        # First query returns session (ownership check), second returns track
        db.query.return_value.filter.return_value.first.side_effect = [session, track]
        return db

    async def test_play_event_sets_played_and_played_at(self):
        session = _make_session("active")
        track = _make_track(position=0)
        db = self._db_with(session, track)

        result = await record_track_event(
            session_id=SESSION_ID,
            body=TrackEventRequest(position=0, event="play"),
            user_id=USER_ID,
            db=db,
        )

        assert track.played is True
        assert track.played_at is not None
        assert result == {"position": 0, "event": "play"}
        db.commit.assert_called_once()

    async def test_play_does_not_overwrite_played_at(self):
        original_ts = datetime(2025, 1, 1, 12, 0, 0)
        track = _make_track(position=0, played=True, played_at=original_ts)
        session = _make_session("active")
        db = self._db_with(session, track)

        await record_track_event(
            session_id=SESSION_ID,
            body=TrackEventRequest(position=0, event="play"),
            user_id=USER_ID,
            db=db,
        )

        assert track.played_at == original_ts  # unchanged

    async def test_skip_event_sets_skipped(self):
        track = _make_track(position=2)
        session = _make_session("active")
        db = self._db_with(session, track)

        await record_track_event(
            session_id=SESSION_ID,
            body=TrackEventRequest(position=2, event="skip"),
            user_id=USER_ID,
            db=db,
        )

        assert track.skipped is True

    async def test_complete_event_sets_played(self):
        track = _make_track(position=5)
        session = _make_session("active")
        db = self._db_with(session, track)

        await record_track_event(
            session_id=SESSION_ID,
            body=TrackEventRequest(position=5, event="complete"),
            user_id=USER_ID,
            db=db,
        )

        assert track.played is True

    async def test_404_when_track_position_not_found(self):
        session = _make_session("active")
        db = _make_db()
        db.query.return_value.filter.return_value.first.side_effect = [session, None]

        with pytest.raises(HTTPException) as exc:
            await record_track_event(
                session_id=SESSION_ID,
                body=TrackEventRequest(position=99, event="play"),
                user_id=USER_ID,
                db=db,
            )

        assert exc.value.status_code == 404

    async def test_404_when_session_not_owned(self):
        db = _make_db()
        db.query.return_value.filter.return_value.first.return_value = None  # ownership fails

        with pytest.raises(HTTPException) as exc:
            await record_track_event(
                session_id=SESSION_ID,
                body=TrackEventRequest(position=0, event="play"),
                user_id=USER_ID,
                db=db,
            )

        assert exc.value.status_code == 404
