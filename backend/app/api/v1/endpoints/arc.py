"""
Arc Endpoints — Flowstate
--------------------------
POST /api/v1/arc/generate   — NL mood → emotionally coherent arc
POST /api/v1/arc/replan     — skip-driven mid-session re-plan
POST /api/v1/arc/adjust     — NL mid-session arc adjustment via Claude
GET  /api/v1/arc/suggest    — context-aware zero-input arc suggestion
GET  /api/v1/arc/user-graph — diagnostic: personalised edge weights
GET  /api/v1/arc/preview    — fast path-only preview (no tracks)
GET  /api/v1/arc/emotions   — valid emotion labels + metadata
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user_id
from app.db.session import get_db
from app.models.session import Session as SessionModel, SessionTrack
from app.services.arc_planner import ArcPlanner, EMOTION_GRAPH, ENERGY_CENTERS
from app.services.context_seeder import ContextSeeder
from app.services.graph_learner import GraphLearner
from app.services.longitudinal_analyzer import LongitudinalAnalyzer
from app.services.mood_parser import MoodParser, EMOTION_DESCRIPTIONS, VALID_EMOTIONS

router = APIRouter(prefix="/arc", tags=["arc"])

planner = ArcPlanner()
parser = MoodParser()
seeder = ContextSeeder()
learner = GraphLearner()
analyzer = LongitudinalAnalyzer()


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _serialize_track(t) -> dict:
    return {
        "spotify_id": t.spotify_id,
        "title": t.title,
        "artist": t.artist,
        "duration_ms": t.duration_ms,
        "emotion_label": t.emotion_label,
        "emotion_confidence": t.emotion_confidence,
        "energy": t.energy,
        "valence": t.valence,
        "tempo": t.tempo,
        "language": getattr(t, "language", "en"),
    }


def _serialize_segment(seg) -> dict:
    return {
        "emotion": seg["emotion"],
        "segment_index": seg["segment_index"],
        "energy_direction": seg["energy_direction"],
        "track_count": seg["track_count"],
        "tracks": [_serialize_track(t) for t in seg["tracks"]],
    }


def _arc_warnings(arc: dict) -> list[str]:
    if arc["readiness"]["has_gaps"]:
        missing = arc["readiness"]["missing_emotions"]
        return [
            f"No tracks found for: {', '.join(missing)}. These segments were skipped."
        ]
    return []


def _get_planner(user_id: str, db) -> tuple[ArcPlanner, bool]:
    """Return (planner_instance, personalised).  Uses per-user graph when available."""
    user_graph = learner.load_user_graph(user_id, db)
    if user_graph:
        return ArcPlanner(graph=user_graph), True
    return planner, False


def _load_session(session_id: UUID, user_id: str, db) -> tuple:
    """Return (session, session_tracks) or raise 404."""
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.id == session_id,
            SessionModel.user_id == user_id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    tracks = (
        db.query(SessionTrack)
        .filter(SessionTrack.session_id == session_id)
        .order_by(SessionTrack.position)
        .all()
    )
    return session, tracks


def _current_emotion(session_tracks, position: int, fallback: str) -> str:
    st = next((t for t in session_tracks if t.position == position), None)
    return st.emotion_label if st and st.emotion_label else fallback


# ─── Request models ───────────────────────────────────────────────────────────


class ArcRequest(BaseModel):
    """Generate a full arc from a natural language mood description."""

    mood_text: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Natural language mood description",
        example="I'm stressed from work and want to wind down",
    )
    duration_minutes: int = Field(default=30, ge=5, le=180)
    # Optional pre-resolved emotions (from /arc/suggest) — skips Claude parsing
    source_emotion: Optional[str] = Field(
        None, description="Pre-resolved source — bypasses mood parsing"
    )
    target_emotion: Optional[str] = Field(
        None, description="Pre-resolved target — bypasses mood parsing"
    )
    # Optional language filter — only use tracks in these languages.
    # The emotion classifier is language-agnostic (audio features only), so
    # emotional coherence is preserved regardless of which languages are selected.
    language_filter: Optional[list[str]] = Field(
        None, description="BCP-47 language codes to include, e.g. ['en', 'hi', 'te']"
    )


class ArcPreviewRequest(BaseModel):
    """Fast path-only arc preview."""

    source_emotion: str = Field(..., description="Starting emotion label")
    target_emotion: str = Field(..., description="Target emotion label")


class ReplanRequest(BaseModel):
    """Mid-session re-plan triggered by skip behaviour."""

    session_id: UUID
    current_position: int = Field(..., ge=0)
    remaining_duration_minutes: int = Field(default=20, ge=1, le=120)


class AdjustRequest(BaseModel):
    """Mid-session natural language arc adjustment."""

    session_id: UUID
    current_position: int = Field(..., ge=0)
    command: str = Field(..., min_length=1, max_length=300)
    remaining_duration_minutes: int = Field(default=20, ge=1, le=120)


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/generate")
async def generate_arc(
    request: ArcRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Main arc generation endpoint.

    1. Parse mood_text → (source, target) via Claude (or use pre-resolved pair)
    2. Load personalised emotion graph (falls back to global if < 5 signals)
    3. Run ArcPlanner Dijkstra → select + sequence tracks
    4. Return ordered playlist with full arc metadata
    """
    # Step 1 — resolve emotions
    pre = (
        request.source_emotion
        and request.target_emotion
        and request.source_emotion in VALID_EMOTIONS
        and request.target_emotion in VALID_EMOTIONS
        and request.source_emotion != request.target_emotion
    )
    if pre:
        source = request.source_emotion
        target = request.target_emotion
        mood = {
            "source": source,
            "target": target,
            "interpretation": request.mood_text,
            "method": "preresolved",
        }
    else:
        mood = await parser.parse(request.mood_text)
        source = mood["source"]
        target = mood["target"]

    # Step 2 — personalised planner
    req_planner, personalised = _get_planner(user_id, db)

    # Step 3 — plan (with optional language filter)
    arc = req_planner.plan_from_db(
        source=source,
        target=target,
        duration_minutes=request.duration_minutes,
        db=db,
        user_id=user_id,
        language_filter=request.language_filter or None,
    )

    if arc.get("error") == "library_not_ready":
        raise HTTPException(
            status_code=202,
            detail={
                "error": "library_not_ready",
                "message": arc["message"],
            },
        )

    return {
        "mood_input": request.mood_text,
        "mood_interpretation": mood["interpretation"],
        "parse_method": mood["method"],
        "personalised": personalised,
        "source_emotion": source,
        "target_emotion": target,
        "arc_path": arc["arc_path"],
        "segments": [_serialize_segment(s) for s in arc["segments"]],
        "tracks": [_serialize_track(t) for t in arc["tracks"]],
        "total_tracks": arc["total_tracks"],
        "total_duration_ms": arc["total_duration_ms"],
        "duration_minutes": request.duration_minutes,
        "warnings": _arc_warnings(arc),
        "readiness": arc["readiness"],
    }


