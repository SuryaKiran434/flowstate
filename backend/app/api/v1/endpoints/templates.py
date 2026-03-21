"""
Arc Template Endpoints — Flowstate
-------------------------------------
Allows users to share arc templates (emotional skeleton, no tracks) that
others can remix against their own library.

POST /api/v1/templates               — publish arc as a shareable template
GET  /api/v1/templates               — list public templates (most-remixed first)
GET  /api/v1/templates/{id}          — get a single template
POST /api/v1/templates/{id}/remix    — generate a new arc using the template's
                                       fixed emotional path + requesting user's tracks
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user_id
from app.db.session import get_db
from app.models.arc_template import ArcTemplate
from app.models.user import User
from app.services.arc_planner import ArcPlanner
from app.services.graph_learner import GraphLearner
from app.services.mood_parser import VALID_EMOTIONS

router  = APIRouter(prefix="/templates", tags=["templates"])
learner = GraphLearner()
_base_planner = ArcPlanner()

_MAX_PAGE = 50


# ─── Request / Response schemas ───────────────────────────────────────────────

class PublishRequest(BaseModel):
    """Publish the current arc as a shareable template."""

    display_name:   str = Field(..., min_length=1, max_length=200)
    description:    Optional[str] = Field(None, max_length=500)
    source_emotion: str
    target_emotion: str
    arc_path:       list[str] = Field(..., min_length=1)
    duration_mins:  int = Field(..., ge=5, le=180)


class RemixRequest(BaseModel):
    """Remix a template against the requesting user's library."""

    duration_mins: Optional[int] = Field(None, ge=5, le=180,
                                         description="Override duration (default: template's)")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_template_or_404(template_id: UUID, db: Session) -> ArcTemplate:
    tmpl = db.query(ArcTemplate).filter(ArcTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Template not found")
    return tmpl


def _template_dict(tmpl: ArcTemplate, author_name: str = "") -> dict:
    return {
        "id":             str(tmpl.id),
        "display_name":   tmpl.display_name,
        "description":    tmpl.description,
        "source_emotion": tmpl.source_emotion,
        "target_emotion": tmpl.target_emotion,
        "arc_path":       tmpl.arc_path,
        "duration_mins":  tmpl.duration_mins,
        "remix_count":    tmpl.remix_count,
        "created_at":     tmpl.created_at.isoformat() if tmpl.created_at else None,
        "author":         author_name,
        "author_id":      str(tmpl.user_id),
    }


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
def publish_template(
    body: PublishRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Publish the current arc as a shareable template.

    Stores the emotional skeleton (source, arc_path, target, duration) but not
    the actual tracks — those are personal to each user's library.
    """
    # Validate all emotions in arc_path
    invalid = [e for e in body.arc_path if e not in VALID_EMOTIONS]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid emotion(s) in arc_path: {invalid}",
        )
    if body.source_emotion not in VALID_EMOTIONS:
        raise HTTPException(status_code=422, detail=f"Invalid source_emotion: {body.source_emotion}")
    if body.target_emotion not in VALID_EMOTIONS:
        raise HTTPException(status_code=422, detail=f"Invalid target_emotion: {body.target_emotion}")

    tmpl = ArcTemplate(
        user_id=user_id,
        display_name=body.display_name,
        description=body.description,
        source_emotion=body.source_emotion,
        target_emotion=body.target_emotion,
        arc_path=body.arc_path,
        duration_mins=body.duration_mins,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return {"template_id": str(tmpl.id)}


@router.get("")
def list_templates(
    limit:  int = Query(default=20, ge=1, le=_MAX_PAGE),
    offset: int = Query(default=0,  ge=0),
    source: Optional[str] = Query(default=None, description="Filter by source emotion"),
    target: Optional[str] = Query(default=None, description="Filter by target emotion"),
    user_id: str = Depends(get_current_user_id),  # noqa: ARG001 — auth gate only
    db: Session = Depends(get_db),
):
    """
    List public arc templates, sorted by remix count (most popular first).
    Optionally filter by source or target emotion.
    """
    q = db.query(ArcTemplate)
    if source and source in VALID_EMOTIONS:
        q = q.filter(ArcTemplate.source_emotion == source)
    if target and target in VALID_EMOTIONS:
        q = q.filter(ArcTemplate.target_emotion == target)

    total  = q.count()
    items  = q.order_by(ArcTemplate.remix_count.desc(), ArcTemplate.created_at.desc()) \
               .offset(offset).limit(limit).all()

    # Batch-load author display names
    author_ids   = list({t.user_id for t in items})
    author_names = {}
    if author_ids:
        users = db.query(User).filter(User.id.in_(author_ids)).all()
        author_names = {str(u.id): (u.display_name or "Unknown") for u in users}

    return {
        "total":     total,
        "templates": [_template_dict(t, author_names.get(str(t.user_id), "")) for t in items],
    }


@router.get("/{template_id}")
def get_template(
    template_id: UUID,
    user_id: str = Depends(get_current_user_id),  # noqa: ARG001
    db: Session = Depends(get_db),
):
    """Return a single template by ID."""
    tmpl   = _get_template_or_404(template_id, db)
    author = db.query(User).filter(User.id == tmpl.user_id).first()
    return _template_dict(tmpl, author.display_name if author else "")


@router.post("/{template_id}/remix")
def remix_template(
    template_id: UUID,
    body: RemixRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Remix a template against the requesting user's own track library.

    Preserves the exact emotional arc_path from the template but selects
    tracks from the requesting user's seeded library, so the same emotional
    journey is built from entirely different music.

    Increments the template's remix_count.
    """
    tmpl     = _get_template_or_404(template_id, db)
    duration = body.duration_mins or tmpl.duration_mins

    # Use personalised graph if the user has enough signal; else global
    user_graph = learner.load_user_graph(user_id, db)
    req_planner = ArcPlanner(graph=user_graph) if user_graph else _base_planner

    arc = req_planner.plan_from_db(
        source=tmpl.source_emotion,
        target=tmpl.target_emotion,
        duration_minutes=duration,
        db=db,
        user_id=user_id,
        fixed_arc_path=tmpl.arc_path,
    )

    if arc.get("error") == "library_not_ready":
        raise HTTPException(status_code=202, detail={
            "error":   "library_not_ready",
            "message": arc["message"],
        })

    # Increment remix counter
    tmpl.remix_count += 1
    db.commit()

    warnings = []
    if arc["readiness"]["has_gaps"]:
        missing = arc["readiness"]["missing_emotions"]
        warnings.append(
            f"No tracks found for: {', '.join(missing)}. "
            "Your library may not have these emotions yet."
        )

    def _track(t) -> dict:
        return {
            "spotify_id":         t.spotify_id,
            "title":              t.title,
            "artist":             t.artist,
            "duration_ms":        t.duration_ms,
            "emotion_label":      t.emotion_label,
            "emotion_confidence": t.emotion_confidence,
            "energy":             t.energy,
            "valence":            t.valence,
            "tempo":              t.tempo,
        }

    def _segment(seg) -> dict:
        return {
            "emotion":          seg["emotion"],
            "segment_index":    seg["segment_index"],
            "energy_direction": seg["energy_direction"],
            "track_count":      seg["track_count"],
            "tracks":           [_track(t) for t in seg["tracks"]],
        }

    return {
        # Template provenance
        "template_id":    str(tmpl.id),
        "template_name":  tmpl.display_name,
        "remixed_from":   str(tmpl.user_id),
        "personalised":   user_graph is not None,

        # Arc structure — same schema as /arc/generate
        "mood_interpretation": (
            tmpl.description or
            f"Remixed: {tmpl.source_emotion} → {tmpl.target_emotion}"
        ),
        "source_emotion":    tmpl.source_emotion,
        "target_emotion":    tmpl.target_emotion,
        "arc_path":          arc["arc_path"],
        "segments":          [_segment(s) for s in arc["segments"]],
        "tracks":            [_track(t) for t in arc["tracks"]],
        "total_tracks":      arc["total_tracks"],
        "total_duration_ms": arc["total_duration_ms"],
        "duration_minutes":  duration,
        "warnings":          warnings,
        "readiness":         arc["readiness"],
    }
