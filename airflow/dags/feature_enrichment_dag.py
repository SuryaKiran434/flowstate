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
            # Clamp tempo to 60-160 BPM — librosa octave error doubles/halves real BPM
            while tempo > 160: tempo /= 2
            while tempo < 60:  tempo *= 2

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
    V2 — Region-aware emotion classifier.

    Key improvement over V1:
    - Detects music region (indian / western) from artist_names
    - Normalizes percentiles WITHIN each region separately
    - Indian film music composers/artists have a dedicated lookup set
    - Prevents cross-contamination: a soft AR Rahman ballad won't be
      labelled "energetic" just because it's louder than other Indian tracks
      when compared globally against Western EDM

    Additional improvements:
    - Valence formula adjusted: chroma_variance weighted higher for Indian
      music (raga-based harmony shows up strongly in chroma)
    - Confidence scoring unchanged
    - Idempotent: only processes tracks with emotion_label IS NULL
    """
    import os
    import json
    import numpy as np
    from sqlalchemy import create_engine, text

    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://flowstate:flowstate_dev@db:5432/flowstate")
    engine = create_engine(DATABASE_URL)

    # ── Indian music artist/composer detection set ────────────────────────────
    # Covers major South Indian (Telugu, Tamil, Kannada, Malayalam) + Hindi
    # composers, playback singers, and music directors.
    # Add more names here as needed — matching is case-insensitive substring.
    INDIAN_ARTISTS = {
    # ── Legendary playback singers ──────────────────────────────────────────
    "s. p. balasubrahmanyam", "s.p. balasubrahmanyam", "sp balasubrahmanyam",
    "s. janaki", "s.janaki", "s. p. sailaja", "s.p. sailaja",
    "p. susheela", "p.susheela", "k. j. yesudas", "k.j. yesudas",
    "vani jairam", "ghantasala", "s. sowmya", "swarnalatha",
    "udit narayan", "kumar sanu", "alka yagnik", "kavitha krishnamurthy",
    "k. s. chithra", "k.s. chithra", "k. s. harisankar",
    "unnikrishnan", "unni menon", "p. jayachandran",
    "bombay jayashri", "vasundhara das", "nithya menen",

    # ── South Indian composers ───────────────────────────────────────────────
    "a.r. rahman", "ar rahman", "ilaiyaraaja", "harris jayaraj",
    "yuvan shankar raja", "devi sri prasad", "dsp", "thaman s", "thaman",
    "anirudh ravichander", "anirudh", "sai karthik", "govind vasantha",
    "mickey j. meyer", "anup rubens", "vivek sagar", "jakes bejoy",
    "gopi sundar", "shaan rahman", "hesham abdul wahab",
    "g. v. prakash", "gv prakash", "g.v. prakash",
    "m. m. keeravaani", "m.m. keeravaani", "keeravani", "mm keeravaani",
    "mani sharma", "dhibu ninan thomas", "vishal chandrashekhar",
    "justin prabhakaran", "santhosh narayanan", "vivek - mervin",
    "sean roldan", "sam c.s.", "radhan", "ravi basrur",
    "praveen lakkaraju", "pravin lakkaraju", "shakthikanth karthick",
    "sushin shyam", "bijibal", "sunny m.r.", "sid sriram",
    "vijai bulganin", "vijay vijay", "vishnu vijay", "hip hop tamizha",
    "hiphop tamizha", "nivas k prasanna", "chaitan bharadwaj",
    "siddharth vipin", "vinayak sasikumar", "anand aravindakshan",

    # ── Hindi film composers ─────────────────────────────────────────────────
    "pritam", "amit trivedi", "vishal-shekhar", "vishal shekhar",
    "shankar-ehsaan-loy", "shankar ehsaan loy", "shankar mahadevan",
    "sachin-jigar", "sachin jigar", "ajay-atul", "ajay atul",
    "mithoon", "salim-sulaiman", "salim sulaiman", "jatin-lalit",
    "himesh reshammiya", "bappi lahiri", "r. d. burman", "rd burman",
    "tanishk bagchi", "rochak kohli", "lijo george-dj chetas",
    "sanjay leela bhansali", "shashwat sachdev", "siddharth-garima",
    "siddharth - garima", "meet bros", "meet bros anjjan",
    "chirantan bhatt", "lalit sen", "sandeep chowta",
    "sandeep nath", "sachet-parampara", "sachet parampara",
    "varun jain", "ritviz", "lost stories",

    # ── South Indian playback singers ────────────────────────────────────────
    "haricharan", "karthik", "chinmayi", "shreya ghoshal",
    "sid sriram", "vijay prakash", "naresh iyer", "mahalakshmi iyer",
    "sadhana sargam", "hariharan", "kk", "sonu nigam", "sunidhi chauhan",
    "shaan", "udit narayan", "hemachandra vedala", "anurag kulkarni",
    "rahul nambiar", "benny dayal", "jonita Gandhi", "jonita gandhi",
    "shweta mohan", "saindhavi", "nithyashree mahadevan",
    "bombay jayashri", "tippu", "velvet voice karthik",
    "srinidhi", "sithara krishnakumar", "sivaangi krishnakumar",
    "madhuvanthi narayan", "haripriya", "padmalatha",
    "anjana sowmya", "gopika poornima", "geetha madhuri",
    "ramya behara", "sahithi", "sahithi chaganti", "sravana bhargavi",
    "nutana mohan", "sunitha", "sunitha sarathy", "sweekar", "sweekar agasthi",
    "ranina reddy", "manisha eerabathini", "satya yamini",
    "nakash aziz", "shashaa tirupati", "armaan malik",

    # ── Telugu/Tamil lyricists & supporting artists ──────────────────────────
    "anantha sriram", "blaaze", "kittu vissapragada", "adk",
    "sirivennela seetharama sastry", "ramajogayya sastry",
    "vennelakanti", "bhuvana chandra", "bhaskarabhatla", "kasarla shyam",
    "veturi", "veturi sundararama murthy", "chandra bose", "srimani",
    "madhan karky", "arunraja kamaraj", "hriday gattani",
    "devan ekambaram", "irshad kamil", "prasoon joshi",
    "kumaar", "swanand kirkire", "amitabh bhattacharya",
    "kausar munir", "manoj muntashir", "jaideep sahni",
    "anvita dutt", "sayeed quadri", "kunaal vermaa",

    # ── Hindi playback singers ───────────────────────────────────────────────
    "arijit singh", "jubin nautiyal", "mohit chauhan", "javed ali",
    "atif aslam", "rahat fateh ali khan", "nusrat fateh ali khan",
    "shafqat amanat ali", "ali sethi", "sonu nigam", "mika singh",
    "neha kakkar", "tulsi kumar", "palak muchhal", "shreya ghoshal",
    "sunidhi chauhan", "alka yagnik", "asha bhosle", "lata mangeshkar",
    "harshdeep kaur", "nooran sisters", "neeti mohan", "jasleen royal",
    "shilpa rao", "jonita gandhi", "antara mitra", "monali thakur",
    "shweta pandit", "asees kaur", "dhvani bhanushali", "payal dev",
    "b praak", "kanika kapoor", "vishal mishra", "stebin ben",
    "darshan raval", "guru randhawa", "badshah", "yo yo honey singh",
    "diljit dosanjh", "ammy virk", "ap dhillon", "karan sehmbi",
    "maninder buttar", "pav dharia", "jazadin", "jaz dhami",

    # ── Regional/indie Indian artists ────────────────────────────────────────
    "sai abhyankkar", "mitraz", "ritviz", "prateek kuhad",
    "vidya vox", "rahul sipligunj", "kala bhairava",
    "ranjith govind", "ranjith", "ram miriyala", "dhanush",
    "sivakarthikeyan", "silambarasan tr", "vijay", "kamal haasan",
    "dulquer salmaan", "nazriya nazim", "mammootty",
    "vishal dadlani", "shankar mahadevan", "salman khan",
    "ayushmann khurrana", "nakul", "sanjith hegde",
    "nikhil d'souza", "nikhil paul george", "kunal ganjawala",
    "roop kumar rathod", "nakash aziz", "sanah moidutty",
    "manu manjith", "sujatha", "mano", "s.p. charan", "sp charan",
    "malaysia vasudevan", "k. s. harisankar", "vijay yesudas",
    "hesham abdul wahab", "sithara krishnakumar",
    "mukesh", "kishore kumar", "mohammed rafi", "hemant kumar",

    # ── Composers/artists with single names ─────────────────────────────────
    "brodha v", "raftaar", "divine", "naezy", "mc stan",
    "mc mushti", "hiphop tamizha", "arivu", "dabzee",
    "asal kolaar", "mugen rao", "dhanush", "yuvan",
    "ganga", "andal", "chitra", "mano", "tippu",
    "sujatha", "harini", "charulatha", "padma", "usha",
    "savithri", "smitha", "malathi", "deepa", "divya",
    "renuka", "sridevi", "gayatri", "radhan",

    # ── Specific artists from your DB ────────────────────────────────────────
    "vishal chandrashekhar", "s.p. charan", "krishna kanth",
    "david simon", "anitha", "ranjith govind", "nakash aziz",
    "sanah moidutty", "sai abhyankkar", "paal dabba", "bhumi",
    "deepthi suresh", "yugendran vasudeva nair", "inno genga",
    "malaysia vasudevan", "vijay", "asal kolaar", "vishnu edavan",
    "alka yagnik", "karan sehmbi", "goldboy", "sameera bharadwaj",
    "giulio cercato",  # <- likely indian fusion
    "kala bhairava", "ram miriyala", "rahul nambiar",
    "ilaiyaraaja", "charulatha mani", "hariharan",
    "sumangaly", "balaji", "adnan sami", "nithya menen",
    "u.v.jackey", "anup rubens", "vivek", "nadeesh",
    "suzanne d'mello", "hriday gattani", "devan ekambaram",
    "anantha sriram", "kittu vissapragada", "adk",
    "srinivasa mouli", "gowtham bharadwaj", "aalaap raju",
    "aashir wajahat", "aastha gill", "aavani malhar",
    "abhay jodhpurkar", "abhijay sharma", "abhijeet",
    "abhijit vaghani", "adithi singh sharma", "aditi shankar",
    "aditya rikhari", "ajaey shravan", "aishwarya majmudar",
    "ajay-atul", "akhil", "altamash faridi", "alyssa mendonsa",
    "anand bhaskar", "ananya bhat", "anjana sowmya",
    "ankit menon", "ankit tiwari", "annural khalid",
    "anthony daasan", "anudeep dev", "anuj gurwara",
    "anumita nadesan", "anupam amod", "aravindh sankar",
    "arivu", "arun", "arun chiluveru", "arunraja kamaraj",
    "asees kaur", "asena", "avvy sra", "ayyan pranathi",
    "badshah", "baman", "bela shende", "bellie raj",
    "benny dayal", "bhadra rajin", "bhaskarabhatla",
    "bheems ceciroleo", "bhumi", "bhuvana chandra",
    "bilal saeed", "bindu mahima", "bobby-imran",
    "caralisa monteiro", "chaitan bharadwaj", "chaitanya prasad",
    "chamath sangeeth", "chet singh", "chinna ponnu",
    "chirantan bhatt", "chorus", "darshana rajendran",
    "darshan raval", "d.burn", "deva", "dhanunjay seepana",
    "dhee", "dhvani bhanushali", "diljit dosanjh", "dilushselva",
    "divya kumar", "dj exe", "dulquer salmaan",
    "emcee jesz", "ganga", "gautham vasudev menon", "gayatri",
    "geetha madhuri", "ghantasala", "gopika poornima",
    "gowtham bharadwaj", "g sahithi", "gurinder gill",
    "gurnazar", "gurpreet saini", "haarika narayan",
    "haji springer", "hansika", "harini", "harini ivaturi",
    "haripriya", "harish raghavendra", "harrdy sandhu",
    "hesham abdul wahab", "hiphop tamizha",
    "ip singh", "jaani", "jadu jadu", "jai dhir",
    "jaspreet", "jaspreet jasz", "jassie gift", "jay krish",
    "jeans srinivas", "jigar saraiya", "jonita gandhi",
    "jr. ntr", "jyothsna", "jyotica tangri",
    "kailash kher", "kalai mk", "kalpana patowary",
    "kalyani nair", "kamalakar", "kanika kapoor",
    "kapil", "kapilan kugavel", "karunya", "kasarla shyam",
    "kausar munir", "kaushik krish", "keerthana sharma",
    "keerthi sagathia", "khushi murali", "kiddo", "kid sathya",
    "kiran kamath", "kranthi sekhar", "krish", "krishh",
    "krishna chaitanya", "krishna chithanya", "krishnakali saha",
    "krishna kanth", "krisshh", "kshitij patwardhan",
    "ku karthik", "kunal ganjawala", "kutle khan",
    "kushi murali", "l. v. revanth", "maanu",
    "madhusree", "mahathi", "mahati swara sagar",
    "malathi", "malavika", "malvi sundaresan",
    "mamta mohandas", "maninder buttar", "mani sharma",
    "manj musik", "mano", "marian hill", "mathan",
    "mathangi", "mc mushti", "m. d. rajendran",
    "mellen gi", "mervin solomon", "ml gayatri",
    "m.m.manasi", "mm sreelekha", "mohana",
    "mohana bhogaraju", "mohan rajan", "momina mustehsan",
    "mugen rao", "murali", "muralidhar",
    "naga saihithi", "nakul", "narendra",
    "naresh ayar", "naveen", "naveen madhav",
    "naven", "navin raaj mathavan", "nayana nair",
    "nazriya nazim", "neeti mohan", "nehaal naseem",
    "neha bhasin", "nikhil d'souza", "nikhil paul george",
    "nikhita gandhi", "nikita nigam", "nupoor khedkar",
    "nutana mohan", "oaff", "paal dabba", "padma",
    "padmalatha", "parampara tandon", "parampara thakur",
    "pawni pandey", "peddapalli rohith", "pradeep kumar",
    "pradeep ranganathan", "pranavi", "pranavi acharya",
    "prasanna.r", "prasanthini", "prashan sean",
    "prashanthini", "pravin saivi", "priya mali",
    "priya prakash", "priya saraiya", "prudhvi chandra",
    "p s jayhari", "purnachary", "raaban", "raghav",
    "ragini tandan", "raja hasan", "rajat nagpal",
    "raj ranjodh", "raj thillaiyampalam",
    "saraswati putra ramajogayya sastry", "ramcharan",
    "ram pothineni", "ramya nsk", "ranina reddy",
    "ranji", "ranjith", "rashid ali", "rashmeet kaur",
    "riar saab", "ritviz", "r maalavika manoj",
    "rohit gopalakrishnan", "roisee", "rokesh",
    "roop kumar rathod", "roshini jkv", "roshni baptist",
    "rzee", "sachin sanghvi", "sagar", "sagar desai",
    "sahiti", "saindhavi", "saint t.f.c.", "sai smriti",
    "saketh komanduri", "saketh naidu", "sanjana",
    "sanapati bharadwaj patrudu", "sandeep nath",
    "sandilya pisapati", "sanjith hegde", "sankar sharma",
    "santosh.g", "satheeshan", "sathya.c", "sathyaprakash",
    "satya", "savera", "savithri", "scammacist",
    "sdm nation", "shaan", "shadab faridi", "shae gill",
    "shahil hada", "shakthisree gopalan", "sharan",
    "shashwat singh", "shefali alvares", "shekar chandra",
    "shekhar ravjiani", "shivani", "shree mani",
    "shreshta", "shruthika samudhrala", "shruti pathak",
    "shweta pandit", "siddharth", "siddharth - garima",
    "siddhu kumar", "silambarasan tr", "silvia anisha",
    "simran choudhary", "sinduri vishal",
    "sirivennela seetharama sastry", "sivaraman",
    "smitha", "sniggy", "sofia carson",
    "spoorthi jithender", "sravana bhargavi", "sravani",
    "srikanth addala", "sri krishna", "sri madhumitha",
    "srinidhi", "srinisha jayaseelan", "srinivas",
    "srinivasa mouli", "sri vasanth", "sruthi ml",
    "sruthi ranjani", "stebin ben", "sublahshini",
    "suchithra karthik kumar", "suchith santoshan",
    "suchith suresan", "suchitra", "suchit suresan",
    "sudarshan ashok", "sudharshan ashok", "suhail koya",
    "sukh-e muzical doctorz", "sukhwinder singh",
    "sumangaly", "sunitha", "sunitha sarathy",
    "super subu", "suraj", "surendra krishna",
    "swanand kirkire", "sweetaj brar", "swetha pandit",
    "teja", "the doorbeen", "the indian choral ensemble",
    "the prophec", "tippu", "tony kakkar", "tulsi kumar",
    "uma neha", "usha", "u.v.jackey",
    "vaishali samant", "varun jain", "varun parandhaman",
    "vedan", "ved sharma", "vennelakanti", "venu srirangam",
    "veturi", "veturi sundararama murthy", "vignesh ramakrishna",
    "vigz", "vimal roy", "vinayak sasikumar",
    "vinod yajamanya", "vishnupriya ravi",
    "vv prassanna", "yazin", "yohani", "young desi",
    "young tapz", "yugendran vasudeva nair",
    }

    def detect_region(artist_names_str: str) -> str:
        """Returns 'indian' or 'western' based on artist name matching."""
        if not artist_names_str:
            return "western"

        lower = artist_names_str.lower()
        for artist in INDIAN_ARTISTS:
            if artist in lower:
                return "indian"
        # Also detect Telugu/Tamil/Hindi script characters as fallback
        for char in artist_names_str:
            if '\u0C00' <= char <= '\u0C7F':  # Telugu unicode block
                return "indian"
            if '\u0900' <= char <= '\u097F':  # Devanagari (Hindi)
                return "indian"
            if '\u0B80' <= char <= '\u0BFF':  # Tamil
                return "indian"
        return "western"

    # ── Step 1: Load tracks with features but no emotion label ───────────────
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                tf.track_id,
                tf.rms_energy,
                tf.tempo_librosa,
                tf.spectral_centroid,
                tf.zero_crossing_rate,
                tf.chroma_mean,
                tf.mfcc_mean,
                t.artist_names
            FROM track_features tf
            JOIN tracks t ON t.id = tf.track_id
            WHERE tf.rms_energy IS NOT NULL
              AND tf.emotion_label IS NULL
        """)).fetchall()

    if not rows:
        print("No tracks needing emotion classification — all up to date.")
        return 0

    print(f"Classifying emotions for {len(rows)} tracks...")

    # ── Step 2: Split into regional buckets ──────────────────────────────────
    regions = [detect_region(r.artist_names or "") for r in rows]
    indian_idx  = [i for i, r in enumerate(regions) if r == "indian"]
    western_idx = [i for i, r in enumerate(regions) if r == "western"]

    print(f"  Indian tracks: {len(indian_idx)} | Western tracks: {len(western_idx)}")

    # ── Step 3: Extract raw feature arrays ───────────────────────────────────
    track_ids       = [r.track_id for r in rows]
    rms_values      = np.array([r.rms_energy or 0.0    for r in rows])
    tempo_values    = np.array([r.tempo_librosa or 0.0 for r in rows])
    centroid_values = np.array([r.spectral_centroid or 0.0 for r in rows])
    zcr_values      = np.array([r.zero_crossing_rate or 0.0 for r in rows])
    chroma_variances = np.array([
        float(np.var(r.chroma_mean)) if r.chroma_mean else 0.0
        for r in rows
    ])
    mfcc1_values = np.array([
        float(r.mfcc_mean[1]) if r.mfcc_mean else 0.0
        for r in rows
    ])

    # ── Step 4: Percentile normalization ─────────────────────────────────────
    def percentile_normalize(arr: np.ndarray) -> np.ndarray:
        if len(arr) == 0:
            return arr
        if arr.max() == arr.min():
            return np.full_like(arr, 0.5, dtype=float)
        ranks = arr.argsort().argsort().astype(float)
        return ranks / (len(ranks) - 1)

    def normalize_by_region(values: np.ndarray, idx_list: list) -> np.ndarray:
        """
        Normalize values only within the given index subset.
        Each region gets its own 0-1 scale so Indian tracks compare
        against Indian tracks, Western against Western.
        """
        result = np.zeros(len(values))
        if not idx_list:
            return result
        subset = values[idx_list]
        normalized = percentile_normalize(subset)
        for i, global_i in enumerate(idx_list):
            result[global_i] = normalized[i]
        return result

    # Normalize each feature within its region
    rms_norm      = np.zeros(len(rows))
    tempo_norm    = np.zeros(len(rows))
    centroid_norm = np.zeros(len(rows))
    zcr_norm      = np.zeros(len(rows))
    chroma_norm   = np.zeros(len(rows))
    mfcc1_norm    = np.zeros(len(rows))

    for idx_group in [indian_idx, western_idx]:
        if not idx_group:
            continue
        idx = idx_group
        rms_norm[idx]      = normalize_by_region(rms_values,      idx)[idx]
        tempo_norm[idx]    = normalize_by_region(tempo_values,     idx)[idx]
        centroid_norm[idx] = normalize_by_region(centroid_values,  idx)[idx]
        zcr_norm[idx]      = normalize_by_region(zcr_values,       idx)[idx]
        chroma_norm[idx]   = normalize_by_region(chroma_variances, idx)[idx]
        mfcc1_norm[idx]    = normalize_by_region(mfcc1_values,     idx)[idx]

    # ── Step 5: Derive energy + valence ──────────────────────────────────────
    # Indian music: chroma variance weighted higher (raga-based harmony)
    # Western music: original weights preserved
    energy  = np.zeros(len(rows))
    valence = np.zeros(len(rows))

    for i, region in enumerate(regions):
        if region == "indian":
            energy[i]  = 0.45 * rms_norm[i] + 0.35 * tempo_norm[i] + 0.20 * zcr_norm[i]
            valence[i] = 0.30 * centroid_norm[i] + 0.45 * chroma_norm[i] + 0.25 * mfcc1_norm[i]
        else:
            energy[i]  = 0.45 * rms_norm[i] + 0.35 * tempo_norm[i] + 0.20 * zcr_norm[i]
            valence[i] = 0.40 * centroid_norm[i] + 0.35 * chroma_norm[i] + 0.25 * mfcc1_norm[i]

    # Re-normalize composites within each region
    for idx_group in [indian_idx, western_idx]:
        if not idx_group:
            continue
        idx = idx_group
        e_sub = energy[idx]
        v_sub = valence[idx]
        energy[idx]  = percentile_normalize(e_sub)
        valence[idx] = percentile_normalize(v_sub)

    # ── Step 6: Emotion bucket mapping (unchanged) ────────────────────────────
    EMOTION_BUCKETS = [
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
        for e_min, e_max, v_min, v_max, label in EMOTION_BUCKETS:
            if e_min <= e <= e_max and v_min <= v <= v_max:
                e_center = (e_min + e_max) / 2
                v_center = (v_min + v_max) / 2
                e_range  = (e_max - e_min) / 2
                v_range  = (v_max - v_min) / 2
                e_dist   = abs(e - e_center) / e_range
                v_dist   = abs(v - v_center) / v_range
                confidence = round(1.0 - 0.5 * (e_dist + v_dist) / 2, 3)
                return label, max(0.5, confidence)
        return "neutral", 0.5

    # ── Step 7: Write to DB ───────────────────────────────────────────────────
    total_classified = 0
    label_counts: dict[str, int] = {}
    region_label_counts = {"indian": {}, "western": {}}

    with engine.begin() as conn:
        for i, track_id in enumerate(track_ids):
            e = float(energy[i])
            v = float(valence[i])
            label, confidence = assign_emotion(e, v)
            region = regions[i]

            conn.execute(text("""
                UPDATE track_features SET
                    energy             = :energy,
                    valence            = :valence,
                    emotion_label      = :label,
                    emotion_confidence = :confidence,
                    updated_at         = now()
                WHERE track_id = :track_id
            """), {
                "energy":     round(e, 4),
                "valence":    round(v, 4),
                "label":      label,
                "confidence": confidence,
                "track_id":   track_id,
            })

            label_counts[label] = label_counts.get(label, 0) + 1
            region_label_counts[region][label] = region_label_counts[region].get(label, 0) + 1
            total_classified += 1

    # ── Step 8: Report ────────────────────────────────────────────────────────
    print(f"\n📊 Emotion classification complete — {total_classified} tracks")

    for region in ["indian", "western"]:
        rcounts = region_label_counts[region]
        if not rcounts:
            continue
        rtotal = sum(rcounts.values())
        print(f"\n  {region.upper()} ({rtotal} tracks):")
        for label, count in sorted(rcounts.items(), key=lambda x: -x[1]):
            pct = round(count / rtotal * 100, 1)
            bar = "█" * (count // 2)
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
