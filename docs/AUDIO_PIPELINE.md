# Audio Feature Extraction Pipeline — Flowstate

## Why We Built This

Flowstate needs audio features (tempo, timbre, harmonic content) to classify tracks into emotion states for arc planning. The obvious source — Spotify's `/audio-features` API — is unavailable:

| Approach | Status | Reason |
|---|---|---|
| Spotify `/audio-features` | ❌ | Blocked in Development Mode; deprecated for new apps (2025); Extended Quota requires 250k MAU |
| Spotify 30s preview URLs | ❌ | Not provided for Indian catalog (Telugu, Tamil, Hindi) |
| AcousticBrainz dataset | ❌ | Shut down 2022; static; missing Indian music |
| **yt-dlp + librosa** | ✅ | Works globally, on-demand, all languages |

---

## Pipeline Flow

```
Airflow DAG: feature_enrichment (daily 2AM UTC)

┌─────────────────────────────┐
│  Task 1: seed_tracks_via_search │
│                             │
│  Spotify Search API         │
│  18 queries × 10 results    │
│  → ~180 unique tracks/day   │
│  → upsert tracks + user_tracks │
└────────────┬────────────────┘
             │
┌────────────▼────────────────┐
│  Task 2: extract_audio_features │
│                             │
│  For each track:            │
│  1. yt-dlp YouTube search   │
│     "{name} {artist} audio" │
│  2. Download first 30s      │
│  3. librosa feature extract │
│  4. Store to track_features │
└────────────┬────────────────┘
             │
┌────────────▼────────────────┐
│  Task 3: log_pipeline_run   │
│  MLflow metrics             │
└─────────────────────────────┘
```

---

## Feature Vector (42 dimensions)

| Feature | Dims | Description |
|---|---|---|
| MFCC mean | 13 | Average timbral texture per coefficient |
| MFCC std | 13 | Timbral variation / dynamics |
| Chroma mean | 12 | Harmonic content across 12 pitch classes |
| Spectral centroid | 1 | Brightness — high = bright, low = warm/bass |
| Zero crossing rate | 1 | Noisiness / percussiveness |
| RMS energy | 1 | Loudness proxy |
| Tempo (BPM) | 1 | Primary energy indicator |
| **Total** | **42** | |

---

## yt-dlp Search Strategy

```bash
yt-dlp "ytsearch1:{track_name} {artist_name} audio" \
  --extract-audio --audio-format mp3 --audio-quality 5 \
  --download-sections "*0:00-0:35" \
  --max-downloads 1 --no-playlist
```

Validation: skip if file < 10KB (empty/corrupt download).

---

## Interviewer Talking Points

> "Spotify deprecated their audio features API for new apps in 2025, so I built a custom extraction pipeline. yt-dlp sources audio from YouTube — which has global coverage for all languages — and librosa computes a 42-dimensional feature vector including MFCCs, chroma, spectral centroid, and tempo. This actually gives richer features than Spotify provided, works for Telugu and Tamil music which Spotify doesn't have preview URLs for, and scales as the catalog grows since extraction is on-demand."

---

## Production Scaling

| Concern | Solution |
|---|---|
| yt-dlp slow (5–15s/track) | Pre-compute via Airflow; serve from feature store |
| YouTube rate limiting | Distribute across Airflow workers; add random sleep |
| YouTube blocks at scale | License audio via Musicstax/AudD for production |
| Re-downloading same audio | Cache .mp3 files in S3/GCS by track ID |
| Feature store growth | Partition track_features by extracted_at date |

---

## Local Setup

```bash
# Install yt-dlp in Airflow container
docker exec --user airflow flowstate_airflow python -m pip install yt-dlp librosa

# Trigger pipeline
docker exec flowstate_airflow airflow dags trigger feature_enrichment

# Check results
docker exec -it flowstate_db psql -U flowstate -c "
  SELECT
    COUNT(*) as total_tracks,
    COUNT(tf.track_id) as with_features,
    ROUND(AVG(tf.tempo_librosa)::numeric, 1) as avg_tempo
  FROM tracks t
  LEFT JOIN track_features tf ON t.id = tf.track_id;
"
```
