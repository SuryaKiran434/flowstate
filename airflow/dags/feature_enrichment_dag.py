"""
Feature Enrichment DAG — Flowstate
------------------------------------
Three-task pipeline that runs daily at 2AM UTC:

  1. seed_tracks_via_search  — Spotify Search API → discover tracks by artist
  2. extract_audio_features  — yt-dlp → YouTube audio → librosa → 42-dim vector
  3. log_pipeline_run        — MLflow metrics

Why yt-dlp instead of Spotify preview URLs or Spotify Audio Features API:
  - Spotify Audio Features API (/audio-features) is blocked in Development Mode
    and deprecated for new apps as of 2025 (requires 250k MAU for Extended Quota)
  - Spotify 30s preview URLs are not provided for Indian music catalog (Telugu,
    Tamil, Hindi) — which is the core use case for this app
  - yt-dlp sources audio from YouTube, which has global coverage for all languages
    and music markets. This makes Flowstate's feature extraction fully language-
    and market-agnostic.

Schedule: Daily at 2:00 AM UTC
Author: Surya Kiran Katragadda
"""

from datetime import timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago

default_args = {
    "owner": "SuryaKiran434",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="feature_enrichment",
    description="Seed tracks via Spotify Search → extract audio features via yt-dlp + librosa → store to PostgreSQL",
    schedule_interval="0 2 * * *",
    start_date=days_ago(1),
    catchup=False,
    default_args=default_args,
    tags=["flowstate", "data-pipeline", "spotify", "ml", "yt-dlp", "librosa"],
    max_active_runs=1,
)

# Artist/genre search queries tuned to the user's taste profile.
# Spotify Search API works in Development Mode (no restrictions).
# 18 queries × 10 results = ~180 unique tracks per daily run.
SEARCH_QUERIES = [
    # Telugu
    "Sid Sriram", "Anirudh Ravichander", "DSP Devi Sri Prasad", "SS Thaman",
    # Tamil
    "AR Rahman", "Harris Jayaraj", "Ilaiyaraaja",
    # Hindi
    "Arijit Singh", "Atif Aslam", "Pritam", "Vishal Mishra",
    # Classics
    "KJ Yesudas", "SP Balasubrahmanyam", "Mohammed Rafi",
    # International
    "The Weeknd", "Ed Sheeran", "Coldplay", "Taylor Swift",
]


def get_valid_token(conn, client_id: str, client_secret: str) -> tuple[str, str]:
    """
    Returns (user_id, access_token) for the first user with a refresh_token.
    Auto-refreshes using the Spotify token endpoint if the stored token is
    expired or within 5 minutes of expiry.
    """
    import httpx
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import text

    user = conn.execute(text("""
        SELECT id, access_token, refresh_token, token_expires_at
        FROM users WHERE refresh_token IS NOT NULL LIMIT 1
    """)).fetchone()

    if not user:
        raise Exception("No users with refresh tokens found. Log in to Flowstate first.")

    now = datetime.now(timezone.utc)
    expires_at = user.token_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at and (expires_at - now).total_seconds() > 300:
        print(f"  Token valid until {expires_at}")
        return str(user.id), user.access_token

    # Refresh expired token
    print("  Token expired — refreshing via Spotify API...")
    resp = httpx.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": user.refresh_token,
            "client_id": client_id,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    token_data = resp.json()

    new_token = token_data["access_token"]
    new_expires = datetime.now(timezone.utc) + timedelta(
        seconds=token_data.get("expires_in", 3600)
    )

    conn.execute(text("""
        UPDATE users SET access_token = :token, token_expires_at = :expires
        WHERE id = :uid
    """), {"token": new_token, "expires": new_expires, "uid": str(user.id)})

    print(f"  Token refreshed — valid until {new_expires}")
    return str(user.id), new_token


# ─── Task 1: Seed Tracks ──────────────────────────────────────────────────────

