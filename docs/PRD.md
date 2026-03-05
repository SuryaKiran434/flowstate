# Product Requirements Document — Flowstate

**Author:** Surya Kiran Katragadda  
**Version:** 1.0  
**Status:** In Progress  
**Last Updated:** 2026-03-04

---

## 1. Problem Statement

Music streaming services serve static mood playlists. When a user selects "Chill" or "Energetic", they receive a pre-curated list that doesn't adapt to their emotional trajectory or where they want to end up. This ignores a fundamental truth about how people actually use music: as a **tool for emotional regulation**, not just reflection.

A student finishing an exam doesn't want music that matches their current stress — they want music that guides them *out of* stress and into calm. An athlete warming up doesn't want relaxing music, but they also don't want to jump straight to 180 BPM — they want a ramp.

**Current gap:** No major streaming service offers dynamic, goal-directed emotional arc playlists.

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
| Test coverage | > 80% on core services |

---

## 3. User Stories

### Core
- As a user, I want to select my current emotional state and my desired emotional state so that Flowstate can build a playlist that takes me there.
- As a user, I want to see a visual arc of my emotional journey so I can understand where I am and where I'm going.
- As a user, I want to use my own Spotify library as the track pool so the arc feels personal.
- As a user, I want Spotify playback directly in the app so I don't have to switch apps.

### Extended
- As a user, I want to specify the duration of my session (15 min, 30 min, 60 min) so the arc fits my schedule.
- As a user, I want to save arcs I loved so I can replay them.
- As a user, I want to skip a track if it breaks my flow and have the arc auto-adjust.

---

## 4. Non-Goals (v1)

- Offline playback
- Podcast or audiobook support
- Social/sharing features
- iOS/Android native app
- Support for non-Spotify music sources

---

## 5. Functional Requirements

### FR-1: Authentication
- Flowstate must authenticate users via Spotify OAuth2 PKCE flow
- Access tokens must be refreshed automatically
- Users must not need to re-login between sessions

### FR-2: Arc Generation
- System must accept source emotion, target emotion, and duration as inputs
- System must return an ordered list of tracks within 2 seconds (p95)
- Each track in the response must include: track_id, artist, title, emotion_label, confidence, transition_note
- System must use only tracks from the user's Spotify library

### FR-3: Emotion Classification
- System must classify tracks into one of 12 emotion states
- Classification must use audio features (MFCCs, chroma, tempo, valence, energy)
- Model must achieve > 75% F1 on held-out test set
- Inference must complete within 100ms per track

### FR-4: Arc Visualization
- Frontend must display a D3.js arc showing the emotional journey
- Arc must update in real-time as playback progresses
- Current position on the arc must be visible at all times

### FR-5: Playback
- Frontend must integrate Spotify Web Playback SDK
- Playback controls (play/pause/skip) must be available without leaving the app
- Skipping a track must trigger arc re-adjustment

### FR-6: Data Pipeline
- Airflow DAG must run daily to enrich the feature store with new user tracks
- Pipeline must handle Spotify API rate limits gracefully with exponential backoff
- Failed DAG runs must trigger alerts

---

## 6. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Performance | Arc generation p95 < 2s |
| Scalability | Architecture must support horizontal scaling of API layer |
| Security | No Spotify credentials stored; tokens encrypted at rest |
| Observability | All API endpoints emit structured logs + metrics |
| Reliability | Graceful degradation if Spotify API is unavailable |
| Portability | Full stack runs via single `docker-compose up` command |

---

## 7. Technical Constraints

- Must run on MacBook Pro M1 (Apple Silicon) locally
- Zero paid infrastructure during development (Spotify free tier, Fly.io free tier, Vercel free tier)
- All dependencies must be open source
- Python 3.11+, Node.js 18+

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Spotify API rate limiting | High | Medium | Exponential backoff + feature store caching |
| Emotion classifier underfits | Medium | High | Start with Spotify's valence/energy as proxies, augment with librosa |
| Arc generation too slow | Low | High | Pre-compute common paths, cache in Redis |
| Spotify changes SDK | Low | High | Wrap SDK in abstraction layer |
| 30s preview clips unavailable | Medium | Medium | Fall back to Spotify audio features only |

---

## 9. Open Questions

- [ ] Should we support multi-hop arcs (e.g., stressed → focused → peaceful)?
- [ ] How do we handle tracks that span multiple emotion states?
- [ ] Should the arc re-plan dynamically based on playback skip patterns?
- [ ] What is the minimum library size required for a good arc?
