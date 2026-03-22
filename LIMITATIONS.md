# Limitations & Future Directions

> What Flowstate currently can't do — and what remains on the frontier.

This document tracks the honest constraints of this codebase. It started as a list of everything broken or missing. Most of it has been built. What remains below is what's genuinely still open.

---

## Part 1: Resolved Technical Limitations

These were originally listed as blockers. They are now implemented.

---

### ~~1. Emotion Classifier Not Yet Trained~~ ✓ Resolved

**What was missing:** A labeled training dataset, training pipeline, and evaluation harness.

**What was built:**
- `train_classifier.py` — RandomForest on 42-dim librosa feature vectors, cross-validated, target >75% macro F1
- MLflow experiment tracking with per-class F1, macro F1, and sample counts
- `GET /tracks/model-status` — exposes model availability, F1, training metadata
- `POST /tracks/reclassify` — applies trained model to entire user library in a single bulk UPDATE
- `ModelStatusCard` in the dashboard shows classifier health and triggers reclassification

---

### ~~2. In-Memory PKCE State Store~~ ✓ Resolved

**What was missing:** PKCE state was held in a Python dict — lost on restart, unsafe for multi-process deployment, no TTL.

**What was built:** Redis-backed PKCE store with 10-minute TTL. State survives restarts and is safe across multiple workers.

---

### ~~3. yt-dlp Latency and Fragility~~ Partially Mitigated

**Still true:** yt-dlp takes 5–15 seconds per track and YouTube can return wrong videos. These are inherent to using an unofficial scraper.

**Mitigated by:**
- Airflow pre-computes features daily — at query time, the arc planner reads from PostgreSQL, not YouTube
- New tracks added mid-session wait for the next DAG run (typically < 24h)
- The readiness endpoint (`GET /tracks/readiness`) guards against showing an arc before enough tracks are classified

**Production path:** License audio fingerprinting via AudD or Musicstax. Not implemented — requires paid API access.

---

### ~~4. No Real-time Playback Integration~~ ✓ Resolved

**What was built:** Spotify Web Playback SDK is integrated. Users listen within the app. `SpotifyPlayer.jsx` manages device transfer, play/pause/skip, and fires telemetry events back to the session record.

---

### ~~5. Static Arc — No Adaptation During Playback~~ ✓ Resolved

**What was built:**
- `POST /arc/replan` — detects 2+ consecutive skips in the same emotion segment, bypasses that emotion, and re-routes from the next best neighbour toward the target
- `POST /arc/adjust` — natural language mid-session commands ("slow this down", "more melancholic") are parsed by Claude and re-plan the remaining arc from the current position

---

### ~~6. Single-User Model~~ ✓ Resolved

**What was built:** Collaborative arc sessions (`/collab/*`). N users each contribute a source emotion. A graph centroid algorithm (Dijkstra-based minimum total distance) finds the most central emotional starting point for the group. The host triggers arc generation using their library.

---

### ~~7. Cold Start Problem~~ ✓ Resolved

**What was built:** `LibrarySeeder` auto-triggers on first login, immediately pulling the user's playlists, liked tracks, and top artists. The readiness endpoint reports processing state and blocks arc generation until at least one track is classified. The frontend polls readiness every 8 seconds and updates live.

---

### ~~8. No Evaluation of Arc Quality~~ ✓ Resolved

**What was built:**
- Session telemetry: every skip and play event is recorded with position and timestamp
- `LongitudinalAnalyzer` aggregates session history into completion rates, streak, top starting emotions, arc pair frequency, and per-time-slot dominant source emotions
- `GET /arc/insights` exposes this as a structured endpoint
- The `InsightsPanel` in the dashboard shows a streak badge, top emotions, recent arc timeline

---

### ~~9. Hardcoded Emotion Graph~~ ✓ Resolved

**What was built:** `GraphLearner` accumulates skip and completion signals per user, computes delta weights, and builds a personalised version of the 12-node graph. ArcPlanner uses the personalised graph when ≥ 5 signals exist; falls back to the global graph otherwise. `GET /arc/user-graph` exposes the deltas for diagnostic inspection.

---

### ~~10. Test Coverage Near Zero~~ ✓ Resolved

**What was built:** 428 tests across 18 test files covering every service, endpoint function, and integration path. All pass.

---

## Part 2: Remaining Open Limitations

These are genuine constraints that are not yet addressed.

---

### 1. yt-dlp at Production Scale

yt-dlp is a development-only solution. At scale, YouTube aggressively blocks automated scrapers. The current pipeline is suitable for personal use and demos but will break for multi-user production deployments.

