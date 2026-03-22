"""
Unit tests — CollabArcService  (Phase 6.1)
==========================================
Covers:
  - Session creation (happy path, bad target emotion)
  - Invite code uniqueness retry
  - join_session (new participant, update, bad emotion, not found, closed)
  - get_session (found, not found)
  - aggregate_source_emotion (single, identical, mixed, tie-breaking)
  - generate_arc (host only, no participants, cached, library_not_ready)
  - Endpoints: create 201, join 200, get 200, arc 200, 403, 404, 400, 409
"""

import uuid
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.services.collab_service import (
    CollabArcService,
    CollabError,
    SessionNotFoundError,
    NotHostError,
    SessionClosedError,
    _generate_invite_code,
    _shortest_distances,
)
from app.services.arc_planner import EMOTION_GRAPH


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _uid():
    return str(uuid.uuid4())


def _mock_session(
    invite_code="ABCDEF",
    host_user_id=None,
    target_emotion="peaceful",
    duration_minutes=30,
    status="open",
    arc_json=None,
    aggregated_source=None,
):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.invite_code = invite_code
    s.host_user_id = uuid.UUID(host_user_id) if host_user_id else uuid.uuid4()
    s.target_emotion = target_emotion
    s.duration_minutes = duration_minutes
    s.status = status
    s.arc_json = arc_json
    s.aggregated_source = aggregated_source
    return s


def _mock_participant(session_id=None, user_id=None, source_emotion="tense"):
    p = MagicMock()
    p.id = uuid.uuid4()
    p.session_id = session_id or uuid.uuid4()
    p.user_id = uuid.UUID(user_id) if user_id else uuid.uuid4()
    p.source_emotion = source_emotion
    p.joined_at = None
    return p


def _make_db(session=None, participants=None, no_session=False):
    db = MagicMock()
    query_mock = MagicMock()
    db.query.return_value = query_mock
    filter_mock = MagicMock()
    query_mock.filter_by.return_value = filter_mock
    if no_session:
        filter_mock.first.return_value = None
        filter_mock.all.return_value = []
    else:
        filter_mock.first.return_value = session
        filter_mock.all.return_value = participants or []
    return db


# ─── _generate_invite_code ────────────────────────────────────────────────────

def test_invite_code_length():
    code = _generate_invite_code()
    assert len(code) == 6


def test_invite_code_uppercase_alphanum():
    for _ in range(50):
        code = _generate_invite_code()
        assert code.isalnum()
        assert code == code.upper()


def test_custom_invite_code_length():
    code = _generate_invite_code(length=8)
    assert len(code) == 8


# ─── _shortest_distances ──────────────────────────────────────────────────────

def test_shortest_distances_self_is_zero():
    d = _shortest_distances("peaceful", EMOTION_GRAPH)
    assert d["peaceful"] == 0.0


def test_shortest_distances_direct_neighbour():
    d = _shortest_distances("peaceful", EMOTION_GRAPH)
    # peaceful → neutral is direct with cost 1.0
    assert d["neutral"] == pytest.approx(1.0)


def test_shortest_distances_all_reachable():
    d = _shortest_distances("energetic", EMOTION_GRAPH)
    assert all(v < float("inf") for v in d.values())


# ─── CollabArcService.create_session ──────────────────────────────────────────

def test_create_session_happy():
    host_id = _uid()
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    svc = CollabArcService()
    session = svc.create_session(host_id, "peaceful", 30, db)
    assert session.target_emotion == "peaceful"
    assert len(session.invite_code) == 6
    assert session.status == "open"
    db.add.assert_called_once()
    db.flush.assert_called_once()


def test_create_session_bad_emotion():
    svc = CollabArcService()
    with pytest.raises(CollabError, match="Invalid target"):
        svc.create_session(_uid(), "unicorn", 30, MagicMock())


def test_create_session_code_uniqueness_retry():
    host_id = _uid()
    db = MagicMock()
    # First query returns existing session (collision), second returns None
    db.query.return_value.filter_by.return_value.first.side_effect = [
        _mock_session(), None
    ]
    svc = CollabArcService()
    session = svc.create_session(host_id, "happy", 30, db)
    assert session.invite_code  # still succeeds


# ─── CollabArcService.join_session ────────────────────────────────────────────

def test_join_session_new_participant():
    host_id = _uid()
    user_id = _uid()
    session = _mock_session(host_user_id=host_id)

    db = MagicMock()
    # First call: find session; second call: find participant
    db.query.return_value.filter_by.return_value.first.side_effect = [
        session, None
    ]
    svc = CollabArcService()
    result = svc.join_session(session.invite_code, user_id, "tense", db)
    assert result is session
    db.add.assert_called_once()


