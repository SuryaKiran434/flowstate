from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.security import get_current_user_id
from app.db.session import get_db

router = APIRouter(prefix="/tracks", tags=["tracks"])


@router.get("")
def get_user_tracks(
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uid = user_id
    rows = db.execute(text("""
        SELECT
            t.id, t.name, t.artist_names, t.album_name,
            t.duration_ms, t.popularity,
            tf.tempo_librosa, tf.spectral_centroid,
            tf.zero_crossing_rate, tf.rms_energy,
            tf.mfcc_mean, tf.chroma_mean,
            ut.saved_at
        FROM user_tracks ut
        JOIN tracks t ON ut.track_id = t.id
        LEFT JOIN track_features tf ON t.id = tf.track_id
        WHERE ut.user_id = cast(:uid as uuid)
        ORDER BY ut.saved_at DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """), {"uid": uid, "limit": limit, "offset": offset}).fetchall()
    return {"tracks": [dict(r._mapping) for r in rows], "limit": limit, "offset": offset, "count": len(rows)}


@router.get("/stats")
def get_library_stats(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uid = user_id
    stats = db.execute(text("""
        SELECT
            COUNT(DISTINCT ut.track_id)                   AS total_tracks,
            COUNT(tf.track_id)                            AS tracks_with_features,
            ROUND(AVG(tf.tempo_librosa)::numeric, 1)      AS avg_tempo_bpm,
            ROUND(AVG(tf.spectral_centroid)::numeric, 0)  AS avg_spectral_centroid,
            ROUND(AVG(tf.zero_crossing_rate)::numeric, 4) AS avg_zero_crossing_rate,
            ROUND(AVG(tf.rms_energy)::numeric, 4)         AS avg_rms_energy
        FROM user_tracks ut
        LEFT JOIN track_features tf ON ut.track_id = tf.track_id
        WHERE ut.user_id = cast(:uid as uuid)
    """), {"uid": uid}).fetchone()
    return dict(stats._mapping)
