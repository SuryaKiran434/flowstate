"""
Arc Generation Endpoint — Flowstate
-------------------------------------
POST /api/v1/arc/generate
  Takes a natural language mood description, parses it into source/target
  emotions via Claude API, then generates an emotionally coherent track arc
  using the ArcPlanner graph-based algorithm.

GET /api/v1/arc/emotions
  Returns the 12 valid emotion labels with descriptions and energy/valence
  centers. Used by the frontend to show mood input hints.

GET /api/v1/arc/preview
  Quick arc path preview (no tracks) — used for frontend emotion path display
  before committing to a full arc generation.
"""

import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

from app.core.security import get_current_user_id
from app.db.session import get_db
from app.services.arc_planner import ArcPlanner, EMOTION_GRAPH, ENERGY_CENTERS
from app.services.mood_parser import MoodParser, EMOTION_DESCRIPTIONS, VALID_EMOTIONS

router = APIRouter(prefix="/arc", tags=["arc"])

planner = ArcPlanner()
parser  = MoodParser()


# ─── Request / Response Models ────────────────────────────────────────────────

class ArcRequest(BaseModel):
    mood_text: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Natural language mood description",
        example="I'm stressed from work and want to wind down",
    )
    duration_minutes: int = Field(
        default=30,
        ge=5,
        le=180,
        description="Desired session length in minutes",
    )


class ArcPreviewRequest(BaseModel):
    source_emotion: str = Field(..., description="Starting emotion label")
    target_emotion: str = Field(..., description="Target emotion label")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_arc(
    request: ArcRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Main arc generation endpoint.

    Flow:
      1. Parse mood_text → (source_emotion, target_emotion) via Claude API
      2. Load user's classified track pool from DB
      3. Run ArcPlanner Dijkstra to find emotional path
      4. Select + sequence tracks per segment
      5. Return ordered playlist with full arc metadata
    """

    # Step 1: Parse mood → emotions
    mood = await parser.parse(request.mood_text)
    source = mood["source"]
    target = mood["target"]

    # Step 2 + 3 + 4: Plan arc from DB
    arc = planner.plan_from_db(
        source=source,
        target=target,
        duration_minutes=request.duration_minutes,
        db=db,
        user_id=user_id,
    )

    # Library not ready yet
    if arc.get("error") == "library_not_ready":
        raise HTTPException(status_code=202, detail={
            "error":   "library_not_ready",
            "message": arc["message"],
        })

    # Warn if some emotions in the path had no tracks
    warnings = []
    if arc["readiness"]["has_gaps"]:
        missing = arc["readiness"]["missing_emotions"]
        warnings.append(
            f"No tracks found for: {', '.join(missing)}. "
            "These segments were skipped. Your library may not have enough variety yet."
        )

    # Serialize TrackCandidate dataclasses → dicts for JSON response
    def serialize_track(t) -> dict:
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

    def serialize_segment(seg) -> dict:
        return {
            "emotion":          seg["emotion"],
            "segment_index":    seg["segment_index"],
            "energy_direction": seg["energy_direction"],
            "track_count":      seg["track_count"],
            "tracks":           [serialize_track(t) for t in seg["tracks"]],
        }

    return {
        # Mood parsing results
        "mood_input":         request.mood_text,
        "mood_interpretation": mood["interpretation"],
        "parse_method":       mood["method"],

        # Arc structure
        "source_emotion":     source,
        "target_emotion":     target,
        "arc_path":           arc["arc_path"],
        "segments":           [serialize_segment(s) for s in arc["segments"]],

        # Flat track list for easy playlist rendering
        "tracks":             [serialize_track(t) for t in arc["tracks"]],
        "total_tracks":       arc["total_tracks"],
        "total_duration_ms":  arc["total_duration_ms"],
        "duration_minutes":   request.duration_minutes,

        # Diagnostics
        "warnings":           warnings,
        "readiness":          arc["readiness"],
    }


@router.post("/preview")
def preview_arc_path(
    request: ArcPreviewRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Returns just the emotional path without tracks.
    Fast endpoint — used by frontend to show the arc visualization
    before the user commits to generating the full playlist.
    """
    source = request.source_emotion.lower()
    target = request.target_emotion.lower()

    if source not in VALID_EMOTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid source emotion: {source}")
    if target not in VALID_EMOTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid target emotion: {target}")

    path = planner.find_emotional_path(source, target)

    return {
        "source_emotion": source,
        "target_emotion": target,
        "arc_path":       path,
        "step_count":     len(path),
        "path_with_energy": [
            {
                "emotion":        e,
                "energy_center":  ENERGY_CENTERS.get(e, 0.5),
                "neighbors":      list(EMOTION_GRAPH.get(e, {}).keys()),
            }
            for e in path
        ],
    }


@router.get("/emotions")
def get_valid_emotions(
    user_id: str = Depends(get_current_user_id),
):
    """
    Returns all 12 valid emotion labels with descriptions and energy centers.
    Used by frontend to build mood input hints and emotion selector UI.
    """
    return {
        "emotions": [
            {
                "label":          emotion,
                "description":    EMOTION_DESCRIPTIONS[emotion],
                "energy_center":  ENERGY_CENTERS.get(emotion, 0.5),
                "neighbors":      list(EMOTION_GRAPH.get(emotion, {}).keys()),
            }
            for emotion in VALID_EMOTIONS
        ],
        "total": len(VALID_EMOTIONS),
    }
