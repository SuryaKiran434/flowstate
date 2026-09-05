# Flowstate

> *Music that moves with you.*

**Flowstate** is an emotional arc engine that curates dynamic listening sessions based on where you are emotionally and where you want to be. Instead of static mood playlists, Flowstate asks *"where are you, and where do you want to go?"* — then builds a musical bridge using audio ML, graph-based path planning, Claude-powered mood parsing, real-time Spotify playback, and a full suite of adaptive and social features built on top.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104.1-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat&logo=react&logoColor=white)](https://reactjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%20(pgvector)-336791?style=flat&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Tests](https://img.shields.io/badge/tests-568%20passing-brightgreen)](backend/tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## What Makes Flowstate Different

- **Custom Audio ML Pipeline** — 42-dimensional librosa feature vectors (MFCCs, chroma, spectral centroid, tempo, RMS, ZCR) extracted via yt-dlp. Language-agnostic by design — classifies Telugu, Tamil, Hindi, Korean, and English equally, because it operates on raw audio, not lyrics or metadata.
- **Graph-based Arc Planning** — Shortest-path planning over a 12-node emotion graph finds the smoothest perceptual route between any two emotional states. Paths are read out of a cached Floyd–Warshall all-pairs table rather than recomputed per request (see [Arc Algorithm](#arc-algorithm)).
- **Personalised Emotion Graph** — Edge weights adapt per-user from skip and completion signals. Your "tense → peaceful" transition is not the same as anyone else's.
- **Claude-powered Mood Parsing** — Natural language like *"I'm burned out and want to decompress"* is parsed into structured source/target emotion pairs, with keyword fallback.
- **Real-time Adaptive Playback** — Skip a few tracks and the arc re-plans from your current emotional position. Issue a natural language command mid-session ("more melancholic") and Claude re-routes the remaining arc.
- **Longitudinal Emotional Intelligence** — Tracks patterns across sessions: your streak, which emotions you start with at different times of day, which arc pairs you complete vs. abandon. Seeds future arcs without you having to describe anything.
- **Social Arc Sessions** — Multiple users contribute their current emotional state; a graph centroid algorithm finds the most musically central starting point and plans toward a shared destination.
- **Multi-language Aware** — Detects 11 non-Latin languages across 12 Unicode script blocks (plus an English/Latin default), displays your library's language distribution, and lets you filter arcs to specific languages while preserving emotional coherence.

> **Why yt-dlp instead of Spotify Audio Features?** Spotify deprecated `/audio-features` for new apps in 2025 (requires 250k MAU for access). Flowstate's yt-dlp + librosa pipeline sources audio from YouTube — global coverage, all languages, on-demand extraction.

---

## Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React 18 · Vite · :3000)                 │
│                                                                           │
│  Routes    /  Home (OAuth entry)   /callback  Callback   /dashboard       │
│  Screens   landing · input · loading · result · discover · collab         │
│            (the Insights panel renders inside the landing screen)         │
│  Widgets   ArcVisualizer (D3 v7) · SpotifyPlayer (Web Playback SDK)       │
│            ConstellationBg (emotion-driven canvas background)             │
└─────────────────────────────────┬─────────────────────────────────────────┘
                                  │ REST — all routes under /api/v1
┌─────────────────────────────────▼─────────────────────────────────────────┐
│                       BACKEND (FastAPI · uvicorn · :8000)                 │
│                                                                           │
│  Routers (backend/app/api/v1/endpoints/)                                  │
│    auth.py       Spotify OAuth2 PKCE + JWT issue/refresh                  │
│    tracks.py     Library, stats, emotions, readiness, language, model     │
│    arc.py        generate · replan · adjust · suggest · preview ·         │
│                  user-graph · emotions · insights                         │
│    sessions.py   Session lifecycle + skip/play telemetry                  │
│    templates.py  Arc template publish, browse, remix                      │
│    collab.py     Multi-user collaborative arc sessions                    │
│                                                                           │
│  Services (backend/app/services/)                                         │
│    MoodParser           Claude API → (source, target) emotion pairs       │
│    ArcPlanner           Cached Floyd–Warshall APSP over the 12-node       │
│                         (optionally personalised) emotion graph           │
│    GraphLearner         Skip/completion telemetry → per-user edge weights │
│    ContextSeeder        Time + history → zero-input arc suggestion        │
│    LongitudinalAnalyzer Session history → streak, patterns, time slots    │
│    EmotionClassifier    StandardScaler → RandomForest on 42-dim features  │
│    ReclassifyService    Batch ML reclassification of a user's library     │
│    CollabArcService     Group emotion aggregation via graph centroid      │
│    LanguageDetector     Unicode script → language code (memoised)         │
│    LibrarySeeder        Auto-seed the library on first login              │
│    SpotifyClient        Spotify Web API wrapper + token refresh           │
└─────────────────────────────────┬─────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼─────────────────────────────────────────┐
│                               DATA LAYER                                  │
│  PostgreSQL 15 + pgvector :5432  │  Redis 7 :6379     │  MLflow :5001     │
│  9 tables, created on startup    │  PKCE state, TTL   │  training runs    │
└─────────────────────────────────┬─────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼─────────────────────────────────────────┐
│             AIRFLOW 2.11.2 PIPELINE  (:8080 · daily 02:00 UTC)            │
│  feature_enrichment DAG:                                                  │
│     Spotify library → yt-dlp → librosa → track_features → classifier      │
│  backfill_empty_tracks.py: standalone metadata repair script              │
└───────────────────────────────────────────────────────────────────────────┘
```

### Data flow, end to end

1. **Spotify library** — after OAuth, `LibrarySeeder` pulls the user's playlists, liked tracks, and top artists into `tracks` / `user_tracks`.
2. **yt-dlp** — the `feature_enrichment` DAG searches YouTube for each track and downloads a short audio clip (Spotify's `/audio-features` is unavailable to new apps).
3. **librosa features** — the clip is decoded with ffmpeg and reduced to a 42-dimensional vector (MFCC mean/std, chroma mean, spectral centroid, ZCR, RMS, tempo), written to `track_features`.
4. **Classifier** — `EmotionClassifier` (StandardScaler → RandomForest, trained by `backend/scripts/train_classifier.py`, tracked in MLflow) labels each vector with an emotion and a confidence.
5. **Emotion graph** — the 12 emotion labels form a weighted directed graph. `GraphLearner` reads skip/completion telemetry out of `session_tracks` and rescales that user's edge weights once they have at least 5 signals.
6. **Arc planning** — `ArcPlanner` resolves source → target from a cached all-pairs shortest-path table over that graph, allocates tracks per path segment from the classified pool, and orders each segment by energy gradient.
7. **Playback** — the arc is persisted as a `session`, rendered by the D3 arc visualizer, and played through the Spotify Web Playback SDK. Play/skip events flow back to `/sessions/{id}/events`, which feeds step 5 for the next arc.

---

## Audio Feature Pipeline

```
Spotify Personal Library → track metadata
         │
         ▼
yt-dlp → YouTube search → short audio clip
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
│   │   ├── main.py                  # FastAPI app, CORS, create_all, /api/v1/health
│   │   ├── api/v1/
│   │   │   ├── router.py            # Mounts every router under /api/v1
│   │   │   └── endpoints/
│   │   │       ├── auth.py          # Spotify OAuth2 PKCE + JWT
│   │   │       ├── tracks.py        # Library, stats, emotions, readiness,
│   │   │       │                    #   arc-pool, language-stats, model-status,
│   │   │       │                    #   reclassify
│   │   │       ├── arc.py           # generate, replan, adjust, suggest,
│   │   │       │                    #   user-graph, preview, emotions, insights
│   │   │       ├── sessions.py      # Session lifecycle + skip/play telemetry
│   │   │       ├── templates.py     # Arc template publish, list, remix
│   │   │       └── collab.py        # Collaborative arc sessions
│   │   ├── core/
│   │   │   ├── config.py            # Pydantic Settings (Spotify, DB, Claude, Redis)
│   │   │   ├── log_sanitize.py      # Control-character stripping + truncation for logs
│   │   │   └── security.py          # JWT + PKCE helpers
│   │   ├── db/session.py            # Engine, SessionLocal, declarative Base
│   │   ├── models/
│   │   │   ├── user.py              # User ORM
│   │   │   ├── track.py             # Track, TrackFeature, UserTrack ORM
│   │   │   ├── session.py           # Session, SessionTrack ORM
│   │   │   ├── arc_template.py      # ArcTemplate ORM
│   │   │   └── collab.py            # CollabSession, CollabParticipant ORM
│   │   └── services/
│   │       ├── arc_planner.py       # Emotion graph, cached APSP, track selection
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
│   ├── scripts/train_classifier.py  # Trains + saves the model, logs to MLflow
│   ├── models/                      # Trained artefacts (gitignored, .gitkeep only)
│   ├── tests/unit/                  # 20 test files — see Test Suite below
│   ├── pytest.ini
│   ├── requirements.txt
│   └── Dockerfile
│
├── airflow/
│   ├── dags/
│   │   ├── feature_enrichment_dag.py    # Spotify → yt-dlp → librosa → DB (daily)
│   │   └── backfill_empty_tracks.py     # Backfill missing metadata from Spotify
│   └── Dockerfile                       # airflow:2.11.2 + ffmpeg/librosa/yt-dlp
│
├── frontend/
│   ├── src/
│   │   ├── main.jsx                 # Vite entry
│   │   ├── App.jsx                  # Router + PrivateRoute guard
│   │   ├── pages/
│   │   │   ├── Home.jsx             # Landing page + OAuth entry point
│   │   │   ├── Dashboard.jsx        # All screens: landing, input, loading,
│   │   │   │                        #   result, discover, collab (+ Insights)
│   │   │   └── Callback.jsx         # Spotify OAuth redirect handler
│   │   └── components/
│   │       ├── ArcVisualizer.jsx    # D3.js energy chart + emotion-driven fill
│   │       └── SpotifyPlayer.jsx    # Spotify Web Playback SDK wrapper
│   ├── vite.config.js
│   ├── package.json
│   └── Dockerfile
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                   # Backend · Frontend · SonarCloud · Docker Build
│   │   ├── dependabot-auto-merge.yml  # Queues grouped minor/patch bumps to merge
│   │   └── slack-notify.yml         # Push notification to a Slack webhook
│   ├── dependabot.yml               # Weekly grouped pip / npm / docker / actions
│   └── ISSUE_TEMPLATE/              # Bug report + feature request forms
│
├── docker/
│   └── postgres/initdb/
│       └── 01-create-airflow-db.sh  # Creates the `airflow` DB on first init
│
├── docs/
│   ├── PRD.md
│   ├── DB_SCHEMA.md
│   └── AUDIO_PIPELINE.md
│
├── LIMITATIONS.md                   # Constraints + market gaps analysis
├── sonar-project.properties         # SonarCloud sources, coverage report paths
├── docker-compose.yml               # 6-service stack (db, redis, backend,
│                                    #   frontend, airflow, mlflow)
├── .env.example
└── flowstate.sh                     # One-command dev environment wrapper
```

---

## Database Schema (9 Tables)

Tables are created from the SQLAlchemy models by `Base.metadata.create_all()` on backend startup — there are no Alembic migrations to run.

| Table | Purpose |
|---|---|
| `users` | Spotify profile + OAuth access/refresh tokens |
| `tracks` | Track metadata (Spotify ID, artist, album, duration, popularity) |
| `track_features` | 42-dim librosa feature vectors + ML-predicted emotion label + confidence |
| `user_tracks` | Join table — which tracks belong to which user's library, and how they got there |
| `sessions` | User listening sessions — source emotion, target emotion, arc path, status |
| `session_tracks` | Ordered tracks within a session with played/skipped/position telemetry |
| `arc_templates` | Serialised arc skeletons (source, path, target, duration) — shareable and remixable |
| `collab_sessions` | Multi-user arc sessions with invite codes and generated arc JSON cache |
| `collab_participants` | Per-user source emotion contributions to a collab session |

> Personalised edge weights are **not** stored in a table. `GraphLearner` is stateless: it derives each user's weights on demand from consecutive-track play/skip pairs in `session_tracks`.

---

## API Reference

Every route below is mounted under the `/api/v1` prefix — e.g. `GET /api/v1/arc/emotions`. Interactive docs live at `/docs` (Swagger) and `/redoc`.

### Health
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Liveness probe — `{"status": "ok"}` |

### Auth
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/auth/spotify/login` | Initiate Spotify PKCE OAuth flow (returns `auth_url`) |
| `GET` | `/auth/spotify/callback` | Handle Spotify redirect + issue JWT |
| `GET` | `/auth/spotify-token` | Retrieve Spotify access token for Web Playback SDK |
| `GET` | `/auth/me` | Current user profile |

### Tracks
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/tracks` | Paginated user library with features |
| `GET` | `/tracks/stats` | Library counts: total, analysed, with emotions |
| `GET` | `/tracks/emotions` | Emotion distribution across library |
| `GET` | `/tracks/by-emotion/{emotion}` | Tracks filtered by emotion label |
| `GET` | `/tracks/readiness` | Library processing state (empty / processing / ready) |
| `GET` | `/tracks/arc-pool` | All classified tracks for arc planning (single query) |
| `GET` | `/tracks/model-status` | ML classifier status, F1 score, training metadata |
| `GET` | `/tracks/language-stats` | Language distribution (Unicode script detection) |
| `POST` | `/tracks/reclassify` | Apply trained classifier to entire user library |

### Arc
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/arc/generate` | Natural language mood → full arc (with optional language filter) |
| `POST` | `/arc/replan` | Skip-driven mid-session re-plan from current emotional position |
| `POST` | `/arc/adjust` | Natural language mid-session arc adjustment via Claude |
| `GET` | `/arc/suggest` | Context-aware zero-input arc suggestion (time + history) |
| `GET` | `/arc/user-graph` | Diagnostic: personalised vs. global edge weight deltas |
| `POST` | `/arc/preview` | Fast path-only arc preview (no track selection) |
| `GET` | `/arc/emotions` | All 12 valid emotion labels with descriptions, energy centres, neighbours |
| `GET` | `/arc/insights` | Longitudinal patterns: streak, top emotions, arc pairs, time slots |

### Sessions
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/sessions` | Create session record from generated arc |
| `PATCH` | `/sessions/{session_id}` | Update session status (active / completed / abandoned) |
| `POST` | `/sessions/{session_id}/events` | Record track play/skip events |

### Templates
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/templates` | Publish arc as shareable template |
| `GET` | `/templates` | Browse templates (paginated, filterable by source/target) |
| `GET` | `/templates/{template_id}` | Single template |
| `POST` | `/templates/{template_id}/remix` | Apply template path to your own library |

### Collab
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/collab/sessions` | Create collaborative session with target emotion + invite code |
| `POST` | `/collab/sessions/{invite_code}/join` | Join session with your source emotion |
| `GET` | `/collab/sessions/{invite_code}` | Session state + all participants |
| `POST` | `/collab/sessions/{invite_code}/arc` | Host triggers group arc generation (centroid aggregation) |

---

## Arc Algorithm

Emotion space is modelled as a **weighted directed graph**:

- **Nodes** — 12 states: energetic, happy, euphoric, peaceful, focused, romantic, nostalgic, neutral, melancholic, sad, tense, angry
- **Edges** — perceptual transition costs (how jarring is this emotional jump?)
- **Shortest path** source → target is the lowest total transition cost
- **Per-user personalisation** — `GraphLearner` rescales edge weights from skip/completion history; at least 5 total signals (and 3 per edge) are required before personalisation activates

### How the path is computed

The graph is tiny — 12 nodes, ~40 edges — so instead of running a Dijkstra search per request, the planner does **one Floyd–Warshall pass** (12³ = 1728 relaxations) and answers every source/target query from the resulting distance and successor matrices in O(1).

The table is memoised with `functools.lru_cache` keyed on a **content digest of the graph**, not on identity. That matters for correctness, not just speed: `GraphLearner.load_user_graph()` returns a different personalised graph per user, and serving one user's shortest paths to another would be a bug. `backend/tests/unit/test_perf_optimisations.py` asserts the cached results match a reference Dijkstra for all 144 source/target pairs, on the global graph and on personalised graphs.

Two more hot-path optimisations ride along:

- **Track pool bucketing** — the candidate pool is indexed by `emotion_label` once per plan, so each path segment scans only its own bucket instead of re-filtering the whole library. Selection is a top-k pass rather than a full sort-then-slice.
- **Memoised language detection** — `language_detector.detect()` is `lru_cache`d and short-circuits on a single codepoint comparison for ASCII/Latin text before walking any Unicode range table.

### Collaborative Aggregation

When N users join a collab session each with a different source emotion:

1. Look up shortest-path distances from every unique source emotion in the shared all-pairs matrix
2. For each candidate emotion, sum those distances across all participants
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

Falls back to keyword classification if the Anthropic API key is unset or the call fails.

---

## ML Model

`Pipeline(StandardScaler → RandomForestClassifier)` trained on 42-dimensional librosa features by `backend/scripts/train_classifier.py`, evaluated with stratified K-fold CV and tracked in MLflow.

| Feature Group | Dims | What It Captures |
|---|---|---|
| MFCC mean + std | 26 | Timbral texture and dynamics |
| Chroma mean | 12 | Harmonic / pitch class content |
| Spectral centroid | 1 | Brightness |
| Zero crossing rate | 1 | Percussiveness / noisiness |
| RMS energy | 1 | Loudness |
| Tempo (BPM) | 1 | Energy |

The classifier operates entirely on acoustic properties — it is **language-agnostic by construction**. A Telugu film track and an English pop track with similar acoustic profiles receive the same emotion label. Predictions below a 0.35 confidence floor are excluded from arc selection as noise.

Once trained, the `/tracks/reclassify` endpoint applies the model to your library in a single bulk UPDATE.

---

## Run It Locally

There are two supported paths. **Docker Compose** is the one to use unless you have a reason not to — it brings up all six services with the right versions and networking. The **manual** path runs the backend and frontend on your machine against containerised (or locally installed) Postgres and Redis.

### Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Docker Engine | 20.10+ | Both paths (manual path still uses it for Postgres/Redis) |
| Docker Compose | v2 (`docker compose`) or v1 (`docker-compose`) | Compose path — `flowstate.sh` invokes the v1 `docker-compose` binary |
| Python | 3.11 | Manual backend (CI pins 3.11; `backend/Dockerfile` uses `python:3.11-slim`) |
| Node.js | 18 | Manual frontend (CI pins 18; `frontend/Dockerfile` uses `node:18-alpine`) |
| ffmpeg + libsndfile | any recent | Manual backend only — librosa audio decoding |
| Spotify Developer app | — | OAuth. [Create one](https://developer.spotify.com/dashboard) |
| Anthropic API key | — | Optional. Without it, mood parsing uses the keyword fallback. [Get a key](https://console.anthropic.com) |

A **Spotify Premium** account is required for in-app playback — the Web Playback SDK does not stream to free accounts.

### 1. Clone and configure

```bash
git clone https://github.com/SuryaKiran434/flowstate.git
cd flowstate
cp .env.example .env
```

Then edit `.env`. The values you must fill in:

| Variable | Notes |
|---|---|
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | From your Spotify dashboard app |
| `SPOTIFY_REDIRECT_URI` | Must match a redirect URI registered on the Spotify app **exactly**. Default: `http://127.0.0.1:3000/callback` |
| `SECRET_KEY` | Any random string — signs the app's JWTs |
| `ANTHROPIC_API_KEY` | Optional; leave blank to use the keyword mood parser |

`.env` is gitignored. Never commit it — only `.env.example`, which holds placeholders.

### 2a. Path A — Docker Compose (recommended)

```bash
docker compose up --build          # or: docker-compose up --build
```

Or use the wrapper, which additionally waits on health checks, tails logs into `logs/`, and exposes `--rebuild` / `--down` / `--seed` / `--status` / `--logs`:

```bash
./flowstate.sh          # already committed with the executable bit set
```

> `flowstate.sh` calls the Compose **v1** binary (`docker-compose`) and will exit early if only `docker compose` v2 is installed. Use `docker compose` directly in that case.

The stack is six services:

| Service | Container | Image / build | Port | URL |
|---|---|---|---|---|
| PostgreSQL | `flowstate_db` | `pgvector/pgvector:pg15` | 5432 | — |
| Redis | `flowstate_redis` | `redis:7-alpine` | 6379 | — |
| Backend | `flowstate_backend` | `./backend/Dockerfile` | 8000 | http://localhost:8000 · [/docs](http://localhost:8000/docs) |
| Frontend | `flowstate_frontend` | `./frontend/Dockerfile` | 3000 | http://localhost:3000 |
| Airflow | `flowstate_airflow` | `./airflow/Dockerfile` | 8080 | http://localhost:8080 (admin / admin) |
| MLflow | `flowstate_mlflow` | `python:3.11-slim` | 5001 → 5000 | http://localhost:5001 |

Database setup is automatic, for both databases:

- **`flowstate`** — created by the Postgres image from `POSTGRES_DB`. The backend then calls `Base.metadata.create_all()` at startup, so all 9 tables exist as soon as the API is up. **There is no Alembic migration step.**
- **`airflow`** — Airflow points at a *separate* database on the same Postgres instance, and the image only auto-creates `POSTGRES_DB`. `docker/postgres/initdb/01-create-airflow-db.sh` is mounted into `/docker-entrypoint-initdb.d/`, which the Postgres entrypoint runs when the cluster is first initialised, and it issues the `CREATE DATABASE`. Airflow then runs `airflow db migrate` itself and creates an `admin` / `admin` user.

No manual `CREATE DATABASE` step is needed on a fresh `docker compose up`.

> **Upgrading from an older checkout:** `/docker-entrypoint-initdb.d/` scripts run *only* on first cluster init, so an existing `postgres_data` volume will not pick this up. Either create the database once by hand —
> ```bash
> docker exec flowstate_db psql -U flowstate -c 'CREATE DATABASE airflow;'
> docker compose restart airflow
> ```
> — or discard the volume and let the init script run: `docker compose down -v && docker compose up -d` (this deletes all local data).

Check it came up:

```bash
curl http://localhost:8000/api/v1/health     # {"status":"ok","version":"1.0.0"}
docker compose ps
```

### 2b. Path B — Manual / local

Bring up just the datastores in Docker, then run the app processes yourself:

```bash
docker compose up -d db redis
```

**Backend** (terminal 1):

```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# macOS: brew install ffmpeg libsndfile
# Debian/Ubuntu: sudo apt-get install -y ffmpeg libsndfile1 libpq-dev gcc

export $(grep -v '^#' ../.env | grep -v '^$' | xargs)   # or set vars however you prefer
uvicorn app.main:app --reload --port 8000
```

`DATABASE_URL` and `REDIS_URL` in `.env.example` already point at `localhost`, which is what this path needs. **Postgres must be reachable before the backend starts** — `app/main.py` runs `Base.metadata.create_all()` at import time, so an unreachable database is an immediate startup failure rather than a request-time one. Redis connects lazily, so a missing Redis only breaks the login flow.

**Frontend** (terminal 2):

```bash
cd frontend
npm ci
npm run dev        # Vite dev server on http://localhost:3000
```

Airflow and MLflow are optional for local development. Start them with `docker compose up -d airflow mlflow` when you want to run the feature pipeline or log training runs; without MLflow, `train_classifier.py` simply skips the logging step.

### 3. First login

Open http://localhost:3000 and log in with Spotify. The backend seeds your library on first login (playlists, liked tracks, top artists) and a readiness indicator shows processing progress. Arcs become available once at least one track is classified.

### 4. Seed the feature store (full pipeline)

```bash
docker exec flowstate_airflow airflow dags trigger feature_enrichment
```

The DAG (`airflow/dags/feature_enrichment_dag.py`, scheduled `0 2 * * *` — daily at 02:00 UTC):

1. Pulls your Spotify library (playlists, liked tracks, top artists)
2. For each track: yt-dlp → YouTube → librosa → 42-dim feature vector → PostgreSQL
3. Logs metrics to MLflow

Expect roughly 5–15 seconds per track — this is why features are pre-computed rather than derived at request time.

### 5. Train the emotion classifier

```bash
cd backend
DATABASE_URL=postgresql://flowstate:flowstate_dev@localhost:5432/flowstate \
    python scripts/train_classifier.py
```

Flags: `--min-confidence` (default 0.65), `--n-estimators` (default 200), `--cv` (default 5), `--model-path`. The model is written to `backend/models/emotion_classifier.joblib` alongside `emotion_classifier_meta.json`; both are gitignored. Metrics go to MLflow at `MLFLOW_TRACKING_URI` (default `http://localhost:5001`).

Then click **Reclassify library** in the dashboard — or `POST /api/v1/tracks/reclassify` — to apply the trained model.

### 6. Run the tests

```bash
# Backend — 568 tests
cd backend && python3 -m pytest              # or: python3 -m pytest tests/unit -v

# Backend lint, exactly as CI runs it (ruff is pinned to 0.15.8 in
# requirements.txt — a newer ruff enables different rules and will report
# findings that CI does not)
ruff check app/ && ruff format --check app/

# Frontend
cd frontend && npm run lint && npm run build && npm run test:coverage
```

The backend suite needs no database or Redis — every DB and network interaction is stubbed. CI additionally provisions Postgres and Redis services and runs `pytest tests/unit -v --cov=app`.

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `INVALID_CLIENT: Invalid redirect URI` | `SPOTIFY_REDIRECT_URI` in `.env` does not byte-match the URI registered on the Spotify app. `localhost` and `127.0.0.1` are different URIs. |
| Backend exits on startup with `could not translate host name "db"` | `DATABASE_URL` still points at the Compose hostname. On the manual path it must be `localhost`. |
| `/auth/spotify/login` returns a connection error | Redis is not up (it connects lazily, so this surfaces at login, not startup). `docker compose up -d redis`. |
| Playback controls do nothing | Web Playback SDK requires Spotify Premium. |
| Airflow container restart-loops on `database "airflow" does not exist` | The init script only runs on a *fresh* `postgres_data` volume. On a pre-existing volume, create it once: `docker exec flowstate_db psql -U flowstate -c 'CREATE DATABASE airflow;' && docker compose restart airflow` — or reset with `docker compose down -v`. |
| Airflow tasks fail on `librosa` / `yt-dlp` import | The `airflow` service must be built from `airflow/Dockerfile` (which bakes them in), not from the stock image. `docker compose build airflow`. |
| yt-dlp returns no results / gets throttled | Expected at volume — see [LIMITATIONS.md](LIMITATIONS.md). |

---

## Test Suite

```bash
cd backend && python3 -m pytest
```

568 tests across 20 test files, **all passing** on Python 3.11 (the version CI and `backend/Dockerfile` use). Coverage spans every service, endpoint function, and integration path.

The failure in `test_graph_learner.py::TestUserGraphEndpoint::test_generate_arc_includes_personalised_flag` noted in earlier revisions of this file was environment-specific: the test drove its own loop via the deprecated `asyncio.get_event_loop().run_until_complete(...)`, which behaves differently on newer Python versions than on 3.11. It is now a plain `async def` handled by pytest-asyncio, so it no longer depends on that.

| Test File | Coverage |
|---|---|
| `test_arc_planner.py` | Path planning, track selection, language filter |
| `test_perf_optimisations.py` | APSP vs. Dijkstra equivalence, cache keying, bucketing, top-k |
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
| `test_log_sanitize.py` | Control-character stripping, truncation boundary, non-string input |
| `test_config_database_url.py` | DSN fallback assembly, password escaping (`@`, `/`, `:`, `#`) |

The frontend has one suite — 34 tests in `frontend/src/utils/__tests__/auth.test.js`, covering the
session-token guard. That token arrives as a `?token=` query parameter and ends up in an
`Authorization` header, so its rejection cases (CRLF injection, base64 padding, wrong segment count,
the 4096-character cap) are pinned individually. `auth.js` sits at 100%.

```bash
cd frontend && npm run test            # or npm run test:coverage for lcov
```

The rest of `frontend/src` has no test harness yet — the pages and the two visualiser/player
components need a DOM environment and a mocked Spotify SDK before they can be rendered. Those paths
are listed in `sonar.coverage.exclusions` so they are still analysed for bugs, smells, security and
duplication, but do not score coverage they have no way to produce. Each entry is meant to be deleted
as the file behind it gets tests.

---

## CI

`.github/workflows/ci.yml` runs on every push and PR to `main` / `develop`. `main` requires the three
blocking checks below to pass before a merge; SonarCloud is advisory and runs `continue-on-error`, so
an outage there never blocks a merge.

| Check | Does | Required |
|---|---|---|
| **Backend (Python)** | `ruff check` + `ruff format --check` on `app/`, then `pytest tests/unit` with Postgres + Redis services, publishes `coverage.xml` | yes |
| **Frontend (React)** | `npm ci`, ESLint, typecheck stub, `vite build`, `vitest run --coverage`, publishes `lcov.info` | yes |
| **Docker Build** | Builds `./backend` and `./frontend` images | yes |
| **SonarCloud** | Downloads both coverage reports and runs one scan over both trees | no |

SonarCloud is a job of its own rather than a step inside the backend job, and the reason is worth
knowing before anyone moves it back: Sonar scores a source file it analyses but cannot find in any
coverage report as **0% covered**, not as unmeasured. With the scan inside the backend job the
frontend's lcov was in a different workspace, so all of `frontend/src` counted as uncovered and no
frontend test could change that number. Both test jobs now publish their report as an artifact and
the scan job consumes both. It also rewrites the lcov path prefix — vitest records files relative to
`frontend/`, Sonar resolves them from the repository root — and fails if either report is missing,
because an absent report is silently scored as zero rather than skipped.

Dependency updates are proposed weekly by Dependabot (`.github/dependabot.yml`) for pip, npm, Docker
base images, and GitHub Actions, capped at 5 open PRs per ecosystem. Each ecosystem is **grouped**
into one PR per week rather than one PR per dependency, and majors are kept out of the groups so a
batch can never carry a breaking change. `.github/workflows/dependabot-auto-merge.yml` keys on that
split: a grouped PR queues itself to merge once the required checks pass, while a major waits for a
human. The docker groups are **patch-only** on purpose — a base image tag's "major" is the product
major, so `python:3.11-slim` → `3.14-slim` reads to Dependabot as a minor while being a whole runtime
jump. Docker minors therefore arrive as their own PR and are held back from auto-merge.

`.github/workflows/slack-notify.yml` posts a push notification to a Slack webhook on every branch.

---

## Scaling Considerations

| Challenge | Solution |
|---|---|
| yt-dlp slow (5–15s/track) | Pre-compute via Airflow; serve from DB at query time |
| Repeated path planning | One cached Floyd–Warshall table per distinct graph; O(1) lookups thereafter |
| Arc generation latency | Cache common source→target arcs in Redis (planned) |
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
| Audio pipeline | yt-dlp, librosa 0.10.1, ffmpeg |
| ML | scikit-learn 1.9.0, MLflow, joblib |
| Mood parsing | Anthropic Claude API (claude-haiku-4-5) |
| Backend | FastAPI 0.104.1, SQLAlchemy 2.0.23, Pydantic v2 (2.5.2), uvicorn 0.24.0 |
| Database | PostgreSQL 15 (`pgvector/pgvector:pg15`) |
| Cache / state | Redis 7 (`redis` 5.0.1 client) |
| Pipeline | Apache Airflow 2.11.2 (`apache/airflow:2.11.2-python3.11`) |
| Frontend | React 18, D3.js v7, Vite 6, react-router-dom 7, axios |
| Playback | Spotify Web Playback SDK |
| Auth | Spotify OAuth2 PKCE, JWT (python-jose) |
| Lint / test | ruff 0.15.8, pytest 9.1.1, ESLint 8, Vitest 3 |
| Infra | Docker, Docker Compose |

---

## Roadmap

- [x] Spotify OAuth2 PKCE with Redis state store + auto token refresh
- [x] Personal library seeding (playlists, liked tracks, top artists)
- [x] yt-dlp + librosa audio feature pipeline (42-dim vectors)
- [x] Graph shortest-path arc planning on a 12-node emotion graph
- [x] Claude-powered natural language mood parsing + keyword fallback
- [x] Arc generation API (`/arc/generate`, `/arc/preview`)
- [x] React frontend with OAuth flow and library stats dashboard
- [x] Docker Compose full-stack deployment
- [x] 510-test backend suite (arc planner, mood parser, auth, sessions, classifier)
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
- [x] Hot-path performance — cached all-pairs shortest paths, pool bucketing, memoised language detection
- [ ] Redis-backed arc cache for common source→target pairs
- [ ] Frontend test suite

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

MIT.

---

*Built with a love for music that actually understands where you are and where you want to be.*