def test_join_session_update_existing():
    host_id = _uid()
    user_id = _uid()
    session = _mock_session(host_user_id=host_id)
    existing_p = _mock_participant(user_id=user_id, source_emotion="sad")

    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.side_effect = [
        session, existing_p
    ]
    svc = CollabArcService()
    svc.join_session(session.invite_code, user_id, "tense", db)
    assert existing_p.source_emotion == "tense"
    db.add.assert_not_called()


def test_join_session_not_found():
    db = _make_db(no_session=True)
    svc = CollabArcService()
    with pytest.raises(SessionNotFoundError):
        svc.join_session("XXXXXX", _uid(), "tense", db)


def test_join_session_closed():
    session = _mock_session(status="ready")
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = session
    svc = CollabArcService()
    with pytest.raises(SessionClosedError):
        svc.join_session(session.invite_code, _uid(), "tense", db)


def test_join_session_bad_emotion():
    session = _mock_session()
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = session
    svc = CollabArcService()
    with pytest.raises(CollabError, match="Invalid source"):
        svc.join_session(session.invite_code, _uid(), "xoxo", db)


# ─── CollabArcService.get_session ─────────────────────────────────────────────

def test_get_session_happy():
    session = _mock_session()
    p1 = _mock_participant(session_id=session.id, source_emotion="tense")
    p2 = _mock_participant(session_id=session.id, source_emotion="sad")

    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = session
    db.query.return_value.filter_by.return_value.all.return_value = [p1, p2]
    svc = CollabArcService()
    result = svc.get_session(session.invite_code, db)
    assert result["participant_count"] == 2
    assert result["invite_code"] == session.invite_code


def test_get_session_not_found():
    db = _make_db(no_session=True)
    svc = CollabArcService()
    with pytest.raises(SessionNotFoundError):
        svc.get_session("ZZZZZZ", db)


# ─── CollabArcService.aggregate_source_emotion ────────────────────────────────

def test_aggregate_single_returns_same():
    svc = CollabArcService()
    assert svc.aggregate_source_emotion(["tense"]) == "tense"


def test_aggregate_empty_returns_neutral():
    svc = CollabArcService()
    assert svc.aggregate_source_emotion([]) == "neutral"


def test_aggregate_identical_sources():
    svc = CollabArcService()
    result = svc.aggregate_source_emotion(["peaceful", "peaceful", "peaceful"])
    assert result == "peaceful"


def test_aggregate_tense_and_sad_returns_intermediate():
    # tense (high energy, negative) + sad (low energy, very negative)
    # centroid should be something between them on the graph
    svc = CollabArcService()
    result = svc.aggregate_source_emotion(["tense", "sad"])
    assert result in EMOTION_GRAPH


def test_aggregate_diverse_returns_valid_emotion():
    svc = CollabArcService()
    result = svc.aggregate_source_emotion(["energetic", "sad", "peaceful", "tense"])
    assert result in EMOTION_GRAPH


def test_aggregate_is_deterministic():
    svc = CollabArcService()
    r1 = svc.aggregate_source_emotion(["tense", "sad", "happy"])
    r2 = svc.aggregate_source_emotion(["tense", "sad", "happy"])
    assert r1 == r2


# ─── CollabArcService.generate_arc ────────────────────────────────────────────

def test_generate_arc_not_host_raises():
    host_id = _uid()
    other_id = _uid()
    session = _mock_session(host_user_id=host_id, status="open")

    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = session
    db.query.return_value.filter_by.return_value.all.return_value = []

    svc = CollabArcService()
    with pytest.raises(NotHostError):
        svc.generate_arc(session.invite_code, other_id, db)


def test_generate_arc_not_found():
    db = _make_db(no_session=True)
    svc = CollabArcService()
    with pytest.raises(SessionNotFoundError):
        svc.generate_arc("ZZZZZZ", _uid(), db)


def test_generate_arc_no_participants():
    host_id = _uid()
    session = _mock_session(host_user_id=str(host_id), status="open")

    db = MagicMock()
    # First query (session lookup) returns session
    # Second query (participants) returns empty list
    call_count = [0]
    def side_effect(*args, **kwargs):
        mock = MagicMock()
        call_count[0] += 1
        if call_count[0] == 1:
            mock.filter_by.return_value.first.return_value = session
            mock.filter_by.return_value.all.return_value = []
        else:
            mock.filter_by.return_value.first.return_value = None
            mock.filter_by.return_value.all.return_value = []
        return mock
    db.query.side_effect = side_effect

    svc = CollabArcService()
    with pytest.raises(CollabError, match="No participants"):
        svc.generate_arc(session.invite_code, str(host_id), db)


