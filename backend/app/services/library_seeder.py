"""
Library Seeder — Flowstate
--------------------------
Seeds a user's Spotify library (track metadata only — no audio extraction)
into the PostgreSQL database on first login.

This runs as a FastAPI BackgroundTask after the OAuth callback so the user
reaches the dashboard immediately. Audio features are later populated by the
nightly Airflow DAG (yt-dlp + librosa pipeline).

Reuses the same ON CONFLICT upsert pattern as the Airflow DAG for consistency.
"""

from sqlalchemy import text

from app.services.spotify_client import (
    get_playlist_tracks,
    get_top_tracks,
    get_user_playlists,
)


async def seed_user_library(user_id: str, access_token: str, db) -> int:
    """
    Fetch a user's Spotify library and upsert track metadata into the DB.

    Sources:
      - All playlists the user owns/follows → their tracks
      - Top tracks across short_term, medium_term, long_term time ranges

    Returns:
        Number of new tracks inserted (duplicates across sources counted once).
    """
    seen_ids: set[str] = set()
    total_saved = 0

    def _save_track(track: dict) -> bool:
        """Upsert one track + user_tracks link. Returns True if newly inserted."""
        nonlocal total_saved

        if not track or not track.get("id"):
            return False
        tid = track["id"]
        if tid in seen_ids:
            return False
        seen_ids.add(tid)

        artists = ", ".join(
            a["name"] for a in track.get("artists", []) if isinstance(a, dict)
        )[:500]
        album_obj = track.get("album")
        album = (album_obj.get("name", "") if isinstance(album_obj, dict) else "")[:500]

        db.execute(
            text("""
            INSERT INTO tracks (id, name, artist_names, album_name, duration_ms, preview_url, popularity)
            VALUES (:id, :name, :artists, :album, :duration_ms, :preview_url, :popularity)
            ON CONFLICT (id) DO UPDATE SET
                popularity  = EXCLUDED.popularity,
                preview_url = EXCLUDED.preview_url
        """),
            {
                "id": tid,
                "name": str(track.get("name", ""))[:500],
                "artists": artists,
                "album": album,
                "duration_ms": track.get("duration_ms"),
                "preview_url": track.get("preview_url"),
                "popularity": track.get("popularity"),
            },
        )

        db.execute(
            text("""
            INSERT INTO user_tracks (id, user_id, track_id)
            VALUES (gen_random_uuid(), cast(:user_id as uuid), :track_id)
            ON CONFLICT (user_id, track_id) DO NOTHING
        """),
            {"user_id": user_id, "track_id": tid},
        )

        total_saved += 1
        return True

    # ── Source 1: User's playlists ────────────────────────────────────────────
    try:
        playlists = await get_user_playlists(access_token)
        for pl in playlists:
            if not pl.get("id"):
                continue
            try:
                tracks = await get_playlist_tracks(access_token, pl["id"])
                for t in tracks:
                    _save_track(t)
            except Exception:
                pass  # skip inaccessible playlists
    except Exception:
        pass  # graceful degradation if Spotify API fails

    # ── Source 2: Top tracks (3 time ranges) ─────────────────────────────────
    for time_range in ("short_term", "medium_term", "long_term"):
        try:
            tracks = await get_top_tracks(access_token, time_range=time_range)
            for t in tracks:
                _save_track(t)
        except Exception:
            pass

    db.commit()
    return total_saved


async def seed_user_library_background(user_id: str, access_token: str) -> None:
    """
    Background-task wrapper — creates its own DB session so it is safe to
    run after the HTTP response has been sent (FastAPI BackgroundTasks).
    """
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        count = await seed_user_library(user_id, access_token, db)
        print(f"[seeder] Seeded {count} tracks for user {user_id}")
    except Exception as exc:
        print(f"[seeder] Background seed failed for user {user_id}: {exc}")
    finally:
        db.close()
