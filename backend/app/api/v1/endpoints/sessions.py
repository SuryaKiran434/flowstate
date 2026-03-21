"""
Sessions Endpoints — Flowstate
--------------------------------
Manages session lifecycle and per-track telemetry.

POST  /api/v1/sessions                  → create session when arc is generated
PATCH /api/v1/sessions/{session_id}     → update status (active/completed/abandoned)
POST  /api/v1/sessions/{session_id}/events → record a track play or skip event
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from app.core.security import get_current_user_id
from app.db.session import get_db
from app.models.session import Session, SessionTrack

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ─── Request / Response schemas ───────────────────────────────────────────────

class TrackIn(BaseModel):
    track_id:      str
    position:      int
    emotion_label: Optional[str] = None
    arc_segment:   Optional[int] = None


class CreateSessionRequest(BaseModel):
    source_emotion: str
    target_emotion: str
    duration_mins:  int = Field(..., gt=0)
    arc_path:       list[str]
    tracks:         list[TrackIn]


class PatchSessionRequest(BaseModel):
    status: str = Field(..., pattern=r"^(active|completed|abandoned)$")


class TrackEventRequest(BaseModel):
    position: int                        # flat track index within session
    event:    str = Field(..., pattern=r"^(play|skip|complete)$")


# ─── Helpers ──────────────────────────────────────────────────────────────────

_VALID_TRANSITIONS = {
    "generated":  {"active"},
    "active":     {"completed", "abandoned"},
    "completed":  set(),
    "abandoned":  set(),
}


def _get_session_or_404(session_id: UUID, user_id: str, db: DbSession) -> Session:
    s = db.query(Session).filter(
        Session.id == session_id,
        Session.user_id == user_id,
    ).first()
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return s


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest,
    user_id: str = Depends(get_current_user_id),
    db: DbSession = Depends(get_db),
):
    """
    Create a new session when the frontend generates an arc.
    Stores the full ordered track list so telemetry events can be correlated.
    Returns the session id — the frontend persists this for subsequent calls.
    """
    session = Session(
        user_id=user_id,
        source_emotion=body.source_emotion,
        target_emotion=body.target_emotion,
        duration_mins=body.duration_mins,
        arc_path=body.arc_path,
        status="generated",
    )
    db.add(session)
    db.flush()  # populate session.id before inserting tracks

    for t in body.tracks:
        db.add(SessionTrack(
            session_id=session.id,
            track_id=t.track_id,
            position=t.position,
            emotion_label=t.emotion_label,
            arc_segment=t.arc_segment,
        ))

    db.commit()
    return {"session_id": str(session.id)}


@router.patch("/{session_id}", status_code=status.HTTP_200_OK)
async def update_session_status(
    session_id: UUID,
    body: PatchSessionRequest,
    user_id: str = Depends(get_current_user_id),
    db: DbSession = Depends(get_db),
):
    """
    Transition session status.
    Valid transitions: generated→active, active→completed|abandoned.
    """
    session = _get_session_or_404(session_id, user_id, db)

    allowed = _VALID_TRANSITIONS.get(session.status, set())
    if body.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot transition from '{session.status}' to '{body.status}'",
        )

    now = datetime.utcnow()
    session.status = body.status
    if body.status == "active":
        session.started_at = now
    elif body.status in ("completed", "abandoned"):
        session.completed_at = now

    db.commit()
    return {"session_id": str(session.id), "status": session.status}


@router.post("/{session_id}/events", status_code=status.HTTP_200_OK)
async def record_track_event(
    session_id: UUID,
    body: TrackEventRequest,
    user_id: str = Depends(get_current_user_id),
    db: DbSession = Depends(get_db),
):
    """
    Record a play, skip, or complete event for a track in this session.
    Idempotent — calling play twice does not error; played_at is only set once.
    """
    _get_session_or_404(session_id, user_id, db)  # ownership check

    track = db.query(SessionTrack).filter(
        SessionTrack.session_id == session_id,
        SessionTrack.position == body.position,
    ).first()

    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No track at position {body.position} in this session",
        )

    now = datetime.utcnow()
    if body.event == "play":
        track.played = True
        if not track.played_at:
            track.played_at = now
    elif body.event == "skip":
        track.skipped = True
    elif body.event == "complete":
        track.played = True
        if not track.played_at:
            track.played_at = now

    db.commit()
    return {"position": body.position, "event": body.event}
