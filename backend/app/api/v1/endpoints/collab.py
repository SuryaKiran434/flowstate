"""
Collaborative Arc Session Endpoints — Flowstate
-------------------------------------------------
POST /collab/sessions                 — create session (host sets target emotion)
POST /collab/sessions/{code}/join     — join with your source emotion
GET  /collab/sessions/{code}          — view session + all participants
POST /collab/sessions/{code}/arc      — generate shared arc (host only)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user_id
from app.db.session import get_db
from app.services.collab_service import (
    CollabArcService,
    CollabError,
    SessionNotFoundError,
    NotHostError,
    SessionClosedError,
)

router = APIRouter(prefix="/collab", tags=["collab"])
_svc = CollabArcService()


# ─── Request models ───────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    target_emotion:   str = Field(..., description="Desired emotional destination for the group")
    duration_minutes: int = Field(default=30, ge=5, le=120)


class JoinSessionRequest(BaseModel):
    source_emotion: str = Field(..., description="Your current emotional state")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/sessions", status_code=201)
def create_session(
    body: CreateSessionRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Create a new collab session.  Returns an invite code that other users
    can use to join.  The host sets the shared emotional destination.
    """
    try:
        session = _svc.create_session(
            host_user_id=user_id,
            target_emotion=body.target_emotion,
            duration_minutes=body.duration_minutes,
            db=db,
        )
        db.commit()
    except CollabError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "invite_code":      session.invite_code,
        "host_user_id":     str(session.host_user_id),
        "target_emotion":   session.target_emotion,
        "duration_minutes": session.duration_minutes,
        "status":           session.status,
    }


@router.post("/sessions/{invite_code}/join")
def join_session(
    invite_code: str,
    body: JoinSessionRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Join (or update your state in) an open collab session.
    Call this once per user — re-joining updates your source emotion.
    """
    try:
        session = _svc.join_session(
            invite_code=invite_code,
            user_id=user_id,
            source_emotion=body.source_emotion,
            db=db,
        )
        db.commit()
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except SessionClosedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CollabError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "invite_code":    session.invite_code,
        "target_emotion": session.target_emotion,
        "status":         session.status,
        "joined":         True,
    }


@router.get("/sessions/{invite_code}")
def get_session(
    invite_code: str,
    user_id: str = Depends(get_current_user_id),  # noqa: ARG001 — auth guard
    db: Session = Depends(get_db),
):
    """Return session metadata and all participants with their source emotions."""
    try:
        return _svc.get_session(invite_code=invite_code, db=db)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/sessions/{invite_code}/arc")
def generate_collab_arc(
    invite_code: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Generate the shared arc.  Host-only.

    Aggregates all participants' source emotions to find the graph centroid,
    then plans an arc from centroid → target using the host's track library.
    """
    try:
        arc = _svc.generate_arc(
            invite_code=invite_code,
            requesting_user_id=user_id,
            db=db,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NotHostError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except CollabError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if arc.get("error") == "library_not_ready":
        raise HTTPException(status_code=202, detail={
            "error":   "library_not_ready",
            "message": arc["message"],
        })

    return arc