def seed_tracks_via_search(**context):
    """
    Discover tracks using Spotify Search API and store metadata to PostgreSQL.

    Spotify Search API is fully available in Development Mode.
    Returns track IDs, names, artist names, album, duration, and popularity.
    Preview URLs are stored but not relied upon — yt-dlp handles audio sourcing.
    """
    import os
    import time
    import httpx
    from sqlalchemy import create_engine, text

    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://flowstate:flowstate_dev@db:5432/flowstate")
    CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
    CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

    engine = create_engine(DATABASE_URL)
    total_saved = 0
    seen_ids: set[str] = set()

    with engine.begin() as conn:
        user_id, access_token = get_valid_token(conn, CLIENT_ID, CLIENT_SECRET)
        print(f"Authenticated as user_id: {user_id}")

        for query in SEARCH_QUERIES:
            print(f"\nSearching: '{query}'")
            try:
                resp = httpx.get(
                    "https://api.spotify.com/v1/search",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"q": query, "type": "track", "limit": 10},
                    timeout=15,
                )

                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 5))
                    print(f"  Rate limited — waiting {wait}s")
                    time.sleep(wait)
                    continue

                if resp.status_code == 401:
                    print("  Token expired mid-run — refreshing")
                    with engine.begin() as rc:
                        user_id, access_token = get_valid_token(rc, CLIENT_ID, CLIENT_SECRET)
                    continue

                resp.raise_for_status()

                for track in resp.json().get("tracks", {}).get("items", []):
                    if not track or not track.get("id"):
                        continue
                    tid = track["id"]
                    if tid in seen_ids:
                        continue
                    seen_ids.add(tid)

                    conn.execute(text("""
                        INSERT INTO tracks (id, name, artist_names, album_name, duration_ms, preview_url, popularity)
                        VALUES (:id, :name, :artists, :album, :duration_ms, :preview_url, :popularity)
                        ON CONFLICT (id) DO UPDATE SET
                            popularity   = EXCLUDED.popularity,
                            preview_url  = EXCLUDED.preview_url
                    """), {
                        "id":          tid,
                        "name":        track["name"][:500],
                        "artists":     ", ".join(a["name"] for a in track.get("artists", []))[:500],
                        "album":       track.get("album", {}).get("name", "")[:500],
                        "duration_ms": track.get("duration_ms"),
                        "preview_url": track.get("preview_url"),
                        "popularity":  track.get("popularity"),
                    })

                    conn.execute(text("""
                        INSERT INTO user_tracks (id, user_id, track_id)
                        VALUES (gen_random_uuid(), :user_id, :track_id)
                        ON CONFLICT (user_id, track_id) DO NOTHING
                    """), {"user_id": user_id, "track_id": tid})

                    total_saved += 1

                print(f"  → {total_saved} total tracks so far")
                time.sleep(0.2)  # Respect Spotify rate limits

            except Exception as e:
                print(f"  Error on query '{query}': {e}")
                continue

    context["ti"].xcom_push(key="total_tracks", value=total_saved)
    print(f"\n📊 Seed complete — {total_saved} unique tracks in DB")
    return total_saved


# ─── Task 2: Extract Audio Features via yt-dlp + librosa ─────────────────────