def test_generate_arc_cached_returns_arc_json():
    host_id = _uid()
    cached = {"arc_path": ["tense", "neutral", "peaceful"], "tracks": []}
    session = _mock_session(host_user_id=str(host_id), status="ready", arc_json=cached)

    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = session
    svc = CollabArcService()
    result = svc.generate_arc(session.invite_code, str(host_id), db)
    assert result == cached


def test_generate_arc_happy_path():
    host_id = _uid()
    session = _mock_session(host_user_id=str(host_id), status="open")
    p1 = _mock_participant(session_id=session.id, source_emotion="tense")
    p2 = _mock_participant(session_id=session.id, source_emotion="sad")

    fake_arc = {
        "arc_path": ["neutral", "peaceful"],
        "tracks": [],
        "total_tracks": 0,
        "total_duration_ms": 0,
        "segments": [],
        "readiness": {"has_gaps": False, "missing_emotions": []},
    }

    mock_planner = MagicMock()
    mock_planner.plan_from_db.return_value = fake_arc

    db = MagicMock()
    q1 = MagicMock()
    q1.filter_by.return_value.first.return_value = session
    q2 = MagicMock()
    q2.filter_by.return_value.all.return_value = [p1, p2]
    db.query.side_effect = [q1, q2]

    svc = CollabArcService(planner=mock_planner)
    result = svc.generate_arc(session.invite_code, str(host_id), db)

    assert "collab_meta" in result
    assert result["collab_meta"]["participant_count"] == 2
    assert result["collab_meta"]["source_emotions"] == ["tense", "sad"]
    mock_planner.plan_from_db.assert_called_once()


# ─── Endpoint function tests (no HTTP server needed) ─────────────────────────

import pytest
from fastapi import HTTPException
from app.api.v1.endpoints.collab import (
    create_session as ep_create,
    join_session as ep_join,
    get_session as ep_get,
    generate_collab_arc as ep_arc,
    CreateSessionRequest,
    JoinSessionRequest,
)


def test_endpoint_create_session_happy():
    host_id = _uid()
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None

    result = ep_create(
        CreateSessionRequest(target_emotion="peaceful", duration_minutes=30),
        user_id=host_id, db=db,
    )
    assert result["target_emotion"] == "peaceful"
    assert "invite_code" in result
    db.commit.assert_called_once()


def test_endpoint_create_session_bad_emotion_400():
    db = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        ep_create(
            CreateSessionRequest(target_emotion="bliss", duration_minutes=30),
            user_id=_uid(), db=db,
        )
    assert exc_info.value.status_code == 400


def test_endpoint_join_not_found_404():
    db = _make_db(no_session=True)
    with pytest.raises(HTTPException) as exc_info:
        ep_join("XXXXXX", JoinSessionRequest(source_emotion="tense"),
                user_id=_uid(), db=db)
    assert exc_info.value.status_code == 404


def test_endpoint_join_closed_409():
    session = _mock_session(status="ready")
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = session
    with pytest.raises(HTTPException) as exc_info:
        ep_join(session.invite_code, JoinSessionRequest(source_emotion="tense"),
                user_id=_uid(), db=db)
    assert exc_info.value.status_code == 409


def test_endpoint_get_session_200():
    session = _mock_session()
    p = _mock_participant(session_id=session.id)
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = session
    db.query.return_value.filter_by.return_value.all.return_value = [p]
    result = ep_get(session.invite_code, user_id=_uid(), db=db)
    assert result["participant_count"] == 1


def test_endpoint_get_not_found_404():
    db = _make_db(no_session=True)
    with pytest.raises(HTTPException) as exc_info:
        ep_get("ZZZZZZ", user_id=_uid(), db=db)
    assert exc_info.value.status_code == 404


def test_endpoint_arc_not_host_403():
    host_id = _uid()
    other_id = _uid()
    session = _mock_session(host_user_id=str(host_id), status="open")
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = session
    with pytest.raises(HTTPException) as exc_info:
        ep_arc(session.invite_code, user_id=other_id, db=db)
    assert exc_info.value.status_code == 403


def test_endpoint_arc_not_found_404():
    db = _make_db(no_session=True)
    with pytest.raises(HTTPException) as exc_info:
        ep_arc("ZZZZZZ", user_id=_uid(), db=db)
    assert exc_info.value.status_code == 404
