"""
backfill_empty_tracks.py
------------------------
One-time script to fix tracks with empty name/artist by fetching
their metadata from Spotify using the stored user OAuth token.

Run inside the Airflow container:
  docker exec -u airflow flowstate_airflow python3 /opt/airflow/dags/backfill_empty_tracks.py
"""

import os
import httpx
from sqlalchemy import create_engine, text
from datetime import datetime, timezone

DATABASE_URL  = os.environ.get("DATABASE_URL", "postgresql://flowstate:flowstate_dev@db:5432/flowstate")
CLIENT_ID     = os.environ.get("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

engine = create_engine(DATABASE_URL)


def get_valid_user_token() -> str:
    """Load and refresh the user's OAuth token from the DB."""
    with engine.connect() as conn:
        user = conn.execute(text("""
            SELECT access_token, refresh_token, token_expires_at
            FROM users ORDER BY created_at DESC LIMIT 1
        """)).fetchone()

    if not user:
        raise RuntimeError("No users in DB — log in via the frontend first")

    # Check if token is still valid
    now = datetime.now(timezone.utc)
    expires_at = user.token_expires_at
    if expires_at and expires_at.tzinfo is None:
        from datetime import timezone as tz
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at and now < expires_at:
        print(f"  Token valid until {expires_at}")
        return user.access_token

    # Refresh the token
    print("  Token expired — refreshing...")
    resp = httpx.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": user.refresh_token,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )
    resp.raise_for_status()
    data = resp.json()

    new_token   = data["access_token"]
    new_refresh = data.get("refresh_token", user.refresh_token)
    new_expires = datetime.now(timezone.utc).replace(microsecond=0)
    from datetime import timedelta
    new_expires += timedelta(seconds=data.get("expires_in", 3600))

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE users SET
                access_token     = :token,
                refresh_token    = :refresh,
                token_expires_at = :expires
            WHERE refresh_token = :old_refresh
        """), {
            "token":       new_token,
            "refresh":     new_refresh,
            "expires":     new_expires,
            "old_refresh": user.refresh_token,
        })

    print(f"  Token refreshed — valid until {new_expires}")
    return new_token


def fetch_tracks_metadata(token: str, track_ids: list) -> dict:
    resp = httpx.get(
        "https://api.spotify.com/v1/tracks",
        headers={"Authorization": f"Bearer {token}"},
        params={"ids": ",".join(track_ids)},
        timeout=15.0,
    )
    resp.raise_for_status()
    return {t["id"]: t for t in resp.json().get("tracks", []) if t}


def main():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id FROM tracks
            WHERE name = '' OR name IS NULL
               OR artist_names = '' OR artist_names IS NULL
        """)).fetchall()

    if not rows:
        print("No empty tracks — all metadata complete.")
        return

    track_ids = [r.id for r in rows]
    print(f"Found {len(track_ids)} tracks with missing metadata")

    token = get_valid_user_token()

    fixed = 0
    failed = 0
    for i in range(0, len(track_ids), 50):
        batch = track_ids[i:i+50]
        try:
            metadata = fetch_tracks_metadata(token, batch)

            with engine.begin() as conn:
                for tid in batch:
                    track = metadata.get(tid)
                    if not track or not track.get("name"):
                        print(f"  No metadata for {tid} — deleting empty track")
                        # Remove tracks Spotify can't identify — they're unplayable anyway
                        conn.execute(text("DELETE FROM track_features WHERE track_id = :tid"), {"tid": tid})
                        conn.execute(text("DELETE FROM user_tracks WHERE track_id = :tid"), {"tid": tid})
                        conn.execute(text("DELETE FROM tracks WHERE id = :tid"), {"tid": tid})
                        failed += 1
                        continue

                    name    = track.get("name", "")[:500]
                    artists = ", ".join(a["name"] for a in track.get("artists", []))[:500]
                    album   = (track.get("album") or {}).get("name", "")[:500]
                    dur     = track.get("duration_ms")
                    pop     = track.get("popularity")

                    conn.execute(text("""
                        UPDATE tracks SET
                            name         = :name,
                            artist_names = :artists,
                            album_name   = :album,
                            duration_ms  = COALESCE(:dur, duration_ms),
                            popularity   = COALESCE(:pop, popularity)
                        WHERE id = :tid
                    """), {"name": name, "artists": artists, "album": album,
                           "dur": dur, "pop": pop, "tid": tid})
                    print(f"  ✔ {name} — {artists}")
                    fixed += 1

        except Exception as e:
            print(f"  Batch failed: {e}")
            failed += len(batch)

    print(f"\n✅ Backfill complete — fixed: {fixed} | deleted: {failed}")


if __name__ == "__main__":
    main()
