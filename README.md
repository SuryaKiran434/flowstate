# 🎵 Flowstate

> *Music that moves with you.*

**Flowstate** is an emotional arc engine that curates dynamic listening sessions based on where you are emotionally and where you want to be. Instead of static mood playlists, Flowstate asks *"where are you, and where do you want to go?"* — then constructs a musical bridge using audio ML, graph-based path planning, and real-time Spotify playback.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18+-61DAFB?style=flat&logo=react&logoColor=white)](https://reactjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-336791?style=flat&logo=postgresql&logoColor=white)](https://postgresql.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ✨ What Makes Flowstate Different

- **Custom Audio ML Pipeline** — 42-dimensional feature vectors (MFCCs, chroma, spectral centroid, tempo) extracted via **yt-dlp + librosa**. Works globally for Telugu, Tamil, Hindi, and international catalogs — no API restrictions, no language limits.
- **Graph-based Arc Planning** — modified Dijkstra on a 12-node emotion graph finds the smoothest perceptual path between any two emotional states.
- **Real-time Playback** — Spotify Web Playback SDK with a live D3.js arc visualizer.

> **Why yt-dlp instead of Spotify Audio Features?** Spotify deprecated `/audio-features` for new apps in 2025 (requires 250k MAU for access). Flowstate's yt-dlp + librosa pipeline sources audio from YouTube — global coverage, all languages, on-demand extraction as catalogs grow.

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────┐
│                     FRONTEND (React)                        │
│   Mood Input (Source→Target) │ Arc Viz (D3.js) │ Playback  │
└──────────────────────┬─────────────────────────────────────┘
                       │ REST API
┌──────────────────────▼─────────────────────────────────────┐
│                    BACKEND (FastAPI)                         │
│   /arc/generate  │  /session/*  │  /auth/spotify (PKCE)    │
│                                                             │
│   Arc Planning Service  →  Dijkstra on Emotion Graph       │
│   ML Inference Service  →  Emotion Classifier (librosa)    │
└──────────────────────┬─────────────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────────────┐
│                     DATA LAYER                               │
│   PostgreSQL + pgvector  │  Redis  │  Airflow DAGs          │
└────────────────────────────────────────────────────────────┘
```

---

## 🎵 Audio Feature Pipeline

```
Spotify Search API → track metadata
         │
         ▼
yt-dlp → YouTube search → 30s audio clip
         │
         ▼
librosa feature extraction
   ├── MFCCs (13 mean + 13 std)   — timbral texture       [26 dims]
   ├── Chroma mean (12)           — harmonic/pitch content [12 dims]
   ├── Spectral centroid          — brightness             [ 1 dim ]
   ├── Zero crossing rate         — noisiness              [ 1 dim ]
   ├── RMS energy                 — loudness proxy         [ 1 dim ]
   └── Tempo (BPM)               — energy indicator       [ 1 dim ]
         │                          Total: 42 dimensions
         ▼
PostgreSQL track_features → Emotion Classifier → Arc Planning
```

---

## 🗂️ Project Structure

```
flowstate/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/
│   │   │   ├── auth.py              # Spotify OAuth2 PKCE
│   │   │   └── tracks.py            # Library + feature endpoints
│   │   ├── models/
│   │   │   ├── track.py             # Track, TrackFeature, UserTrack ORM
│   │   │   └── user.py              # User ORM
│   │   └── services/
│   │       ├── arc_planner.py       # Dijkstra arc algorithm
│   │       └── spotify_client.py    # Spotify API wrapper
│   ├── requirements.txt             # Includes yt-dlp + librosa
│   └── Dockerfile                   # Includes ffmpeg for yt-dlp
│
├── airflow/dags/
│   └── feature_enrichment_dag.py    # Search → yt-dlp → librosa → DB
│
├── docs/
│   ├── PRD.md
│   ├── DB_SCHEMA.md
│   └── AUDIO_PIPELINE.md            # yt-dlp + librosa architecture
│
└── docker-compose.yml               # Airflow installs yt-dlp + ffmpeg on startup
```

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Spotify Developer account — [Create app](https://developer.spotify.com/dashboard)

### 1. Clone & configure

```bash
git clone https://github.com/SuryaKiran434/flowstate.git
cd flowstate
cp .env.example .env
# Fill in SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET
```

### 2. Start everything

```bash
docker-compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| Airflow | http://localhost:8080 |
| MLflow | http://localhost:5001 |

### 3. Seed the feature store

```bash
# Log in at http://localhost:3000 first to store a Spotify token
# Then trigger the pipeline:
docker exec flowstate_airflow airflow dags trigger feature_enrichment
```

The DAG will:
1. Search Spotify for ~180 tracks across 18 artist queries
2. For each track: yt-dlp → YouTube → librosa → 42-dim feature vector → PostgreSQL
3. Log metrics to MLflow

---

## 🧠 Arc Algorithm

Emotion space modelled as a **weighted directed graph**:
- **Nodes** — 12 states: energetic, peaceful, melancholic, euphoric, tense, nostalgic, romantic, angry, focused, sad, happy, neutral
- **Edges** — perceptual transition costs (how jarring is this jump?)
- Modified Dijkstra finds the lowest-cost emotional path from source → target
- Track selection per segment uses pgvector similarity search on 42-dim embeddings

---

## 🤖 ML Model

Feedforward classifier trained on 42-dimensional librosa features:

| Feature Group | Dims | What It Captures |
|---|---|---|
| MFCC mean + std | 26 | Timbral texture and dynamics |
| Chroma mean | 12 | Harmonic / pitch class content |
| Spectral centroid | 1 | Brightness |
| Zero crossing rate | 1 | Percussiveness / noisiness |
| RMS energy | 1 | Loudness |
| Tempo (BPM) | 1 | Energy |

Training and evaluation tracked with MLflow.

---

## 📊 How I'd Scale to 1M Users

| Challenge | Solution |
|---|---|
| yt-dlp slow (5–15s/track) | Pre-compute via Airflow; serve from pgvector |
| Arc generation latency | Cache common source→target paths in Redis |
| ML inference at scale | Export to ONNX, serve via Triton |
| DB reads under load | Read replicas + pgbouncer |
| YouTube blocks at scale | License audio via Musicstax/AudD for production |
| Cold start (new user) | Seed from `/me/top/artists` + Search API |

---

## 🛠️ Built With

| Layer | Technology |
|---|---|
| Audio pipeline | yt-dlp, librosa, ffmpeg |
| ML | scikit-learn, PyTorch, MLflow |
| Backend | FastAPI, SQLAlchemy |
| Database | PostgreSQL 15 + pgvector |
| Cache | Redis |
| Pipeline | Apache Airflow |
| Frontend | React 18, D3.js |
| Playback | Spotify Web Playback SDK |
| Auth | Spotify OAuth2 PKCE |
| Infra | Docker, Docker Compose, GitHub Actions |

---

## 🗺️ Roadmap

- [x] Spotify OAuth2 PKCE
- [x] Track seeding via Spotify Search API
- [x] yt-dlp + librosa audio feature pipeline
- [ ] Emotion classifier (Phase 3)
- [ ] Arc planning API endpoints
- [ ] D3.js arc visualizer
- [ ] Spotify Web Playback SDK
- [ ] CI/CD pipeline

---

## 👤 Author

**Surya Kiran Katragadda**
- GitHub: [@SuryaKiran434](https://github.com/SuryaKiran434)
- LinkedIn: [katragadda-suryakiran](https://www.linkedin.com/in/katragadda-suryakiran/)

---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

*Built with 100k minutes of listening experience and a love for music that actually understands you.*
