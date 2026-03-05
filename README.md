# 🎵 Flowstate

> *Music that moves with you.*

**Flowstate** is an emotional arc engine that curates dynamic listening sessions based on where you are emotionally and where you want to be. Instead of static mood playlists, Flowstate builds a personalized musical journey — using audio ML, graph-based path planning, and real-time Spotify playback — to guide you from your current emotional state to your target one.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18+-61DAFB?style=flat&logo=react&logoColor=white)](https://reactjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-336791?style=flat&logo=postgresql&logoColor=white)](https://postgresql.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ✨ What Makes Flowstate Different

Most music apps ask *"what mood are you in?"* and serve you a static playlist. Flowstate asks *"where are you, and where do you want to go?"* — then constructs a musical bridge between those two states using:

- **Audio ML** — emotion classification trained on 10K+ tracks using MFCCs, chroma, valence, and tempo features
- **Graph-based Arc Planning** — a modified Dijkstra algorithm that finds the smoothest emotional path between two states across a weighted emotion graph
- **Real-time Playback** — Spotify Web Playback SDK with a live D3.js arc visualizer showing your progress through the journey

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        FRONTEND (React)                      │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ Mood Input  │  │  Arc Viz     │  │  Spotify Playback  │  │
│  │ (Source →   │  │  (D3.js)     │  │  SDK Widget        │  │
│  │  Target)    │  │              │  │                    │  │
│  └──────┬──────┘  └──────────────┘  └────────────────────┘  │
└─────────┼───────────────────────────────────────────────────┘
          │ REST API
┌─────────▼───────────────────────────────────────────────────┐
│                      BACKEND (FastAPI)                       │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐  │
│  │ /arc/generate│  │ /session/*    │  │ /auth/spotify    │  │
│  │              │  │               │  │ (OAuth2 PKCE)    │  │
│  └──────┬───────┘  └───────┬───────┘  └──────────────────┘  │
│         │                  │                                  │
│  ┌──────▼──────────────────▼──────────────────────────────┐  │
│  │              Arc Planning Service                       │  │
│  │   Emotion Graph → Dijkstra → Ranked Track Sequence     │  │
│  └──────────────────────────┬───────────────────────────┘   │
│                              │                               │
│  ┌───────────────────────────▼───────────────────────────┐  │
│  │              ML Inference Service                      │  │
│  │   Audio Feature Store → Emotion Classifier → Score    │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                    DATA LAYER                                │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐  │
│  │  PostgreSQL  │  │  Redis Cache  │  │  Airflow DAGs    │  │
│  │  + pgvector  │  │  (Sessions)   │  │  (Feature Store  │  │
│  │              │  │               │  │   Enrichment)    │  │
│  └──────────────┘  └───────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 🗂️ Project Structure

```
flowstate/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       └── endpoints/
│   │   │           ├── arc.py          # Arc generation endpoints
│   │   │           ├── session.py      # Session management
│   │   │           ├── tracks.py       # Track feature endpoints
│   │   │           └── auth.py         # Spotify OAuth2 PKCE
│   │   ├── core/
│   │   │   ├── config.py               # Settings & env vars
│   │   │   └── security.py             # JWT + OAuth helpers
│   │   ├── db/
│   │   │   ├── base.py                 # SQLAlchemy base
│   │   │   └── session.py              # DB session factory
│   │   ├── models/
│   │   │   ├── track.py                # Track ORM model
│   │   │   ├── session.py              # Session ORM model
│   │   │   └── emotion.py              # Emotion node model
│   │   ├── schemas/
│   │   │   ├── arc.py                  # Arc request/response schemas
│   │   │   ├── track.py                # Track schemas
│   │   │   └── session.py              # Session schemas
│   │   ├── services/
│   │   │   ├── arc_planner.py          # Graph-based arc algorithm
│   │   │   ├── spotify_client.py       # Spotify Web API wrapper
│   │   │   └── session_manager.py      # Session state service
│   │   └── ml/
│   │       ├── emotion_classifier.py   # PyTorch emotion model
│   │       ├── feature_extractor.py    # librosa audio features
│   │       └── embeddings.py           # Track embedding store
│   ├── tests/
│   │   ├── unit/
│   │   │   ├── test_arc_planner.py
│   │   │   └── test_emotion_classifier.py
│   │   └── integration/
│   │       ├── test_arc_api.py
│   │       └── test_spotify_client.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── alembic/                        # DB migrations
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ArcVisualizer.jsx       # D3.js emotional arc
│   │   │   ├── MoodSelector.jsx        # Emotion input UI
│   │   │   ├── PlayerWidget.jsx        # Spotify playback widget
│   │   │   └── TrackCard.jsx           # Track display
│   │   ├── pages/
│   │   │   ├── Home.jsx
│   │   │   ├── Session.jsx
│   │   │   └── Callback.jsx            # Spotify OAuth callback
│   │   ├── hooks/
│   │   │   ├── useArc.js               # Arc generation hook
│   │   │   └── useSpotifyPlayer.js     # Playback SDK hook
│   │   └── utils/
│   │       ├── api.js                  # Axios API client
│   │       └── emotions.js             # Emotion constants
│   ├── package.json
│   └── Dockerfile
│
├── airflow/
│   └── dags/
│       ├── feature_enrichment_dag.py   # Daily audio feature updates
│       └── model_retrain_dag.py        # Weekly model retraining
│
├── data/
│   ├── raw/                            # Raw Spotify API pulls
│   ├── processed/                      # Feature-engineered data
│   └── models/                         # Saved PyTorch checkpoints
│
├── docs/
│   ├── PRD.md                          # Product Requirements Document
│   ├── SYSTEM_DESIGN.md                # System design doc
│   ├── API.md                          # API reference
│   └── DB_SCHEMA.md                    # Database schema
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                      # CI: lint → test → build
│   │   └── deploy.yml                  # CD: deploy on main merge
│   └── ISSUE_TEMPLATE/
│       ├── bug_report.md
│       └── feature_request.md
│
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Spotify Developer account (free) — [Create app here](https://developer.spotify.com/dashboard)
- Python 3.11+ (for local dev)
- Node.js 18+

### 1. Clone & configure

```bash
git clone https://github.com/SuryaKiran434/flowstate.git
cd flowstate
cp .env.example .env
# Fill in your Spotify Client ID and Client Secret in .env
```

### 2. Run everything

```bash
docker-compose up --build
```

That's it. Services will be available at:

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| Airflow UI | http://localhost:8080 |

### 3. Local development (without Docker)

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

---

## 🧠 How the Arc Algorithm Works

Flowstate models emotional space as a **weighted directed graph** where:

- **Nodes** = 12 emotion states (energetic, peaceful, melancholic, euphoric, tense, nostalgic, romantic, angry, focused, sad, happy, neutral)
- **Edges** = allowed transitions weighted by perceptual distance (how jarring is this jump?)
- **Track scores** = each track in the feature store is assigned a primary emotion + confidence

Given a source emotion `S` and target emotion `T` and a desired duration `D`:

1. **Path Planning** — Run modified Dijkstra on the emotion graph to find the lowest-perceptual-cost path from `S` to `T`
2. **Track Selection** — For each emotion node along the path, query pgvector for the top-k tracks closest to that node's centroid
3. **Sequencing** — Order tracks within each node segment by ascending/descending energy to ensure smooth transitions
4. **Output** — A ranked list of tracks with transition metadata

```python
# Simplified example
arc = ArcPlanner()
session = arc.generate(
    source_emotion="tense",
    target_emotion="peaceful",
    duration_minutes=45,
    track_pool=user_library_ids
)
# Returns: [track_1, track_2, ..., track_n] with emotion labels per segment
```

---

## 🤖 ML Model

The emotion classifier is a lightweight feedforward neural network trained on audio features:

| Feature | Description |
|---|---|
| MFCCs (13) | Timbral texture |
| Chroma (12) | Harmonic/pitch content |
| Spectral Centroid | Brightness |
| Tempo (BPM) | Energy proxy |
| Valence* | Positivity (from Spotify API) |
| Energy* | Intensity (from Spotify API) |

*\*Sourced from Spotify Audio Features API (free)*

**Training data:** Spotify Audio Features for ~10,000 tracks across genres, labeled using a combination of Spotify's valence/energy dimensions and manual annotation.

**Evaluation:** Held-out test set, reporting precision, recall, F1 per class. Experiments tracked with MLflow.

---

## 📡 API Reference

### Core Endpoints

```
POST   /api/v1/arc/generate          Generate an emotional arc session
GET    /api/v1/arc/{arc_id}          Retrieve a generated arc
POST   /api/v1/session/start         Start a playback session
PUT    /api/v1/session/{id}/progress Update session progress
GET    /api/v1/tracks/{id}/features  Get audio features for a track
GET    /api/v1/auth/spotify/login    Initiate Spotify OAuth2 PKCE
GET    /api/v1/auth/spotify/callback Handle OAuth callback
```

Full interactive docs at `/docs` (Swagger UI) when running locally.

---

## 🗄️ Database Schema

### Core Tables

```sql
tracks          -- Track metadata + Spotify IDs
track_features  -- Audio features (MFCCs, chroma, tempo, valence, energy)
track_emotions  -- ML-predicted emotion labels + confidence scores
emotion_nodes   -- Emotion graph nodes with centroid feature vectors
emotion_edges   -- Directed transitions with perceptual distance weights
sessions        -- User listening sessions
session_tracks  -- Ordered track list per session with emotion labels
users           -- Spotify user profiles (OAuth)
```

---

## 🔄 Data Pipeline (Airflow)

Two scheduled DAGs:

**`feature_enrichment_dag`** — runs daily
1. Pull new tracks from Spotify (saved tracks, followed playlists)
2. Fetch audio features via Spotify Audio Features API
3. Download 30s preview clips
4. Extract librosa features
5. Run inference → store emotion labels
6. Update pgvector embeddings

**`model_retrain_dag`** — runs weekly
1. Pull newly labeled tracks from feature store
2. Retrain emotion classifier
3. Evaluate on held-out test set
4. Promote if F1 improvement > threshold
5. Log to MLflow

---

## 🧪 Testing

```bash
# Unit tests
cd backend && pytest tests/unit -v --cov=app --cov-report=html

# Integration tests (requires running DB)
pytest tests/integration -v

# Load testing
cd backend && locust -f tests/load/locustfile.py
```

Target: **80%+ coverage** on core services.

---

## 📊 How I'd Scale This to 1M Users

| Challenge | Solution |
|---|---|
| Audio feature extraction is slow | Pre-compute offline via Airflow, serve from pgvector |
| Arc generation latency | Cache common source→target paths in Redis |
| ML inference at scale | Export to ONNX, serve via Triton Inference Server |
| DB reads under load | Read replicas + pgbouncer connection pooling |
| Feature store growth | Partition `track_features` by ingest date |
| Cold start (new user, no library) | Fall back to genre-based emotion graph seeding |

---

## 🛠️ Built With

| Layer | Technology |
|---|---|
| Audio ML | PyTorch, librosa, essentia |
| Backend | FastAPI, SQLAlchemy, Alembic |
| Database | PostgreSQL 15 + pgvector |
| Cache | Redis |
| Data Pipeline | Apache Airflow |
| Experiment Tracking | MLflow |
| Frontend | React 18, D3.js, Tailwind CSS |
| Playback | Spotify Web Playback SDK |
| Auth | Spotify OAuth2 PKCE |
| Containerization | Docker, Docker Compose |
| CI/CD | GitHub Actions |
| Deployment | Vercel (frontend), Fly.io (backend) |

---

## 📋 SDLC Artifacts

All project documentation lives in `/docs`:

- [`PRD.md`](docs/PRD.md) — Product Requirements Document
- [`SYSTEM_DESIGN.md`](docs/SYSTEM_DESIGN.md) — System design with diagrams
- [`API.md`](docs/API.md) — Full API specification
- [`DB_SCHEMA.md`](docs/DB_SCHEMA.md) — Database schema with ERD

---

## 🗺️ Roadmap

- [x] Project scaffold & architecture
- [ ] Spotify OAuth2 PKCE integration
- [ ] Audio feature extraction pipeline
- [ ] Emotion classifier (v1)
- [ ] Arc planning algorithm
- [ ] FastAPI backend (core endpoints)
- [ ] React frontend + D3.js arc visualizer
- [ ] Airflow DAGs
- [ ] Docker Compose setup
- [ ] CI/CD pipeline
- [ ] Load testing
- [ ] Public beta

---

## 👤 Author

**Surya Kiran Katragadda**
- GitHub: [@SuryaKiran434](https://github.com/SuryaKiran434)
- LinkedIn: [katragadda-suryakiran](https://www.linkedin.com/in/katragadda-suryakiran/)
- Instagram: [@surya_katragadda](https://www.instagram.com/surya_katragadda/)

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

*Built with 100k minutes of listening experience and a love for music that actually understands you.*