@router.post("/replan")
async def replan_arc(
    request: ReplanRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Mid-session arc re-planning triggered by skip behaviour.

    1. Load session + tracks (ownership check)
    2. Count consecutive skips in current emotion segment
    3. Bypass current emotion if 2+ skips (pick best neighbor toward target)
    4. Exclude already-seen tracks; re-plan with personalised graph
    """
    session, session_tracks = _load_session(request.session_id, user_id, db)

    current_emotion = _current_emotion(
        session_tracks, request.current_position, session.source_emotion
    )
    target_emotion = session.target_emotion

    # Count consecutive backward skips in the current emotion segment
    consecutive_skips = 0
    prior = [t for t in session_tracks if t.position < request.current_position]
    for st in reversed(prior):
        if st.skipped and st.emotion_label == current_emotion:
            consecutive_skips += 1
        else:
            break

    if consecutive_skips >= 2:
        replan_source = planner.resolve_replan_source(current_emotion, target_emotion)
        replan_reason = (
            f"Bypassed '{current_emotion}' after {consecutive_skips} consecutive skips"
        )
    else:
        replan_source = current_emotion
        replan_reason = "Re-routed from current emotional position"

    excluded_ids = {
        t.track_id for t in session_tracks if t.position <= request.current_position
    }

    req_planner, personalised = _get_planner(user_id, db)
    arc = req_planner.plan_from_db(
        source=replan_source,
        target=target_emotion,
        duration_minutes=request.remaining_duration_minutes,
        db=db,
        user_id=user_id,
        excluded_spotify_ids=excluded_ids,
    )

    if arc.get("error") == "library_not_ready":
        raise HTTPException(
            status_code=202,
            detail={
                "error": "library_not_ready",
                "message": arc["message"],
            },
        )

    return {
        "replan_reason": replan_reason,
        "skips_detected": consecutive_skips,
        "original_emotion": current_emotion,
        "personalised": personalised,
        "source_emotion": replan_source,
        "target_emotion": target_emotion,
        "arc_path": arc["arc_path"],
        "segments": [_serialize_segment(s) for s in arc["segments"]],
        "tracks": [_serialize_track(t) for t in arc["tracks"]],
        "total_tracks": arc["total_tracks"],
        "total_duration_ms": arc["total_duration_ms"],
        "duration_minutes": request.remaining_duration_minutes,
        "warnings": _arc_warnings(arc),
        "readiness": arc["readiness"],
    }


@router.post("/adjust")
async def adjust_arc(
    request: AdjustRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Mid-session natural language arc adjustment.

    1. Load session context (ownership check)
    2. Parse NL command via Claude → new target emotion
    3. Exclude seen tracks; re-plan with personalised graph
    """
    session, session_tracks = _load_session(request.session_id, user_id, db)

    current_emotion = _current_emotion(
        session_tracks, request.current_position, session.source_emotion
    )

    adjustment = await parser.parse_adjustment(
        current_emotion=current_emotion,
        current_target=session.target_emotion,
        command=request.command,
    )
    new_target = adjustment["new_target"]
    if new_target == current_emotion:
        new_target = session.target_emotion

    excluded_ids = {
        t.track_id for t in session_tracks if t.position <= request.current_position
    }

    req_planner, personalised = _get_planner(user_id, db)
    arc = req_planner.plan_from_db(
        source=current_emotion,
        target=new_target,
        duration_minutes=request.remaining_duration_minutes,
        db=db,
        user_id=user_id,
        excluded_spotify_ids=excluded_ids,
    )

    if arc.get("error") == "library_not_ready":
        raise HTTPException(
            status_code=202,
            detail={
                "error": "library_not_ready",
                "message": arc["message"],
            },
        )

    return {
        "command": request.command,
        "command_interpretation": adjustment["interpretation"],
        "parse_method": adjustment["method"],
        "personalised": personalised,
        "source_emotion": current_emotion,
        "target_emotion": new_target,
        "arc_path": arc["arc_path"],
        "segments": [_serialize_segment(s) for s in arc["segments"]],
        "tracks": [_serialize_track(t) for t in arc["tracks"]],
        "total_tracks": arc["total_tracks"],
        "total_duration_ms": arc["total_duration_ms"],
        "duration_minutes": request.remaining_duration_minutes,
        "warnings": _arc_warnings(arc),
        "readiness": arc["readiness"],
    }


@router.get("/suggest")
async def suggest_arc(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Context-aware zero-input arc suggestion.
    Uses time of day, day of week, and recent session history.
    """
    return await seeder.suggest(user_id=user_id, db=db)


@router.get("/user-graph")
def get_user_graph(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Diagnostic endpoint — returns the user's personalised emotion graph.

    Shows which edge weights have been adjusted from the global default
    based on skip and completion patterns, and by how much.

    Returns:
        personalised: bool  — whether enough data exists for personalisation
        adjustments:  list  — edges that differ from the global default
        total_signals: int  — total skip + completion observations
    """
    adjustments = learner.explain_adjustments(user_id, db)
    user_graph = learner.load_user_graph(user_id, db)
    personalised = user_graph is not None

    return {
        "personalised": personalised,
        "adjustments": adjustments,
        "global_graph": EMOTION_GRAPH,
    }


@router.post("/preview")
def preview_arc_path(
    request: ArcPreviewRequest,
    user_id: str = Depends(get_current_user_id),  # noqa: ARG001
):
    """Fast path-only preview — no track selection."""
    source = request.source_emotion.lower()
    target = request.target_emotion.lower()

    if source not in VALID_EMOTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid source: {source}")
    if target not in VALID_EMOTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid target: {target}")

    path = planner.find_emotional_path(source, target)

    return {
        "source_emotion": source,
        "target_emotion": target,
        "arc_path": path,
        "step_count": len(path),
        "path_with_energy": [
            {
                "emotion": e,
                "energy_center": ENERGY_CENTERS.get(e, 0.5),
                "neighbors": list(EMOTION_GRAPH.get(e, {}).keys()),
            }
            for e in path
        ],
    }


@router.get("/emotions")
def get_valid_emotions(
    user_id: str = Depends(get_current_user_id),  # noqa: ARG001
):
    """Returns all 12 valid emotion labels with descriptions and energy centers."""
    return {
        "emotions": [
            {
                "label": emotion,
                "description": EMOTION_DESCRIPTIONS[emotion],
                "energy_center": ENERGY_CENTERS.get(emotion, 0.5),
                "neighbors": list(EMOTION_GRAPH.get(emotion, {}).keys()),
            }
            for emotion in VALID_EMOTIONS
        ],
        "total": len(VALID_EMOTIONS),
    }


@router.get("/insights")
def get_listening_insights(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Return longitudinal listening patterns derived from the user's session history.

    Includes completion rate, streak, top starting emotions, most-travelled arc
    pairs, per-time-slot dominant source emotion, and a recent arc timeline.

    Returns empty/zero values when the user has no sessions — never raises.
    """
    return analyzer.get_insights(user_id, db)
