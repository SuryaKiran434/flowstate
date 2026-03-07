"""
Feature Enrichment DAG — Flowstate
------------------------------------
Three-task pipeline that runs daily at 2AM UTC:

  1. seed_tracks_from_library  — Pull tracks from user's REAL Spotify library:
                                  • All playlists + their tracks
                                  • Liked/saved tracks
                                  • Top tracks (short + medium term)
                                  • Top artists → their top tracks

  2. extract_audio_features    — yt-dlp → YouTube audio → librosa → 42-dim vector

  3. log_pipeline_run          — MLflow metrics

Why personal library instead of search queries:
  The previous approach used hardcoded artist search queries (Sid Sriram,
  AR Rahman, etc.) which gave generic results not tied to the user's actual
  taste. The new approach uses the user's real Spotify data — playlists,
  liked songs, and top tracks — making the catalog 100% personal.

  APIs used (all available in Spotify Development Mode):
    GET /me/playlists                     — user's playlists
    GET /playlists/{id}/items             — tracks in each playlist
    GET /me/tracks                        — liked/saved tracks
    GET /me/top/tracks                    — top tracks (short + medium term)
    GET /me/top/artists → /top-tracks     — top artists' tracks

Schedule: Daily at 2:00 AM UTC
Author: Surya Kiran Katragadda
"""

import asyncio
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
    description="Seed tracks from personal Spotify library → extract audio features via yt-dlp + librosa",
    schedule_interval="0 2 * * *",
    start_date=days_ago(1),
    catchup=False,
    default_args=default_args,
    tags=["flowstate", "data-pipeline", "spotify", "ml", "yt-dlp", "librosa"],
    max_active_runs=1,
)


