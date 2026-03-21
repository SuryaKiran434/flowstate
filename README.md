# Flowstate

> *Music that moves with you.*

**Flowstate** is an emotional arc engine that curates dynamic listening sessions based on where you are emotionally and where you want to be. Instead of static mood playlists, Flowstate asks *"where are you, and where do you want to go?"* — then constructs a musical bridge using audio ML, graph-based path planning, Claude-powered mood parsing, and real-time Spotify playback.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18+-61DAFB?style=flat&logo=react&logoColor=white)](https://reactjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-336791?style=flat&logo=postgresql&logoColor=white)](https://postgresql.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What Makes Flowstate Different

- **Custom Audio ML Pipeline** — 42-dimensional feature vectors (MFCCs, chroma, spectral centroid, tempo) extracted via **yt-dlp + librosa**. Works globally for Telugu, Tamil, Hindi, and international catalogs — no API restrictions, no language limits.
- **Graph-based Arc Planning** — Modified Dijkstra on a 12-node emotion graph finds the smoothest perceptual path between any two emotional states.
- **Claude-powered Mood Parsing** — Natural language input like *"I'm stressed and want to wind down"* is parsed by Claude into structured source/target emotion pairs, with keyword fallback.
- **Personal Library Seeding** — Builds from your actual Spotify playlists, liked tracks, and top artists — not generic catalog searches.
- **Real-time Playback** — Spotify Web Playback SDK with D3.js arc visualizer (in progress).

> **Why yt-dlp instead of Spotify Audio Features?** Spotify deprecated `/audio-features` for new apps in 2025 (requires 250k MAU for access). Flowstate's yt-dlp + librosa pipeline sources audio from YouTube — global coverage, all languages, on-demand extraction as catalogs grow.

---

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                     FRONTEND (React 18)                     │
│   Mood Input (Source→Target) │ Arc Viz (D3.js) │ Playback  │
└──────────────────────┬─────────────────────────────────────┘
                       │ REST API (Axios)
┌──────────────────────▼─────────────────────────────────────┐
│                    BACKEND (FastAPI)                         │
│   /arc/generate  │  /tracks/*  │  /auth/spotify (PKCE)     │
│                                                             │
│   MoodParser (Claude API)  →  Natural Language Input       │
│   Arc Planner (Dijkstra)   →  Emotion Graph Path Finding   │
│   ML Inference             →  Emotion Classifier (librosa) │
└──────────────────────┬─────────────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────────────┐
│                     DATA LAYER                               │
│   PostgreSQL 15 + pgvector  │  Redis  │  MLflow            │
└──────────────────────┬─────────────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────────────┐
│              AIRFLOW PIPELINE  (Daily 2AM UTC)              │
│   Spotify Library → yt-dlp → librosa → feature store       │
└────────────────────────────────────────────────────────────┘
```

---

## Audio Feature Pipeline

```
Spotify Personal Library → track metadata
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

## Project Structure

```
flowstate/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/
│   │   │   ├── auth.py              # Spotify OAuth2 PKCE flow
│   │   │   ├── tracks.py            # Library + feature endpoints
│   │   │   └── arc.py               # Arc generation + preview
│   │   ├── core/
│   │   │   ├── config.py            # Pydantic Settings (Spotify, DB, Claude)
│   │   │   └── security.py          # JWT token management
│   │   ├── models/
│   │   │   ├── track.py             # Track, TrackFeature, UserTrack ORM
│   │   │   └── user.py              # User ORM
│   │   └── services/
│   │       ├── arc_planner.py       # Dijkstra arc algorithm (12-node graph)
│   │       ├── spotify_client.py    # Spotify API wrapper + PKCE helpers
│   │       └── mood_parser.py       # Claude API mood parsing + keyword fallback
│   ├── requirements.txt             # Includes yt-dlp, librosa, anthropic
│   └── Dockerfile                   # Includes ffmpeg for yt-dlp
│
├── airflow/dags/
│   ├── feature_enrichment_dag.py    # Spotify → yt-dlp → librosa → DB (daily)
│   └── backfill_empty_tracks.py     # Backfill missing track metadata from Spotify
│
├── frontend/
│   └── src/
│       ├── App.jsx                  # Router + PrivateRoute guard
│       └── pages/
│           ├── Home.jsx             # Landing page + OAuth button
│           ├── Dashboard.jsx        # Arc builder + library stats
│           └── Callback.jsx         # Spotify OAuth redirect handler
│
├── docs/
│   ├── PRD.md                       # Product requirements + success metrics
│   ├── DB_SCHEMA.md                 # PostgreSQL 8-table schema with pgvector
│   └── AUDIO_PIPELINE.md            # yt-dlp + librosa architecture rationale
│
├── docker-compose.yml               # Full 6-service stack
├── .env.example                     # Config template
├── flowstate.sh                     # Local setup script
└── migrate_to_personal_library.sh   # Migration to personal library seeding
```

---

## Database Schema (8 Tables)

| Table | Purpose |
|---|---|
| `users` | Spotify profile + OAuth access/refresh tokens |
| `tracks` | Track metadata (Spotify ID, artist, album, duration, popularity) |
| `track_features` | 42-dim librosa feature vectors (MFCCs, chroma, spectral, tempo, RMS, ZCR) |
| `track_emotions` | ML-predicted emotion labels + confidence scores |
| `emotion_nodes` | 12 emotion states with tempo/energy ranges and centroid vectors |
| `emotion_edges` | Directed weighted transitions for Dijkstra graph traversal |
| `sessions` | User listening sessions (source/target emotion, status, arc path) |
| `session_tracks` | Ordered tracks within a session with playback position metadata |

pgvector IVFFlat indices enable fast cosine similarity search over 42-dim embeddings for track selection.

---

## Arc Algorithm

Emotion space modelled as a **weighted directed graph**:
- **Nodes** — 12 states: energetic, peaceful, melancholic, euphoric, tense, nostalgic, romantic, angry, focused, sad, happy, neutral
- **Edges** — perceptual transition costs (how jarring is this jump?)
- Modified Dijkstra finds the lowest-cost emotional path from source → target
- Track selection per segment uses pgvector cosine similarity on 42-dim embeddings

### Mood Parsing

Natural language input is handled by `mood_parser.py` via the Claude API:

```
"I'm completely burned out after work, want to relax"
        ↓ Claude (claude-haiku-4-5)
{ source: "tense", target: "peaceful" }
        ↓ Arc Planner
[ tense → focused → peaceful ] — ordered track list
```

Falls back to keyword classification if the Claude API is unavailable.

---

## ML Model

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

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Spotify Developer account — [Create app](https://developer.spotify.com/dashboard)

### 1. Clone & configure

```bash
git clone https://github.com/SuryaKiran434/flowstate.git
cd flowstate
cp .env.example .env
# Fill in SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, and ANTHROPIC_API_KEY
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
1. Pull your Spotify library (playlists, liked tracks, top artists)
2. For each track: yt-dlp → YouTube → librosa → 42-dim feature vector → PostgreSQL
3. Log metrics to MLflow

---

## Scaling Considerations

| Challenge | Solution |
|---|---|
| yt-dlp slow (5–15s/track) | Pre-compute via Airflow; serve from pgvector at query time |
| Arc generation latency | Cache common source→target paths in Redis |
| ML inference at scale | Export to ONNX, serve via Triton |
| DB reads under load | Read replicas + pgbouncer |
| YouTube blocks at scale | License audio via Musicstax/AudD for production |
| Cold start (new user) | Seed from `/me/top/artists` + personal library |
| Token expiry in Airflow | Auto-refresh via stored refresh_token before each API call |

---

## Built With

| Layer | Technology |
|---|---|
| Audio pipeline | yt-dlp, librosa, ffmpeg |
| ML | scikit-learn, PyTorch, MLflow |
| Mood parsing | Anthropic Claude API (claude-haiku-4-5) |
| Backend | FastAPI, SQLAlchemy, Alembic |
| Database | PostgreSQL 15 + pgvector |
| Cache | Redis |
| Pipeline | Apache Airflow 2.8.0 |
| Frontend | React 18, D3.js, Vite |
| Playback | Spotify Web Playback SDK |
| Auth | Spotify OAuth2 PKCE, JWT |
| Infra | Docker, Docker Compose, GitHub Actions |

---

## Roadmap

- [x] Spotify OAuth2 PKCE with auto token refresh
- [x] Personal library seeding (playlists, liked tracks, top artists)
- [x] yt-dlp + librosa audio feature pipeline (42-dim vectors)
- [x] Modified Dijkstra arc planning on 12-node emotion graph
- [x] Claude-powered natural language mood parsing
- [x] Arc generation API (`/arc/generate`, `/arc/preview`)
- [x] React frontend with OAuth flow and library stats dashboard
- [x] Docker Compose full-stack deployment
- [ ] Emotion classifier model training + evaluation (Phase 3)
- [ ] D3.js arc visualizer with real-time playback progress
- [ ] Spotify Web Playback SDK integration
- [ ] Skip-based arc re-adjustment
- [ ] CI/CD pipeline finalization

---

## Known Limitations

See [LIMITATIONS.md](LIMITATIONS.md) for a detailed analysis of current constraints and market gaps this project could address.

---

## Author

**Surya Kiran Katragadda**
- GitHub: [@SuryaKiran434](https://github.com/SuryaKiran434)
- LinkedIn: [katragadda-suryakiran](https://www.linkedin.com/in/katragadda-suryakiran/)

---

## License

MIT — see [LICENSE](LICENSE).

---

*Built with a love for music that actually understands where you are and where you want to be.*
