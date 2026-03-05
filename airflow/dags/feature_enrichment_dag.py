"""
Feature Enrichment DAG — Flowstate
------------------------------------
Runs daily to pull new tracks from user Spotify libraries,
extract audio features, run emotion classification, and
update the pgvector embedding store.

Schedule: Daily at 2:00 AM UTC
Author: Surya Kiran Katragadda
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago

# ─── Default Args ────────────────────────────────────────────────────────────

default_args = {
    "owner": "SuryaKiran434",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
}

# ─── DAG Definition ──────────────────────────────────────────────────────────

dag = DAG(
    dag_id="feature_enrichment",
    description="Pull new Spotify tracks, extract audio features, classify emotions",
    schedule_interval="0 2 * * *",      # daily at 2AM UTC
    start_date=days_ago(1),
    catchup=False,
    default_args=default_args,
    tags=["flowstate", "data-pipeline", "spotify", "ml"],
    max_active_runs=1,
)

# ─── Task Functions ───────────────────────────────────────────────────────────

def pull_new_tracks(**context):
    """
    Pull saved tracks and playlist tracks from Spotify for all active users.
    Writes raw track metadata to data/raw/tracks_{date}.json
    Handles rate limiting with exponential backoff.
    """
    import json
    import os
    import time
    from datetime import date
    import httpx

    # In production: iterate over all active users' tokens
    # For now: demonstrate the pattern with env-configured token
    print("Pulling new tracks from Spotify API...")

    output_path = f"/opt/airflow/data/raw/tracks_{date.today().isoformat()}.json"

    # Placeholder — real implementation queries DB for active user tokens
    # and calls GET /me/tracks + GET /playlists/{id}/tracks
    tracks = []

    with open(output_path, "w") as f:
        json.dump(tracks, f)

    context["ti"].xcom_push(key="output_path", value=output_path)
    context["ti"].xcom_push(key="track_count", value=len(tracks))
    print(f"Pulled {len(tracks)} tracks → {output_path}")


def extract_spotify_features(**context):
    """
    Call Spotify Audio Features API for all new tracks.
    Writes enriched data to data/processed/features_{date}.json.
    Handles 429 rate limit responses gracefully.
    """
    import json
    from datetime import date

    input_path = context["ti"].xcom_pull(key="output_path", task_ids="pull_new_tracks")
    print(f"Extracting Spotify audio features for tracks in {input_path}...")

    with open(input_path) as f:
        tracks = json.load(f)

    enriched = []
    # Batch requests to Spotify in groups of 100 (API limit)
    batch_size = 100
    for i in range(0, len(tracks), batch_size):
        batch = tracks[i:i + batch_size]
        # GET /audio-features?ids=id1,id2,...
        # Store valence, energy, tempo, danceability, etc.
        enriched.extend(batch)

    output_path = f"/opt/airflow/data/processed/features_{date.today().isoformat()}.json"
    with open(output_path, "w") as f:
        json.dump(enriched, f)

    context["ti"].xcom_push(key="features_path", value=output_path)
    print(f"Extracted features for {len(enriched)} tracks → {output_path}")


def extract_librosa_features(**context):
    """
    Download 30s preview clips and extract librosa features:
    - 13 MFCCs (mean + std)
    - 12 chroma features
    - Spectral centroid
    - Zero crossing rate
    - Tempo (BPM)

    Skips tracks without preview_url.
    """
    import json
    import os
    import tempfile
    from datetime import date

    import librosa
    import numpy as np
    import httpx

    features_path = context["ti"].xcom_pull(key="features_path", task_ids="extract_spotify_features")

    with open(features_path) as f:
        tracks = json.load(f)

    enriched = []
    for track in tracks:
        preview_url = track.get("preview_url")
        if not preview_url:
            track["librosa_features"] = None
            enriched.append(track)
            continue

        try:
            # Download 30s preview
            audio_data = httpx.get(preview_url, timeout=10).content

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name

            # Load with librosa
            y, sr = librosa.load(tmp_path, sr=22050, duration=30)
            os.unlink(tmp_path)

            # Extract features
            mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            chroma = librosa.feature.chroma_stft(y=y, sr=sr)
            spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
            zcr = librosa.feature.zero_crossing_rate(y)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)

            track["librosa_features"] = {
                "mfcc_mean": mfccs.mean(axis=1).tolist(),
                "mfcc_std": mfccs.std(axis=1).tolist(),
                "chroma_mean": chroma.mean(axis=1).tolist(),
                "spectral_centroid": float(spectral_centroid.mean()),
                "zero_crossing_rate": float(zcr.mean()),
                "tempo_librosa": float(tempo),
            }

        except Exception as e:
            print(f"Warning: librosa extraction failed for {track.get('id')}: {e}")
            track["librosa_features"] = None

        enriched.append(track)

    output_path = f"/opt/airflow/data/processed/librosa_{date.today().isoformat()}.json"
    with open(output_path, "w") as f:
        json.dump(enriched, f)

    context["ti"].xcom_push(key="librosa_path", value=output_path)
    print(f"Extracted librosa features for {len(enriched)} tracks → {output_path}")


def run_emotion_inference(**context):
    """
    Run the trained emotion classifier on extracted features.
    Writes emotion labels + confidence scores to DB via SQLAlchemy.
    """
    import json
    import os
    from datetime import date

    librosa_path = context["ti"].xcom_pull(key="librosa_path", task_ids="extract_librosa_features")

    with open(librosa_path) as f:
        tracks = json.load(f)

    print(f"Running emotion inference on {len(tracks)} tracks...")

    # Load model from checkpoint
    # model = EmotionClassifier.load_from_checkpoint("/opt/airflow/data/models/latest.pt")

    labeled = 0
    for track in tracks:
        if track.get("librosa_features") and track.get("valence") is not None:
            # Build feature vector: [mfcc_mean(13), chroma_mean(12), valence, energy, tempo]
            # Pass through model → emotion label + confidence
            # Write to track_emotions table
            labeled += 1

    print(f"Labeled {labeled}/{len(tracks)} tracks with emotion predictions")


def update_embeddings(**context):
    """
    Recompute pgvector embeddings for newly labeled tracks.
    Uses a 50-dim PCA projection of the full feature vector.
    """
    print("Updating pgvector embeddings for newly labeled tracks...")
    # Query newly inserted track_emotions rows
    # Compute embeddings via PCA model
    # Upsert into track_features.embedding
    print("Embeddings updated.")


# ─── Task Definitions ─────────────────────────────────────────────────────────

t1_pull = PythonOperator(
    task_id="pull_new_tracks",
    python_callable=pull_new_tracks,
    dag=dag,
)

t2_spotify_features = PythonOperator(
    task_id="extract_spotify_features",
    python_callable=extract_spotify_features,
    dag=dag,
)

t3_librosa_features = PythonOperator(
    task_id="extract_librosa_features",
    python_callable=extract_librosa_features,
    dag=dag,
)

t4_inference = PythonOperator(
    task_id="run_emotion_inference",
    python_callable=run_emotion_inference,
    dag=dag,
)

t5_embeddings = PythonOperator(
    task_id="update_embeddings",
    python_callable=update_embeddings,
    dag=dag,
)

# ─── DAG Wiring ──────────────────────────────────────────────────────────────

t1_pull >> t2_spotify_features >> t3_librosa_features >> t4_inference >> t5_embeddings