**Path forward:** Integrate AudD, Musicstax, or a similar licensed audio fingerprinting API that doesn't require downloading audio.

---

### 2. No Physiological Feedback Loop

The arc engine adapts to skip behaviour and explicit commands, but has no access to physiological state. Heart rate variability, skin conductance, or motion data from a wearable could make arc pacing genuinely adaptive to real-time stress or recovery state.

**Path forward:** An optional wearable data adapter (Apple Watch via HealthKit, Garmin API) that feeds physiological signals into the arc planner as soft constraints. Requires hardware integration and user consent flows outside this codebase's scope.

---

### 3. Language Detection is Heuristic

Language is inferred from Unicode script ranges in track title and artist name. This works well for scripts with clear Unicode blocks (Telugu, Tamil, Korean, Japanese) but:
- Transliterated titles ("Jai Ho", "Naatu Naatu") are detected as English
- Artist names written in Latin script for non-English artists register as English
- Script mixing (title in one script, artist in another) takes the first recognised script

**Path forward:** Integrate a language identification model (e.g. fastText's language ID) that operates on the full text rather than script ranges. Or add a language metadata field that users can manually override.

---

### 4. Collab Sessions Require Shared Library Access

The collaborative arc currently generates tracks from the **host's library only**. Guests contribute their emotional state but their music doesn't enter the pool. A true group session would merge libraries across all participants.

**Path forward:** Load track pools from all confirmed participants, merge and deduplicate, then plan the arc against the union. Requires each guest to have an active session with a classified library.

---

### 5. Emotion Labels Are Not Ground-Truth Validated

The RandomForest classifier is trained on heuristic-labeled data produced by the previous rule-based system. There is no human-validated ground-truth label set. If the heuristic labels are systematically wrong (e.g. consistently misclassifying Tamil film ballads), the trained model will inherit that bias.

**Path forward:** Build a small human-annotated validation set. Even 200–300 tracks rated by 3+ listeners would allow an honest F1 measurement against human perception rather than heuristic proxies.

---

### 6. Arc Quality Has No Direct User Feedback Signal

Completion rate is used as a proxy for arc quality, but a user might complete an arc they didn't enjoy (passive listening) or abandon a good arc (distraction). There is no explicit "this worked / this didn't" signal.

**Path forward:** A lightweight post-arc rating (thumbs up/down or 1–5 stars) stored alongside the session. This becomes the training signal for future model improvements and arc parameter tuning.

---

## Part 3: Market Gaps — Implementation Status

These were originally listed as capabilities that no major streaming service offers. All have now been built into Flowstate.

| Capability | Status | Where |
|---|---|---|
| Skip-driven arc re-planning | ✓ Built | `POST /arc/replan`, `GraphLearner` |
| Goal-directed emotional navigation | ✓ Built | Core arc architecture |
| Context-aware arc seeding | ✓ Built | `POST /arc/suggest`, `ContextSeeder` |
| Personalised emotion graph | ✓ Built | `GraphLearner`, `GET /arc/user-graph` |
| Multi-language emotional intelligence | ✓ Built | `LanguageDetector`, `language_filter` param |
| Collaborative arc sessions | ✓ Built | `/collab/*`, `CollabArcService` |
| Emotional memory + longitudinal learning | ✓ Built | `LongitudinalAnalyzer`, `GET /arc/insights` |
| Mid-session natural language control | ✓ Built | `POST /arc/adjust` |
| Audio-visual emotional synchronisation | ✓ Built | CSS `--emotion-primary`, constellation lerp, chart fill |
| Arc sharing and remix | ✓ Built | `/templates/*`, `ArcTemplate` ORM |
| Physiological feedback loop | ○ Future | Requires wearable hardware integration |
| Causal emotion attribution | ○ Future | Requires human-annotated rating data |

---

## Summary

| Item | Status |
|---|---|
| Emotion classifier | ✓ Trained, deployed, reclassify API |
| PKCE state store | ✓ Redis with TTL |
| yt-dlp fragility | ⚠ Mitigated (pre-compute), not solved at scale |
| Playback integration | ✓ Spotify Web Playback SDK |
| Static arc | ✓ Replan + NL adjust |
| Single-user model | ✓ Collaborative sessions |
| Cold start | ✓ Auto-seed + readiness guard |
| No arc quality signal | ✓ Telemetry + completion rate (explicit rating: future) |
| Hardcoded emotion graph | ✓ Per-user learned weights |
| Test coverage | ✓ 428 tests, all passing |