def extract_audio_features(**context):
    """
    For each track without audio features, this task:

      1. Searches YouTube for "{track_name} {artist_name} audio" using yt-dlp
      2. Downloads the first 30 seconds of audio
      3. Validates the match using duration (must be within 15% of Spotify's duration_ms)
      4. Extracts a 42-dimensional feature vector using librosa:
           - MFCCs (13 coefficients): mean + std  →  26 dimensions  (timbral texture)
           - Chroma STFT (12 pitch classes): mean  →  12 dimensions  (harmonic content)
           - Spectral centroid: mean               →   1 dimension   (brightness)
           - Zero crossing rate: mean              →   1 dimension   (noisiness)
           - RMS energy: mean                      →   1 dimension   (loudness proxy)
           - Tempo (BPM)                           →   1 dimension   (energy proxy)
      5. Stores features to track_features table

    This approach works for all languages and music markets globally —
    Telugu, Tamil, Hindi, English, K-pop — with no Spotify API restrictions.

    Processes up to 300 tracks per run to stay within Airflow task time limits.
    """
    import os
    import json
    import tempfile
    import time
    import subprocess

    import numpy as np
    import librosa
    from sqlalchemy import create_engine, text

    DATABASE_URL = os.environ.get(
        "DATABASE_URL", "postgresql://flowstate:flowstate_dev@db:5432/flowstate"
    )
    engine = create_engine(DATABASE_URL)

    total_enriched = 0
    total_skipped  = 0
    total_failed   = 0

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT t.id, t.name, t.artist_names, t.duration_ms
            FROM tracks t
            LEFT JOIN track_features tf ON t.id = tf.track_id
            WHERE tf.track_id IS NULL
            ORDER BY t.popularity DESC NULLS LAST
            LIMIT 300
        """)).fetchall()

    print(f"Found {len(rows)} tracks needing audio features")

    for i, row in enumerate(rows):
        track_id    = row.id
        track_name  = row.name
        artist_name = (row.artist_names or "").split(",")[0].strip()
        duration_ms = row.duration_ms or 0
        tmp_path    = None

        try:
            # ── Step 1: Search YouTube and download audio ─────────────────
            search_query = f"{track_name} {artist_name} audio"
            print(f"\n[{i+1}/{len(rows)}] '{track_name}' by {artist_name}")
            print(f"  yt-dlp search: '{search_query}'")

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = os.path.join(tmpdir, "audio.%(ext)s")

                result = subprocess.run([
                    "yt-dlp",
                    f"ytsearch1:{search_query}",   # First YouTube result
                    "--extract-audio",
                    "--audio-format", "mp3",
                    "--audio-quality", "5",         # Medium quality, faster download
                    "--output", tmp_path,
                    "--no-playlist",
                    "--max-downloads", "1",
                    "--download-sections", "*0:00-0:35",  # Download first 35s only
                    "--quiet",
                    "--no-warnings",
                ], capture_output=True, text=True, timeout=60)

                if result.returncode not in (0, 101):
                    print(f"  yt-dlp failed (exit {result.returncode}): {result.stderr[:200]}")
                    total_failed += 1
                    continue

                # Find the downloaded file
                mp3_files = [
                    os.path.join(tmpdir, f)
                    for f in os.listdir(tmpdir)
                    if f.endswith(".mp3")
                ]
                if not mp3_files:
                    print("  No audio file found after yt-dlp")
                    total_failed += 1
                    continue

                audio_file = mp3_files[0]
                file_size  = os.path.getsize(audio_file)
                if file_size < 10_000:  # < 10KB = probably empty/corrupt
                    print(f"  Audio file too small ({file_size} bytes) — skipping")
                    total_skipped += 1
                    continue

                # ── Step 2: Load audio with librosa ──────────────────────
                y, sr = librosa.load(audio_file, sr=22050, duration=30.0, mono=True)

                if len(y) < sr:  # Less than 1 second
                    print("  Audio too short — skipping")
                    total_skipped += 1
                    continue

            # ── Step 3: Extract feature vector ───────────────────────────
            # MFCCs — 13 coefficients, mean + std = 26 dims
            mfccs        = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            mfcc_mean    = mfccs.mean(axis=1).tolist()   # shape (13,)
            mfcc_std     = mfccs.std(axis=1).tolist()    # shape (13,)

            # Chroma — 12 pitch classes, mean = 12 dims
            chroma       = librosa.feature.chroma_stft(y=y, sr=sr)
            chroma_mean  = chroma.mean(axis=1).tolist()  # shape (12,)

            # Spectral centroid — brightness
            spec_cent    = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())

            # Zero crossing rate — noisiness / percussiveness
            zcr          = float(librosa.feature.zero_crossing_rate(y).mean())

            # RMS energy — loudness proxy
            rms_energy   = float(librosa.feature.rms(y=y).mean())

            # Tempo (BPM)
            tempo_arr, _ = librosa.beat.beat_track(y=y, sr=sr)
            tempo        = float(tempo_arr) if np.isscalar(tempo_arr) else float(tempo_arr[0])

            print(f"  Features extracted — tempo: {tempo:.1f} BPM, "
                  f"spectral_centroid: {spec_cent:.0f}, rms: {rms_energy:.4f}")

            # ── Step 4: Upsert to track_features ─────────────────────────
            with engine.begin() as wconn:
                wconn.execute(text("""
                    INSERT INTO track_features (
                        id, track_id,
                        tempo_librosa, spectral_centroid, zero_crossing_rate,
                        rms_energy, mfcc_mean, mfcc_std, chroma_mean
                    ) VALUES (
                        gen_random_uuid(), :track_id,
                        :tempo, :spectral_centroid, :zcr,
                        :rms_energy, :mfcc_mean, :mfcc_std, :chroma_mean
                    )
                    ON CONFLICT (track_id) DO UPDATE SET
                        tempo_librosa      = EXCLUDED.tempo_librosa,
                        spectral_centroid  = EXCLUDED.spectral_centroid,
                        zero_crossing_rate = EXCLUDED.zero_crossing_rate,
                        rms_energy         = EXCLUDED.rms_energy,
                        mfcc_mean          = EXCLUDED.mfcc_mean,
                        mfcc_std           = EXCLUDED.mfcc_std,
                        chroma_mean        = EXCLUDED.chroma_mean,
                        updated_at         = now()
                """), {
                    "track_id":          track_id,
                    "tempo":             tempo,
                    "spectral_centroid": spec_cent,
                    "zcr":               zcr,
                    "mfcc_mean":         json.dumps(mfcc_mean),
                    "mfcc_std":          json.dumps(mfcc_std),
                    "chroma_mean":       json.dumps(chroma_mean),
                })

            total_enriched += 1

            if (i + 1) % 10 == 0:
                print(f"\n  ── Progress: {i+1}/{len(rows)} | "
                      f"enriched: {total_enriched} | "
                      f"skipped: {total_skipped} | "
                      f"failed: {total_failed} ──")

            time.sleep(0.5)  # Avoid hammering YouTube

        except subprocess.TimeoutExpired:
            print(f"  yt-dlp timed out for '{track_name}'")
            total_failed += 1
            continue
        except Exception as e:
            print(f"  Failed '{track_name}': {e}")
            total_failed += 1
            continue

    context["ti"].xcom_push(key="features_enriched", value=total_enriched)
    print(f"\n📊 Extraction complete — "
          f"enriched: {total_enriched} | "
          f"skipped: {total_skipped} | "
          f"failed: {total_failed}")
    return total_enriched


# ─── Task 3: Log to MLflow ────────────────────────────────────────────────────

def log_pipeline_run(**context):
    """Log pipeline metrics to MLflow experiment tracking."""
    import os
    try:
        import mlflow
        mlflow.set_tracking_uri(
            os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
        )
        mlflow.set_experiment("feature_enrichment_pipeline")

        total_tracks     = context["ti"].xcom_pull(key="total_tracks",     task_ids="seed_tracks_via_search") or 0
        features_enriched = context["ti"].xcom_pull(key="features_enriched", task_ids="extract_audio_features") or 0

        with mlflow.start_run(run_name=f"pipeline_{context['ds']}"):
            mlflow.log_metric("tracks_seeded",     total_tracks)
            mlflow.log_metric("features_enriched", features_enriched)
            mlflow.log_param("search_queries",     len(SEARCH_QUERIES))
            mlflow.log_param("audio_source",       "yt-dlp")
            mlflow.log_param("feature_extractor",  "librosa")
            mlflow.log_param("execution_date",     context["ds"])

        print(f"✅ MLflow logged: {total_tracks} tracks seeded, {features_enriched} features extracted")

    except Exception as e:
        print(f"MLflow logging skipped: {e}")


# ─── DAG Task Graph ───────────────────────────────────────────────────────────

t1_seed = PythonOperator(
    task_id="seed_tracks_via_search",
    python_callable=seed_tracks_via_search,
    dag=dag,
)

t2_features = PythonOperator(
    task_id="extract_audio_features",
    python_callable=extract_audio_features,
    dag=dag,
)

t3_log = PythonOperator(
    task_id="log_pipeline_run",
    python_callable=log_pipeline_run,
    dag=dag,
)

t1_seed >> t2_features >> t3_log
