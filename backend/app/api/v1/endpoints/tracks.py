from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from app.core.security import get_current_user_id
from app.db.session import get_db

router = APIRouter(prefix="/tracks", tags=["tracks"])

VALID_EMOTIONS = {
    "energetic", "happy", "euphoric", "peaceful", "focused",
    "romantic", "nostalgic", "neutral", "melancholic", "sad", "tense", "angry"
}


@router.get("")
def get_user_tracks(
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    rows = db.execute(text("""
        SELECT
            t.id, t.name, t.artist_names, t.album_name,
            t.duration_ms, t.popularity,
            tf.tempo_librosa, tf.spectral_centroid,
            tf.zero_crossing_rate, tf.rms_energy,
            tf.mfcc_mean, tf.chroma_mean,
            tf.energy, tf.valence,
            tf.emotion_label, tf.emotion_confidence,
            ut.saved_at
        FROM user_tracks ut
        JOIN tracks t ON ut.track_id = t.id
        LEFT JOIN track_features tf ON t.id = tf.track_id
        WHERE ut.user_id = cast(:uid as uuid)
        ORDER BY ut.saved_at DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """), {"uid": user_id, "limit": limit, "offset": offset}).fetchall()
    return {
        "tracks": [dict(r._mapping) for r in rows],
        "limit": limit,
        "offset": offset,
        "count": len(rows),
    }


@router.get("/stats")
def get_library_stats(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    stats = db.execute(text("""
        SELECT
            COUNT(DISTINCT ut.track_id)                    AS total_tracks,
            COUNT(tf.track_id)                             AS tracks_with_features,
            COUNT(tf.emotion_label)                        AS tracks_with_emotions,
            ROUND(AVG(tf.tempo_librosa)::numeric, 1)       AS avg_tempo_bpm,
            ROUND(AVG(tf.spectral_centroid)::numeric, 0)   AS avg_spectral_centroid,
            ROUND(AVG(tf.zero_crossing_rate)::numeric, 4)  AS avg_zero_crossing_rate,
            ROUND(AVG(tf.rms_energy)::numeric, 4)          AS avg_rms_energy,
            ROUND(AVG(tf.energy)::numeric, 3)              AS avg_energy,
            ROUND(AVG(tf.valence)::numeric, 3)             AS avg_valence
        FROM user_tracks ut
        LEFT JOIN track_features tf ON ut.track_id = tf.track_id
        WHERE ut.user_id = cast(:uid as uuid)
    """), {"uid": user_id}).fetchone()
    return dict(stats._mapping)


@router.get("/emotions")
def get_emotion_distribution(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Returns the distribution of emotion labels across the user's library.
    Used by the frontend to show the user's emotional profile.
    """
    rows = db.execute(text("""
        SELECT
            tf.emotion_label,
            COUNT(*) AS track_count,
            ROUND(AVG(tf.energy)::numeric, 3)   AS avg_energy,
            ROUND(AVG(tf.valence)::numeric, 3)  AS avg_valence,
            ROUND(AVG(tf.emotion_confidence)::numeric, 3) AS avg_confidence
        FROM user_tracks ut
        JOIN track_features tf ON ut.track_id = tf.track_id
        WHERE ut.user_id = cast(:uid as uuid)
          AND tf.emotion_label IS NOT NULL
        GROUP BY tf.emotion_label
        ORDER BY track_count DESC
    """), {"uid": user_id}).fetchall()

    total = sum(r.track_count for r in rows)
    return {
        "distribution": [
            {
                **dict(r._mapping),
                "percentage": round(r.track_count / total * 100, 1) if total else 0,
            }
            for r in rows
        ],
        "total_classified": total,
    }


@router.get("/by-emotion/{emotion}")
def get_tracks_by_emotion(
    emotion: str,
    limit: int = Query(20, le=100),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    energy_min: float = Query(0.0, ge=0.0, le=1.0),
    energy_max: float = Query(1.0, ge=0.0, le=1.0),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Fetch tracks matching a specific emotion label.
    Used internally by the arc planner to build track pools per segment.

    Supports filtering by:
      - min_confidence: only well-classified tracks (default: all)
      - energy_min/max: slice the energy range (used for smooth arc transitions)
    """
    if emotion not in VALID_EMOTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid emotion '{emotion}'. Valid: {sorted(VALID_EMOTIONS)}"
        )

    rows = db.execute(text("""
        SELECT
            t.id AS spotify_id,
            t.name, t.artist_names, t.album_name,
            t.duration_ms,
            tf.energy, tf.valence,
            tf.emotion_label, tf.emotion_confidence,
            tf.tempo_librosa
        FROM user_tracks ut
        JOIN tracks t ON ut.track_id = t.id
        JOIN track_features tf ON t.id = tf.track_id
        WHERE ut.user_id       = cast(:uid as uuid)
          AND tf.emotion_label = :emotion
          AND tf.emotion_confidence >= :min_confidence
          AND tf.energy BETWEEN :energy_min AND :energy_max
        ORDER BY tf.emotion_confidence DESC, tf.energy ASC
        LIMIT :limit
    """), {
        "uid":            user_id,
        "emotion":        emotion,
        "min_confidence": min_confidence,
        "energy_min":     energy_min,
        "energy_max":     energy_max,
        "limit":          limit,
    }).fetchall()

    return {
        "emotion": emotion,
        "tracks":  [dict(r._mapping) for r in rows],
        "count":   len(rows),
    }


@router.get("/arc-pool")
def get_arc_pool(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Returns ALL classified tracks with full emotion metadata.
    Used by the arc planner to build its TrackCandidate pool in one query
    instead of N queries per emotion segment.
    """
    rows = db.execute(text("""
        SELECT
            tf.track_id AS id,
            t.id        AS spotify_id,
            t.name, t.artist_names,
            t.duration_ms,
            tf.energy, tf.valence,
            tf.emotion_label    AS emotion_label,
            tf.emotion_confidence AS emotion_confidence,
            tf.tempo_librosa
        FROM user_tracks ut
        JOIN tracks t ON ut.track_id = t.id
        JOIN track_features tf ON t.id = tf.track_id
        WHERE ut.user_id = cast(:uid as uuid)
          AND tf.emotion_label IS NOT NULL
        ORDER BY tf.emotion_label, tf.energy
    """), {"uid": user_id}).fetchall()

    return {
        "tracks": [dict(r._mapping) for r in rows],
        "count":  len(rows),
    }
