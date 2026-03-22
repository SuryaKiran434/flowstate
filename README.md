# Flowstate

> *Music that moves with you.*

**Flowstate** is an emotional arc engine that curates dynamic listening sessions based on where you are emotionally and where you want to be. Instead of static mood playlists, Flowstate asks *"where are you, and where do you want to go?"* — then builds a musical bridge using audio ML, graph-based path planning, Claude-powered mood parsing, real-time Spotify playback, and a full suite of adaptive and social features built on top.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18+-61DAFB?style=flat&logo=react&logoColor=white)](https://reactjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-336791?style=flat&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Tests](https://img.shields.io/badge/tests-428%20passing-brightgreen)](backend/tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What Makes Flowstate Different

- **Custom Audio ML Pipeline** — 42-dimensional librosa feature vectors (MFCCs, chroma, spectral centroid, tempo, RMS, ZCR) extracted via yt-dlp. Language-agnostic by design — classifies Telugu, Tamil, Hindi, Korean, and English equally, because it operates on raw audio, not lyrics or metadata.
- **Graph-based Arc Planning** — Modified Dijkstra on a 12-node emotion graph finds the smoothest perceptual path between any two emotional states.
- **Personalised Emotion Graph** — Edge weights adapt per-user from skip and completion signals. Your "tense → peaceful" transition is not the same as anyone else's.
- **Claude-powered Mood Parsing** — Natural language like *"I'm burned out and want to decompress"* is parsed into structured source/target emotion pairs, with keyword fallback.
- **Real-time Adaptive Playback** — Skip a few tracks and the arc re-plans from your current emotional position. Issue a natural language command mid-session ("more melancholic") and Claude re-routes the remaining arc.
- **Longitudinal Emotional Intelligence** — Tracks patterns across sessions: your streak, which emotions you start with at different times of day, which arc pairs you complete vs. abandon. Seeds future arcs without you having to describe anything.
- **Social Arc Sessions** — Multiple users contribute their current emotional state; a graph centroid algorithm finds the most musically central starting point and plans toward a shared destination.
- **Multi-language Aware** — Detects 11 language scripts via Unicode analysis, displays your library's language distribution, and lets you filter arcs to specific languages while preserving emotional coherence.

> **Why yt-dlp instead of Spotify Audio Features?** Spotify deprecated `/audio-features` for new apps in 2025 (requires 250k MAU for access). Flowstate's yt-dlp + librosa pipeline sources audio from YouTube — global coverage, all languages, on-demand extraction.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React 18)                          │
│  Landing · MoodInput · ArcResult · Discover · Collaborate · Insights │
│  D3.js Arc Visualizer · Spotify Web Playback SDK · Constellation BG  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ REST API
┌───────────────────────────────▼─────────────────────────────────────┐
│                          BACKEND (FastAPI)                            │
│                                                                       │
│  /auth/*          Spotify OAuth2 PKCE + JWT                          │
│  /tracks/*        Library stats, emotions, readiness, language       │
│  /arc/*           Generate, replan, adjust, suggest, insights        │
│  /sessions/*      Session lifecycle + skip/play telemetry            │
│  /templates/*     Arc template publish, browse, remix                │
│  /collab/*        Multi-user collaborative arc sessions              │
│                                                                       │
│  MoodParser       Claude API → (source, target) emotion pairs        │
│  ArcPlanner       Dijkstra on 12-node personalised emotion graph     │
│  ContextSeeder    Time + history → zero-input arc suggestion         │
│  GraphLearner     Skip/completion signals → per-user edge weights    │
│  LongitudinalAnalyzer  Session history → streak, patterns, slots     │
│  EmotionClassifier     RandomForest on 42-dim librosa features       │
│  ReclassifyService     Batch ML reclassification of user library     │
│  CollabArcService      Group emotion aggregation via graph centroid  │
│  LanguageDetector      Unicode script → language code (11 scripts)  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│                           DATA LAYER                                  │
│   PostgreSQL 15   │   Redis (PKCE state, TTL)   │   MLflow           │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│                  AIRFLOW PIPELINE  (Daily 2AM UTC)                    │
│   Spotify Library → yt-dlp → librosa → feature store → classifier   │
└─────────────────────────────────────────────────────────────────────┘
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
   ├── MFCCs (13 mean + 13 std)   — timbral texture        [26 dims]
   ├── Chroma mean (12)           — harmonic/pitch content  [12 dims]
   ├── Spectral centroid          — brightness              [ 1 dim ]
   ├── Zero crossing rate         — noisiness               [ 1 dim ]
   ├── RMS energy                 — loudness proxy          [ 1 dim ]
   └── Tempo (BPM)                — energy indicator        [ 1 dim ]
         │                           Total: 42 dimensions
         ▼
PostgreSQL track_features → RandomForest Classifier → Arc Planner
```

---

## Project Structure

```
flowstate/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/
│   │   │   ├── auth.py              # Spotify OAuth2 PKCE + JWT
│   │   │   ├── tracks.py            # Library, stats, emotions, language-stats,
│   │   │   │                        #   model-status, reclassify
│   │   │   ├── arc.py               # generate, replan, adjust, suggest,
│   │   │   │                        #   user-graph, preview, emotions, insights
│   │   │   ├── sessions.py          # Session lifecycle + skip/play telemetry
│   │   │   ├── templates.py         # Arc template publish, list, remix
│   │   │   └── collab.py            # Collaborative arc sessions
│   │   ├── core/
│   │   │   ├── config.py            # Pydantic Settings (Spotify, DB, Claude, Redis)
│   │   │   └── security.py          # JWT token management
│   │   ├── models/
│   │   │   ├── user.py              # User ORM
│   │   │   ├── track.py             # Track, TrackFeature, UserTrack ORM
│   │   │   ├── session.py           # Session, SessionTrack ORM
│   │   │   ├── arc_template.py      # ArcTemplate ORM
│   │   │   └── collab.py            # CollabSession, CollabParticipant ORM
│   │   └── services/
│   │       ├── arc_planner.py       # Dijkstra arc algorithm + language filter
│   │       ├── mood_parser.py       # Claude mood parsing + keyword fallback
│   │       ├── context_seeder.py    # Zero-input arc suggestion (time + history)
│   │       ├── graph_learner.py     # Per-user emotion graph weight learning
│   │       ├── longitudinal_analyzer.py  # Session history patterns + time slots
│   │       ├── emotion_classifier.py     # RandomForest on 42-dim features
│   │       ├── reclassify_service.py     # Batch ML reclassification
│   │       ├── library_seeder.py         # Auto-seed on first login
│   │       ├── collab_service.py         # Group emotion aggregation (centroid)
│   │       ├── language_detector.py      # Unicode script → language code
│   │       └── spotify_client.py         # Spotify API wrapper
│   ├── tests/unit/                  # 428 tests across 18 test files
│   │   ├── test_arc_planner.py
│   │   ├── test_mood_parser.py
│   │   ├── test_arc_replan.py
│   │   ├── test_arc_adjust.py
│   │   ├── test_auth_pkce.py
│   │   ├── test_auth_spotify_token.py
│   │   ├── test_tracks_readiness.py
│   │   ├── test_library_seeder.py
│   │   ├── test_emotion_classifier.py
│   │   ├── test_sessions.py
│   │   ├── test_context_seeder.py
│   │   ├── test_graph_learner.py
│   │   ├── test_templates.py
│   │   ├── test_reclassify_service.py
│   │   ├── test_longitudinal_analyzer.py
│   │   ├── test_collab_service.py
│   │   └── test_language_detector.py
│   └── Dockerfile
│
├── airflow/dags/
│   ├── feature_enrichment_dag.py    # Spotify → yt-dlp → librosa → DB (daily)
│   └── backfill_empty_tracks.py     # Backfill missing metadata from Spotify
│
├── frontend/
│   └── src/
│       ├── App.jsx                  # Router + PrivateRoute guard
│       ├── pages/
│       │   ├── Home.jsx             # Landing page + OAuth entry point
│       │   ├── Dashboard.jsx        # All screens: Landing, MoodInput, Loading,
│       │   │                        #   ArcResult, Discover, Collab
│       │   └── Callback.jsx         # Spotify OAuth redirect handler
│       └── components/
│           ├── ArcVisualizer.jsx    # D3.js energy chart + emotion-driven fill
│           └── SpotifyPlayer.jsx    # Spotify Web Playback SDK wrapper
│
├── docs/
│   ├── PRD.md
│   ├── DB_SCHEMA.md
│   └── AUDIO_PIPELINE.md
│
├── LIMITATIONS.md                   # Constraints + market gaps analysis
├── docker-compose.yml               # Full 7-service stack
├── .env.example
└── flowstate.sh
```

---

## Database Schema (10 Tables)

| Table | Purpose |
|---|---|
| `users` | Spotify profile + OAuth access/refresh tokens |
| `tracks` | Track metadata (Spotify ID, artist, album, duration, popularity) |
| `track_features` | 42-dim librosa feature vectors + ML-predicted emotion label + confidence |
| `sessions` | User listening sessions — source emotion, target emotion, arc path, status |
| `session_tracks` | Ordered tracks within a session with played/skipped/position telemetry |
| `user_graph_weights` | Per-user personalised emotion graph edge weights learned from skip/play signals |
| `arc_templates` | Serialised arc skeletons (source, path, target, duration) — shareable and remixable |
| `collab_sessions` | Multi-user arc sessions with invite codes and generated arc JSON cache |
| `collab_participants` | Per-user source emotion contributions to a collab session |
| `user_graph_weights` | Learned edge weight deltas from skip/completion signals per user |

---

## API Reference

### Auth
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/auth/login` | Initiate Spotify PKCE OAuth flow |
| `GET` | `/auth/callback` | Handle Spotify redirect + issue JWT |
| `GET` | `/auth/me` | Current user profile |
| `GET` | `/auth/spotify-token` | Retrieve Spotify access token for Web Playback SDK |

### Tracks
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/tracks` | Paginated user library with features |
| `GET` | `/tracks/stats` | Library counts: total, analysed, with emotions |
| `GET` | `/tracks/emotions` | Emotion distribution across library |
| `GET` | `/tracks/readiness` | Library processing state (empty / processing / ready) |
| `GET` | `/tracks/language-stats` | Language distribution (Unicode script detection) |
| `GET` | `/tracks/model-status` | ML classifier status, F1 score, training metadata |
| `POST` | `/tracks/reclassify` | Apply trained classifier to entire user library |
| `GET` | `/tracks/by-emotion/{emotion}` | Tracks filtered by emotion label |
| `GET` | `/tracks/arc-pool` | All classified tracks for arc planning (single query) |

### Arc
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/arc/generate` | Natural language mood → full arc (with optional language filter) |
| `POST` | `/arc/replan` | Skip-driven mid-session re-plan from current emotional position |
| `POST` | `/arc/adjust` | Natural language mid-session arc adjustment via Claude |
| `GET` | `/arc/suggest` | Context-aware zero-input arc suggestion (time + history) |
| `GET` | `/arc/insights` | Longitudinal patterns: streak, top emotions, arc pairs, time slots |
| `GET` | `/arc/user-graph` | Diagnostic: personalised vs. global edge weight deltas |
| `POST` | `/arc/preview` | Fast path-only arc preview (no track selection) |
| `GET` | `/arc/emotions` | All 12 valid emotion labels with descriptions and energy centres |

### Sessions
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/sessions` | Create session record from generated arc |
| `PATCH` | `/sessions/{id}` | Update session status (active / completed / abandoned) |
| `POST` | `/sessions/{id}/events` | Record track play/skip events |

### Templates
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/templates` | Publish arc as shareable template |
| `GET` | `/templates` | Browse templates (paginated, filterable by source/target) |
| `GET` | `/templates/{id}` | Single template |
| `POST` | `/templates/{id}/remix` | Apply template path to your own library |

### Collab
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/collab/sessions` | Create collaborative session with target emotion + invite code |
| `POST` | `/collab/sessions/{code}/join` | Join session with your source emotion |
| `GET` | `/collab/sessions/{code}` | Session state + all participants |
| `POST` | `/collab/sessions/{code}/arc` | Host triggers group arc generation (centroid aggregation) |

---

## Arc Algorithm

Emotion space modelled as a **weighted directed graph**:
- **Nodes** — 12 states: energetic, peaceful, melancholic, euphoric, tense, nostalgic, romantic, angry, focused, sad, happy, neutral
- **Edges** — perceptual transition costs (how jarring is this emotional jump?)
- **Modified Dijkstra** finds the lowest-cost emotional path from source → target
- **Per-user personalisation** — `GraphLearner` adjusts edge weights from skip/completion history; minimum 5 signals required before activating

### Collaborative Aggregation

When N users join a collab session each with a different source emotion:
1. Run Dijkstra from every unique source emotion
2. For each candidate emotion, sum shortest-path distances from all participants
3. The **graph centroid** — the candidate with the lowest total distance — becomes the shared arc source
4. Plan from centroid → shared target using the host's library

### Mood Parsing

```
"I'm burned out and want to decompress"
        ↓ Claude (claude-haiku-4-5)
{ source: "tense", target: "peaceful" }
        ↓ Arc Planner (+ optional language_filter)
[ tense → focused → neutral → peaceful ] — ordered track list
```

Falls back to keyword classification if Claude API is unavailable.

---

## ML Model

`RandomForestClassifier` trained on 42-dimensional librosa features via `train_classifier.py`, tracked in MLflow.

| Feature Group | Dims | What It Captures |
|---|---|---|
| MFCC mean + std | 26 | Timbral texture and dynamics |
| Chroma mean | 12 | Harmonic / pitch class content |
| Spectral centroid | 1 | Brightness |
| Zero crossing rate | 1 | Percussiveness / noisiness |
| RMS energy | 1 | Loudness |
| Tempo (BPM) | 1 | Energy |

The classifier operates entirely on acoustic properties — it is **language-agnostic by construction**. A Telugu film track and an English pop track with similar acoustic profiles receive the same emotion label. Once trained (`python train_classifier.py`), the `/tracks/reclassify` endpoint applies it to your library in a single bulk UPDATE.

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Spotify Developer account — [Create app](https://developer.spotify.com/dashboard)
- Anthropic API key — [Get key](https://console.anthropic.com)
- Redis (included in docker-compose)

### 1. Clone & configure

```bash
git clone https://github.com/SuryaKiran434/flowstate.git
cd flowstate
cp .env.example .env
# Fill in: SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, ANTHROPIC_API_KEY, SECRET_KEY
```

### 2. Start the stack

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

### 3. First login

Navigate to http://localhost:3000 and log in with Spotify. The backend automatically seeds your library and begins feature extraction. A readiness indicator shows processing progress — arcs become available once at least one track is classified.

### 4. Seed the feature store (full pipeline)

```bash
docker exec flowstate_airflow airflow dags trigger feature_enrichment
```

The DAG:
1. Pulls your Spotify library (playlists, liked tracks, top artists)
2. For each track: yt-dlp → YouTube → librosa → 42-dim feature vector → PostgreSQL
3. Logs metrics to MLflow

### 5. Train the emotion classifier

```bash
cd backend && python train_classifier.py
```

Then click **Reclassify library** in the dashboard to apply the trained model to your tracks.

---

## Test Suite

```bash
cd backend && python -m pytest tests/ -v
```

428 tests across 18 test files. All pass. Coverage spans every service, endpoint function, and integration path.

| Test File | Coverage |
|---|---|
| `test_arc_planner.py` | Dijkstra, track selection, language filter |
| `test_mood_parser.py` | Claude parsing, keyword fallback |
| `test_arc_replan.py` | Skip detection, re-plan source resolution |
| `test_arc_adjust.py` | NL command parsing, mid-session adjustment |
| `test_auth_pkce.py` | PKCE state store (Redis), callback validation |
| `test_auth_spotify_token.py` | Token exchange and refresh |
| `test_tracks_readiness.py` | Library state transitions |
| `test_library_seeder.py` | Auto-seed on first login |
| `test_emotion_classifier.py` | Feature extraction, train, predict_batch |
| `test_sessions.py` | Session lifecycle, telemetry events |
| `test_context_seeder.py` | Time-of-day seeding, history signals |
| `test_graph_learner.py` | Edge weight learning, personalisation threshold |
| `test_templates.py` | Publish, browse, remix arc templates |
| `test_reclassify_service.py` | Bulk reclassification, model-not-available path |
| `test_longitudinal_analyzer.py` | Streak, top emotions, time-slot patterns |
| `test_collab_service.py` | Session creation, join, centroid aggregation |
| `test_language_detector.py` | Unicode script detection, batch, endpoint |

---

## Scaling Considerations

| Challenge | Solution |
|---|---|
| yt-dlp slow (5–15s/track) | Pre-compute via Airflow; serve from DB at query time |
| Arc generation latency | Cache common source→target paths in Redis |
| ML inference at scale | Export to ONNX, serve via Triton |
| DB reads under load | Read replicas + pgbouncer |
| YouTube blocks at scale | License audio via Musicstax/AudD for production |
| Cold start (new user) | Auto-seed from `/me/top/artists` on first login + readiness guard |
| Token expiry in Airflow | Auto-refresh via stored refresh_token before each API call |
| PKCE state in multi-process | Redis with TTL (replaces prior in-memory dict) |

---

## Built With

| Layer | Technology |
|---|---|
| Audio pipeline | yt-dlp, librosa, ffmpeg |
| ML | scikit-learn, MLflow, joblib |
| Mood parsing | Anthropic Claude API (claude-haiku-4-5) |
| Backend | FastAPI, SQLAlchemy, Pydantic v2 |
| Database | PostgreSQL 15 |
| Cache / state | Redis |
| Pipeline | Apache Airflow 2.8.0 |
| Frontend | React 18, D3.js v7, Vite |
| Playback | Spotify Web Playback SDK |
| Auth | Spotify OAuth2 PKCE, JWT |
| Infra | Docker, Docker Compose |

---

## Roadmap

- [x] Spotify OAuth2 PKCE with Redis state store + auto token refresh
- [x] Personal library seeding (playlists, liked tracks, top artists)
- [x] yt-dlp + librosa audio feature pipeline (42-dim vectors)
- [x] Modified Dijkstra arc planning on 12-node emotion graph
- [x] Claude-powered natural language mood parsing + keyword fallback
- [x] Arc generation API (`/arc/generate`, `/arc/preview`)
- [x] React frontend with OAuth flow and library stats dashboard
- [x] Docker Compose full-stack deployment
- [x] 428-test suite (arc planner, mood parser, auth, sessions, classifier)
- [x] Supervised emotion classifier — RandomForest + MLflow tracking
- [x] Spotify Web Playback SDK — in-app playback with session control
- [x] D3.js arc visualizer — animated energy chart, emotion-driven colour fill
- [x] Session telemetry — lifecycle tracking, skip/play events
- [x] Skip-driven arc re-planning from current emotional position
- [x] Mid-session natural language arc adjustment via Claude
- [x] Context-aware zero-input arc suggestion (time + session history)
- [x] Personalised emotion graph — per-user edge weight learning
- [x] Arc sharing and remix — shareable emotional skeleton templates
- [x] Audio-visual emotional sync — page aura, constellation colour, chart fill
- [x] Emotion classifier integration — reclassify API + model status endpoint
- [x] Emotional memory — longitudinal listening patterns, streak, time-slot learning
- [x] Collaborative arc sessions — group emotion centroid aggregation
- [x] Multi-language emotional intelligence — Unicode script detection + arc filtering

---

## Known Limitations

See [LIMITATIONS.md](LIMITATIONS.md) for a detailed analysis of current constraints and future directions.

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
