# Product Requirements Document — Flowstate

**Author:** Surya Kiran Katragadda
**Version:** 1.1
**Status:** In Progress
**Last Updated:** 2026-03-06

---

## 1. Problem Statement

Music streaming services serve static mood playlists. When a user selects "Chill" or "Energetic", they receive a pre-curated list that doesn't adapt to their emotional trajectory or where they want to end up. This ignores a fundamental truth about how people actually use music: as a **tool for emotional regulation**, not just reflection.

A student finishing an exam doesn't want music that matches their current stress — they want music that guides them *out of* stress and into calm. An athlete warming up doesn't want relaxing music, but they also don't want to jump straight to 180 BPM — they want a ramp.

**Current gap:** No major streaming service offers dynamic, goal-directed emotional arc playlists.

**Technical context:** Spotify's Audio Features API (`/audio-features`) — which provides valence, energy, and danceability — was deprecated for new apps in 2025 and is blocked entirely in Development Mode. Flowstate's solution is a custom audio feature extraction pipeline using **yt-dlp + librosa** that is fully independent of Spotify's feature APIs, works for all languages (Telugu, Tamil, Hindi, English), and scales with any catalog.

---

## 2. Goals

### Primary Goal
Build a feature that lets users define a start emotion and end emotion, and automatically curates a listening session that musically bridges those two states.

### Success Metrics
| Metric | Target |
|---|---|
| Arc generation latency (p95) | < 2 seconds |
| Emotion classification accuracy | > 75% F1 on held-out set |
| Session completion rate | > 60% (user listens to > 80% of arc) |
| Arc API uptime | 99.5% |
| Feature extraction coverage | > 80% of seeded tracks enriched |
| Test coverage | > 80% on core services |

---

## 3. User Stories

### Core
- As a user, I want to select my current emotional state and my desired emotional state so that Flowstate can build a playlist that takes me there.
- As a user, I want to see a visual arc of my emotional journey so I can understand where I am and where I'm going.
- As a user, I want Spotify playback directly in the app so I don't have to switch apps.

### Extended
- As a user, I want to specify the duration of my session (15 min, 30 min, 60 min).
- As a user, I want to save arcs I loved so I can replay them.
- As a user, I want to skip a track if it breaks my flow and have the arc auto-adjust.

---

## 4. Non-Goals (v1)
- Offline playback
- Podcast or audiobook support
- Social/sharing features
- iOS/Android native app

---

## 5. Functional Requirements

### FR-1: Authentication
- Flowstate must authenticate users via Spotify OAuth2 PKCE flow
- Access tokens must be refreshed automatically using the stored refresh_token
- Users must not need to re-login between sessions

### FR-2: Arc Generation
- System must accept source emotion, target emotion, and duration as inputs
- System must return an ordered list of tracks within 2 seconds (p95)
- Each track must include: track_id, artist, title, emotion_label, confidence, transition_note
- System must use tracks from the user's seeded library

### FR-3: Emotion Classification
- System must classify tracks into one of 12 emotion states
- Classification must use a 42-dimensional librosa feature vector:
  MFCCs (13 mean + 13 std), Chroma (12 mean), spectral centroid, ZCR, RMS energy, tempo
- Audio sourced via yt-dlp from YouTube — works for all languages and markets globally
- Model must achieve > 75% F1 on held-out test set
- Inference must complete within 100ms per track (from pre-computed features)

### FR-4: Audio Feature Extraction Pipeline (Airflow)
- DAG must discover tracks via Spotify Search API (works in Development Mode)
- For each track: yt-dlp YouTube search → download 30s clip → librosa feature extraction
- Features stored in PostgreSQL `track_features` table
- Pipeline must auto-refresh expired Spotify tokens using stored refresh_token
- Failed extractions must be logged and retried on next run

### FR-5: Arc Visualization
- Frontend must display a D3.js arc showing the emotional journey
- Arc must update in real-time as playback progresses

### FR-6: Playback
- Frontend must integrate Spotify Web Playback SDK
- Playback controls (play/pause/skip) without leaving the app
- Skipping a track must trigger arc re-adjustment

---

## 6. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Performance | Arc generation p95 < 2s |
| Scalability | Horizontal scaling of API layer |
| Security | Tokens encrypted at rest |
| Observability | Structured logs + MLflow metrics |
| Reliability | Graceful degradation if Spotify API unavailable |
| Portability | Full stack via `docker-compose up` |
| Globalization | Audio extraction works for all languages and markets |

---

## 7. Technical Constraints
- MacBook Pro M1 (Apple Silicon) locally
- Zero paid infrastructure during development
- All dependencies open source
- Python 3.11+, Node.js 18+
- Spotify Development Mode: `/audio-features`, playlist tracks, and recommendations endpoints blocked → use yt-dlp + librosa pipeline

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| yt-dlp extraction slow (5–15s/track) | High | Medium | Pre-compute offline via Airflow; serve from feature store at query time |
| YouTube blocks yt-dlp at scale | Medium | High | For production: license audio via Musicstax/AudD; yt-dlp for dev |
| yt-dlp finds wrong YouTube video | Medium | Medium | Validate: yt-dlp duration within 15% of Spotify's duration_ms |
| Emotion classifier underfits | Medium | High | Start with heuristic labels from feature clustering; iterate with MLflow |
| Arc generation too slow | Low | High | Cache common source→target paths in Redis |
| Spotify token expiry during DAG | High | Medium | Auto-refresh via stored refresh_token before each API call |

---

## 9. Open Questions
- [ ] Should we support multi-hop arcs (e.g., stressed → focused → peaceful)?
- [ ] Should yt-dlp audio be cached to object storage to avoid re-downloading?
- [ ] Should the arc re-plan dynamically based on skip patterns?
- [ ] What is the minimum library size for a good arc?