def get_valid_token(conn, client_id: str) -> tuple[str, str]:
    """
    Returns (user_id, access_token) for the first user with a refresh_token.
    Auto-refreshes using the Spotify token endpoint if expired or expiring soon.
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


def upsert_track(conn, track: dict, user_id: str, source: str):
    """Insert/update a track and link it to the user. Returns track_id or None."""
    from sqlalchemy import text

    if not track or not track.get("id"):
        return None

    tid = track["id"]
    artists = ", ".join(a["name"] for a in track.get("artists", []))[:500]
    album = track.get("album", {}).get("name", "") if isinstance(track.get("album"), dict) else ""

    conn.execute(text("""
        INSERT INTO tracks (id, name, artist_names, album_name, duration_ms, preview_url, popularity)
        VALUES (:id, :name, :artists, :album, :duration_ms, :preview_url, :popularity)
        ON CONFLICT (id) DO UPDATE SET
            popularity   = EXCLUDED.popularity,
            preview_url  = EXCLUDED.preview_url,
            name         = CASE WHEN tracks.name = '' OR tracks.name IS NULL
                                THEN EXCLUDED.name ELSE tracks.name END,
            artist_names = CASE WHEN tracks.artist_names = '' OR tracks.artist_names IS NULL
                                THEN EXCLUDED.artist_names ELSE tracks.artist_names END,
            album_name   = CASE WHEN tracks.album_name = '' OR tracks.album_name IS NULL
                                THEN EXCLUDED.album_name ELSE tracks.album_name END,
            duration_ms  = CASE WHEN tracks.duration_ms IS NULL
                                THEN EXCLUDED.duration_ms ELSE tracks.duration_ms END
    """), {
        "id":          tid,
        "name":        track["name"][:500],
        "artists":     artists,
        "album":       album[:500],
        "duration_ms": track.get("duration_ms"),
        "preview_url": track.get("preview_url"),
        "popularity":  track.get("popularity"),
    })

    conn.execute(text("""
        INSERT INTO user_tracks (id, user_id, track_id)
        VALUES (gen_random_uuid(), :user_id, :track_id)
        ON CONFLICT (user_id, track_id) DO NOTHING
    """), {"user_id": user_id, "track_id": tid})

    return tid


# ─── Task 1: Seed Tracks from Personal Library ───────────────────────────────

def seed_tracks_from_library(**context):
    """
    Pull tracks from the authenticated user's real Spotify library:

    Source 1 — Playlists:  GET /me/playlists → GET /playlists/{id}/items
    Source 2 — Top tracks: GET /me/top/tracks (short_term + long_term)

    Notes:
    - GET /me/tracks (liked songs) skipped — user adds to playlists instead
    - GET /artists/{id}/top-tracks blocked 403 in Dev Mode since Feb 2026
    - market=IN used for Indian Spotify catalog
    """
    import os
    import time
    import httpx
    from sqlalchemy import create_engine, text

    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://flowstate:flowstate_dev@db:5432/flowstate")
    CLIENT_ID    = os.environ.get("SPOTIFY_CLIENT_ID", "")
    API_BASE     = "https://api.spotify.com/v1"

    engine = create_engine(DATABASE_URL)
    seen_ids: set[str] = set()
    total_saved = 0

    def auth_headers():
        return {"Authorization": f"Bearer {token}"}

    def safe_get(url, params=None, retries=3):
        """GET with rate limit + 5xx retry handling."""
        for attempt in range(retries):
            try:
                resp = client.get(url, headers=auth_headers(), params=params, timeout=15)
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 5))
                    print(f"  Rate limited — waiting {wait}s")
                    time.sleep(wait)
                    continue
                if resp.status_code in (401, 403):
                    print(f"  HTTP {resp.status_code} on {url} — skipping")
                    return None
                if resp.status_code >= 500:
                    wait = 2 ** attempt
                    print(f"  HTTP {resp.status_code} — retrying in {wait}s ({attempt+1}/{retries})")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                print(f"  Request error: {e} — retrying ({attempt+1}/{retries})")
                time.sleep(2 ** attempt)
        print(f"  Giving up on {url}")
        return None

    def save_track(track):
        """Upsert track + user_track link. Returns True if new track."""
        nonlocal total_saved
        if not track or not track.get("id"):
            return False
        tid = track["id"]
        if tid in seen_ids:
            return False
        seen_ids.add(tid)
        artists = ", ".join(a["name"] for a in track.get("artists", []))[:500]
        album = track.get("album", {}).get("name", "") if isinstance(track.get("album"), dict) else ""
        with engine.begin() as wconn:
            wconn.execute(text("""
                INSERT INTO tracks (id, name, artist_names, album_name, duration_ms, preview_url, popularity)
                VALUES (:id, :name, :artists, :album, :duration_ms, :preview_url, :popularity)
                ON CONFLICT (id) DO UPDATE SET
                    popularity  = EXCLUDED.popularity,
                    preview_url = EXCLUDED.preview_url
            """), {
                "id":          tid,
                "name":        track["name"][:500],
                "artists":     artists,
                "album":       album[:500],
                "duration_ms": track.get("duration_ms"),
                "preview_url": track.get("preview_url"),
                "popularity":  track.get("popularity"),
            })
            wconn.execute(text("""
                INSERT INTO user_tracks (id, user_id, track_id)
                VALUES (gen_random_uuid(), :user_id, :track_id)
                ON CONFLICT (user_id, track_id) DO NOTHING
            """), {"user_id": user_id, "track_id": tid})
        total_saved += 1
        return True

    # Get token
    with engine.begin() as conn:
        user_id, token = get_valid_token(conn, CLIENT_ID)
        print(f"Authenticated as user_id: {user_id}")

    with httpx.Client() as client:

        # ── Source 1: All Playlists ───────────────────────────────────────
        print("\n── Source 1: Fetching your playlists...")
        data = safe_get(f"{API_BASE}/me/playlists", {"limit": 50})
        playlists = []
        while data:
            playlists.extend([p for p in data.get("items", []) if p])
            next_url = data.get("next")
            data = safe_get(next_url) if next_url else None

        print(f"  Found {len(playlists)} playlists")

        for pl in playlists:
            pl_name = pl.get("name", "Unknown")
            pl_id   = pl.get("id")
            if not pl_id:
                continue

            print(f"  → '{pl_name}'")
            pl_before = total_saved
            track_url = f"{API_BASE}/playlists/{pl_id}/items"
            track_params = {"limit": 50}

            while track_url:
                tdata = safe_get(track_url, track_params)
                if not tdata:
                    break
                for item in tdata.get("items", []):
                    track = item.get("item") or item.get("track") if item else None
                    save_track(track)
                track_url    = tdata.get("next")
                track_params = {}
                time.sleep(0.1)

            print(f"    +{total_saved - pl_before} tracks")

        print(f"  Playlists done — {total_saved} tracks so far")

        # ── Source 2: Top Tracks ──────────────────────────────────────────
        print("\n── Source 2: Fetching your top tracks...")
        for time_range in ["short_term", "medium_term", "long_term"]:
            before = total_saved
            data = safe_get(f"{API_BASE}/me/top/tracks", {"limit": 50, "time_range": time_range})
            if not data:
                print(f"  {time_range}: skipped (API error)")
                continue
            for track in data.get("items", []):
                save_track(track)
            print(f"  {time_range}: +{total_saved - before} new tracks")

        print(f"  Top tracks done — {total_saved} tracks so far")

    context["ti"].xcom_push(key="total_tracks", value=total_saved)
    print(f"\n📊 Library seed complete — {total_saved} unique tracks from your personal library")
    return total_saved


# ─── Task 2: Extract Audio Features via yt-dlp + librosa ─────────────────────

def extract_audio_features(**context):
    """
    For each track without audio features:
      1. Search YouTube via yt-dlp: "{track_name} {artist} audio"
      2. Download first 35s of audio
      3. Extract 42-dimensional librosa feature vector:
           MFCCs (13 mean + 13 std), Chroma (12), Spectral centroid,
           Zero crossing rate, RMS energy, Tempo (BPM)
      4. Upsert to track_features table

    Uses a ThreadPoolExecutor with 4 workers for ~4x speedup over sequential.
    Each worker has its own tmpdir and DB connection — no shared mutable state.
    Failed tracks are logged and skipped; they'll be retried on the next DAG run
    via the WHERE tf.track_id IS NULL query.
    """
    import os
    import json
    import tempfile
    import subprocess
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import numpy as np
    import librosa
    from sqlalchemy import create_engine, text

    NUM_WORKERS  = 4
    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://flowstate:flowstate_dev@db:5432/flowstate")

    # pool_size matches NUM_WORKERS so each thread gets its own connection
    engine = create_engine(DATABASE_URL, pool_size=NUM_WORKERS + 2, max_overflow=0)

    # Thread-safe counters
    lock           = threading.Lock()
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

    total_rows = len(rows)
    print(f"Found {total_rows} tracks needing audio features — processing with {NUM_WORKERS} workers")

    def process_track(args):
        idx, row = args
        track_id    = row.id
        track_name  = row.name
        artist_name = (row.artist_names or "").split(",")[0].strip()
        search_query = f"{track_name} {artist_name} audio"

        print(f"\n[{idx+1}/{total_rows}] '{track_name}' by {artist_name}")
        print(f"  yt-dlp search: '{search_query}'")

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run([
                    "yt-dlp",
                    f"ytsearch1:{search_query}",
                    "--extract-audio",
                    "--audio-format", "mp3",
                    "--audio-quality", "5",
                    "--output", os.path.join(tmpdir, "audio.%(ext)s"),
                    "--no-playlist",
                    "--max-downloads", "1",
                    "--download-sections", "*0:00-0:35",
                    "--quiet",
                    "--no-warnings",
                ], capture_output=True, text=True, timeout=60)

                if result.returncode not in (0, 101):
                    print(f"  yt-dlp failed (exit {result.returncode})")
                    return "failed"

                mp3_files = [
                    os.path.join(tmpdir, f)
                    for f in os.listdir(tmpdir)
                    if f.endswith(".mp3")
                ]
                if not mp3_files or os.path.getsize(mp3_files[0]) < 10_000:
                    print("  No valid audio file — skipping")
                    return "skipped"

                y, sr = librosa.load(mp3_files[0], sr=22050, duration=30.0, mono=True)

            if len(y) < sr:
                return "skipped"

            # Feature extraction
            mfccs        = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            mfcc_mean    = mfccs.mean(axis=1).tolist()
            mfcc_std     = mfccs.std(axis=1).tolist()
            chroma       = librosa.feature.chroma_stft(y=y, sr=sr)
            chroma_mean  = chroma.mean(axis=1).tolist()
            spec_cent    = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())
            zcr          = float(librosa.feature.zero_crossing_rate(y).mean())
            rms_energy   = float(librosa.feature.rms(y=y).mean())
            tempo_arr, _ = librosa.beat.beat_track(y=y, sr=sr)
            tempo        = float(tempo_arr) if np.isscalar(tempo_arr) else float(tempo_arr[0])

            print(f"  Features extracted — tempo: {tempo:.1f} BPM, spectral_centroid: {spec_cent:.0f}, rms: {rms_energy:.4f}")

            # Each thread gets its own connection from the pool
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
                    "rms_energy":        rms_energy,
                    "mfcc_mean":         json.dumps(mfcc_mean),
                    "mfcc_std":          json.dumps(mfcc_std),
                    "chroma_mean":       json.dumps(chroma_mean),
                })

            return "enriched"

        except subprocess.TimeoutExpired:
            print(f"  yt-dlp timed out for '{track_name}'")
            return "failed"
        except Exception as e:
            print(f"  Failed '{track_name}': {e}")
            return "failed"

    # Run with thread pool — each worker independently downloads + extracts + writes
    completed = 0
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = {executor.submit(process_track, (i, row)): i for i, row in enumerate(rows)}
        for future in as_completed(futures):
            result = future.result()
            completed += 1
            with lock:
                if result == "enriched":
                    total_enriched += 1
                elif result == "skipped":
                    total_skipped += 1
                else:
                    total_failed += 1
            if completed % 20 == 0:
                print(f"\n  ── Progress: {completed}/{total_rows} | enriched: {total_enriched} | skipped: {total_skipped} | failed: {total_failed} ──")

    context["ti"].xcom_push(key="features_enriched", value=total_enriched)
    print(f"\n📊 Extraction complete — enriched: {total_enriched} | skipped: {total_skipped} | failed: {total_failed}")
    return total_enriched


# ─── Task 3: Log to MLflow ────────────────────────────────────────────────────

def log_pipeline_run(**context):
    """Log pipeline metrics to MLflow."""
    import os
    try:
        import mlflow
        mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
        mlflow.set_experiment("feature_enrichment_pipeline")

        total_tracks        = context["ti"].xcom_pull(key="total_tracks",         task_ids="seed_tracks_from_library") or 0
        features_enriched   = context["ti"].xcom_pull(key="features_enriched",   task_ids="extract_audio_features") or 0
        emotions_classified = context["ti"].xcom_pull(key="emotions_classified",  task_ids="classify_emotions") or 0
        emotion_dist        = context["ti"].xcom_pull(key="emotion_distribution",  task_ids="classify_emotions") or {}

        with mlflow.start_run(run_name=f"pipeline_{context['ds']}"):
            mlflow.log_metric("tracks_seeded",      total_tracks)
            mlflow.log_metric("features_enriched",  features_enriched)
            mlflow.log_metric("emotions_classified", emotions_classified)
            mlflow.log_param("seed_source",         "personal_library")
            mlflow.log_param("audio_source",        "yt-dlp")
            mlflow.log_param("feature_extractor",   "librosa")
            mlflow.log_param("emotion_classifier",  "percentile_rule_based")
            mlflow.log_param("execution_date",      context["ds"])
            for label, count in emotion_dist.items():
                mlflow.log_metric(f"emotion_{label}", count)

        print(f"✅ MLflow logged: {total_tracks} seeded, {features_enriched} features, {emotions_classified} emotions")
    except Exception as e:
        print(f"MLflow logging skipped: {e}")


# ─── Task 4: Classify Emotions ───────────────────────────────────────────────

def classify_emotions(**context):
    """
    Maps each track's 42-dim librosa feature vector to 4 emotion fields:
      - energy      (0.0–1.0)  derived from rms_energy + tempo
      - valence     (0.0–1.0)  derived from spectral_centroid + chroma variance
      - emotion_label          one of 12 labels matching the arc planner graph
      - emotion_confidence     0.0–1.0, how strongly the track fits its label

    Uses percentile-based normalization within the user's own library so that
    emotion labels are always well-distributed regardless of library genre mix.
    A library of all calm Telugu melodies will still have "energetic" tracks —
    they're just the most energetic relative to that library.

    Idempotent: only processes tracks where emotion_label IS NULL.
    Re-runs safely after new tracks are added.
    """
    import os
    import json
    import numpy as np
    from sqlalchemy import create_engine, text

    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://flowstate:flowstate_dev@db:5432/flowstate")
    engine = create_engine(DATABASE_URL)

    # ── Step 1: Load all tracks that have features but no emotion label ───────
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                tf.track_id,
                tf.rms_energy,
                tf.tempo_librosa,
                tf.spectral_centroid,
                tf.zero_crossing_rate,
                tf.chroma_mean,
                tf.mfcc_mean
            FROM track_features tf
            WHERE tf.rms_energy IS NOT NULL
              AND tf.emotion_label IS NULL
        """)).fetchall()

    if not rows:
        print("No tracks needing emotion classification — all up to date.")
        return 0

    print(f"Classifying emotions for {len(rows)} tracks...")

    # ── Step 2: Build raw feature arrays ─────────────────────────────────────
    track_ids        = [r.track_id for r in rows]
    rms_values       = np.array([r.rms_energy or 0.0    for r in rows])
    tempo_values     = np.array([r.tempo_librosa or 0.0 for r in rows])
    centroid_values  = np.array([r.spectral_centroid or 0.0 for r in rows])
    zcr_values       = np.array([r.zero_crossing_rate or 0.0 for r in rows])

    # Chroma variance — higher = more harmonic richness / tonal complexity
    # JSONB columns come back from PostgreSQL as Python lists already — no json.loads needed
    chroma_variances = np.array([
        float(np.var(r.chroma_mean)) if r.chroma_mean else 0.0
        for r in rows
    ])

    # MFCC[1] — second coefficient correlates with tonal brightness
    mfcc1_values = np.array([
        float(r.mfcc_mean[1]) if r.mfcc_mean else 0.0
        for r in rows
    ])

    # ── Step 3: Percentile-normalize within this library ─────────────────────
    # Each feature is ranked 0.0–1.0 relative to the full library.
    # This ensures emotion labels spread across all 12 categories
    # regardless of genre (a calm library still has its "energetic" tracks).
    def percentile_normalize(arr: np.ndarray) -> np.ndarray:
        """Rank-based normalization → 0.0 to 1.0."""
        if arr.max() == arr.min():
            return np.full_like(arr, 0.5, dtype=float)
        ranks = arr.argsort().argsort().astype(float)
        return ranks / (len(ranks) - 1)

    rms_norm      = percentile_normalize(rms_values)
    tempo_norm    = percentile_normalize(tempo_values)
    centroid_norm = percentile_normalize(centroid_values)
    zcr_norm      = percentile_normalize(zcr_values)
    chroma_norm   = percentile_normalize(chroma_variances)
    mfcc1_norm    = percentile_normalize(mfcc1_values)

    # ── Step 4: Derive energy + valence scores ────────────────────────────────
    # energy:  weighted combo of loudness (rms), speed (tempo), percussiveness (zcr)
    # valence: weighted combo of brightness (centroid), harmonic richness (chroma),
    #          tonal warmth (mfcc1 — higher = brighter/more positive sounding)
    energy  = 0.45 * rms_norm  + 0.35 * tempo_norm  + 0.20 * zcr_norm
    valence = 0.40 * centroid_norm + 0.35 * chroma_norm + 0.25 * mfcc1_norm

    # Re-normalize composite scores to 0–1
    energy  = percentile_normalize(energy)
    valence = percentile_normalize(valence)

    # ── Step 5: Map (energy, valence) → emotion label ────────────────────────
    # 2D grid matching arc planner's energy_centers and valence intuition.
    # Each bucket: (energy_min, energy_max, valence_min, valence_max) → label
    # Buckets are ordered by specificity — more specific rules first.
    EMOTION_BUCKETS = [
        # energy  range    valence range    label
        (0.75, 1.00,  0.60, 1.00,  "euphoric"),
        (0.75, 1.00,  0.35, 0.60,  "energetic"),
        (0.75, 1.00,  0.00, 0.35,  "tense"),
        (0.55, 0.75,  0.60, 1.00,  "happy"),
        (0.55, 0.75,  0.35, 0.65,  "focused"),
        (0.55, 0.75,  0.00, 0.35,  "angry"),
        (0.30, 0.55,  0.55, 1.00,  "romantic"),
        (0.30, 0.55,  0.35, 0.55,  "neutral"),
        (0.30, 0.55,  0.00, 0.35,  "nostalgic"),
        (0.00, 0.30,  0.45, 1.00,  "peaceful"),
        (0.00, 0.30,  0.20, 0.45,  "melancholic"),
        (0.00, 0.30,  0.00, 0.20,  "sad"),
    ]

    def assign_emotion(e: float, v: float) -> tuple[str, float]:
        """
        Returns (label, confidence).
        Confidence = how centered the track is within its bucket (0.5–1.0).
        Tracks near bucket boundaries get lower confidence — arc planner uses
        these as bridge tracks between emotion segments.
        """
        for e_min, e_max, v_min, v_max, label in EMOTION_BUCKETS:
            if e_min <= e <= e_max and v_min <= v <= v_max:
                # Distance from bucket center → confidence
                e_center = (e_min + e_max) / 2
                v_center = (v_min + v_max) / 2
                e_range  = (e_max - e_min) / 2
                v_range  = (v_max - v_min) / 2
                e_dist   = abs(e - e_center) / e_range
                v_dist   = abs(v - v_center) / v_range
                confidence = round(1.0 - 0.5 * (e_dist + v_dist) / 2, 3)
                return label, max(0.5, confidence)
        # Fallback — shouldn't happen with full coverage buckets
        return "neutral", 0.5

    # ── Step 6: Write to DB ───────────────────────────────────────────────────
    total_classified = 0
    label_counts: dict[str, int] = {}

    with engine.begin() as conn:
        for i, track_id in enumerate(track_ids):
            e = float(energy[i])
            v = float(valence[i])
            label, confidence = assign_emotion(e, v)

            conn.execute(text("""
                UPDATE track_features SET
                    energy           = :energy,
                    valence          = :valence,
                    emotion_label    = :label,
                    emotion_confidence = :confidence,
                    updated_at       = now()
                WHERE track_id = :track_id
            """), {
                "energy":     round(e, 4),
                "valence":    round(v, 4),
                "label":      label,
                "confidence": confidence,
                "track_id":   track_id,
            })

            label_counts[label] = label_counts.get(label, 0) + 1
            total_classified += 1

    # ── Step 7: Report distribution ──────────────────────────────────────────
    print(f"\n📊 Emotion classification complete — {total_classified} tracks classified")
    print("\n  Label distribution:")
    for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
        bar = "█" * (count // 3)
        pct = round(count / total_classified * 100, 1)
        print(f"    {label:<14} {count:>4}  {pct:>5}%  {bar}")

    context["ti"].xcom_push(key="emotions_classified", value=total_classified)
    context["ti"].xcom_push(key="emotion_distribution", value=label_counts)
    return total_classified


# ─── DAG Task Graph ───────────────────────────────────────────────────────────

t1_seed = PythonOperator(
    task_id="seed_tracks_from_library",
    python_callable=seed_tracks_from_library,
    dag=dag,
)

t2_features = PythonOperator(
    task_id="extract_audio_features",
    python_callable=extract_audio_features,
    dag=dag,
)

t3_emotions = PythonOperator(
    task_id="classify_emotions",
    python_callable=classify_emotions,
    dag=dag,
)

t4_log = PythonOperator(
    task_id="log_pipeline_run",
    python_callable=log_pipeline_run,
    dag=dag,
)

t1_seed >> t2_features >> t3_emotions >> t4_log
