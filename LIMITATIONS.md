# Limitations & Market Gaps

> What Flowstate currently can't do — and what no major streaming service offers today.

This document is split into two parts:
1. **Current Technical Limitations** — known constraints in this codebase
2. **Unexplored Market Opportunities** — capabilities that don't exist in Spotify, Apple Music, YouTube Music, or any mainstream service

---

## Part 1: Current Technical Limitations

### 1. Emotion Classifier Not Yet Trained
The 42-dimensional librosa feature vectors are extracted and stored, but the supervised emotion classifier model has not been trained. Currently, emotion labels in the database are either absent or heuristic. Until the model is trained and evaluated (target: >75% F1), arc quality depends entirely on the quality of manual/heuristic emotion labeling.

**What's missing:** A labeled training dataset, training pipeline, and evaluation harness. MLflow is configured but unused.

---

### 2. In-Memory PKCE State Store
The OAuth2 PKCE state dictionary (`_pkce_store` in `auth.py`) is held in-memory. This means:
- State is lost on server restart → users get a broken OAuth callback
- Not safe for multi-process or multi-instance deployments
- No TTL expiry, so stale states accumulate

**Fix required:** Move to Redis with a short TTL (5–10 minutes).

---

### 3. yt-dlp Latency and Fragility
Audio extraction takes 5–15 seconds per track. The pipeline mitigates this by pre-computing via Airflow, but:
- New tracks added mid-session have no features until the next DAG run
- YouTube can return the wrong video (title mismatch, covers, live versions)
- YouTube blocks automated scrapers at scale — yt-dlp is a development-only solution

**Production path:** License audio fingerprinting via AudD or Musicstax, or use a dedicated audio analysis API.

---

### 4. No Real-time Playback Integration
The Spotify Web Playback SDK is not yet integrated. Users cannot listen within the app. The arc exists as a data structure but has no playback layer — the experience ends at arc generation.

---

### 5. Static Arc — No Adaptation During Playback
Once an arc is generated, it's fixed. If a user skips a track, nothing changes. The arc doesn't learn from behavior within a session or across sessions.

---

### 6. Single-User Model
The arc is built from a single user's library and emotional state. There is no multi-user or group listening concept.

---

### 7. Cold Start Problem
New users with small or unanalyzed libraries get poor arcs. The Airflow DAG needs to run at least once (and complete feature extraction) before a meaningful arc can be generated. For a new user, this could mean a 30–60 minute wait before the product is usable.

---

### 8. No Evaluation of Arc Quality
There is no feedback loop or signal for whether an arc worked. No completion rates, skip patterns, or user ratings are collected. Without this signal, the arc algorithm cannot improve over time.

---

### 9. Hardcoded Emotion Graph
The 12-node emotion graph and its edge weights are manually defined constants in `arc_planner.py`. These weights represent one person's intuition about perceptual transitions — they are not learned from listening behavior or validated against user data.

---

### 10. Test Coverage Near Zero
CI is configured but no test files exist in the repository. The arc planner, mood parser, and feature extraction pipeline are untested. A regression in core algorithm logic would go undetected.

---

## Part 2: Unexplored Market Opportunities

These are capabilities that **no major streaming service currently offers** and that Flowstate's architecture is positioned to explore.

---

### 1. Skip-Driven Arc Re-Planning
**What exists:** Streaming services log skips but use them only for long-term recommendation signals (e.g., "don't play this artist for 30 days").

**What doesn't exist:** Real-time arc re-planning based on mid-session skip behavior. If a user skips the third track in a "tense → peaceful" arc, the system should infer the transition was too slow or too fast and re-route the remaining arc accordingly.

**Flowstate's path:** The Dijkstra-based arc planner already supports re-entry from any emotion node. A skip detection hook in the playback layer could trigger re-planning from the current emotional position with updated constraints.

---

### 2. Goal-Directed Emotional Navigation
**What exists:** Static mood playlists ("Chill Vibes", "Workout"). These reflect a current mood but don't move the listener anywhere.

**What doesn't exist:** Playlists with an explicit emotional *destination* — music that is intentionally designed to shift your state over 20–60 minutes. No service asks "where do you want to feel at the end of this session?"

**Flowstate's path:** This is the core arc architecture. The gap is completing the ML classifier and playback integration to make this a polished, usable feature.

---

### 3. Context-Aware Arc Seeding
**What exists:** Time-of-day playlist suggestions (Spotify's "Morning Commute", "Evening Wind Down") — manually curated, not personalized.

**What doesn't exist:** Arcs that adapt to your actual context: calendar events, time of day, day of week, recently played history, or biometric data.

**Example:** At 10 PM on a Sunday, after a heavy "energetic" session, automatically suggest a "euphoric → peaceful" arc without the user needing to describe their state.

**Implementation path:** Layer a context inference model on top of mood parsing that proposes arc parameters, which the user can accept or modify.

---

### 4. Personalized Emotion Graph
**What exists:** A universal emotion graph shared across all users (Flowstate's current model) or no graph at all (every other service).

**What doesn't exist:** A per-user emotion graph where edge weights are learned from that user's actual skip/completion patterns. Some users find "tense → peaceful" jarring and need to pass through "focused" first. Others tolerate larger perceptual jumps. No service models this.

**Implementation path:** Collect session completion rates and skip positions. Use these as negative/positive signals to update a user-specific copy of the emotion transition weights over time.

---

### 5. Multi-Language Emotional Intelligence
**What exists:** Language-specific playlist categories ("Bollywood", "K-Pop"). Emotion analysis is mostly English-centric or language-agnostic via popularity signals.

**What doesn't exist:** An emotion classifier that is genuinely language-agnostic at the *audio feature level* — one that correctly classifies a Telugu folk song as "nostalgic" or a Tamil film track as "romantic" based on acoustic properties, not metadata or language-specific training labels.

**Flowstate's path:** The librosa pipeline is inherently language-agnostic (it operates on raw audio). With a properly trained multi-lingual emotion dataset, Flowstate could offer emotionally coherent arcs across Telugu, Tamil, Hindi, English, and Korean in the same session — something no service does today.

---

### 6. Physiological Feedback Loop
**What exists:** Apple Music's integration with Apple Health shows workout playlists. No service reads biometric data to infer or adapt emotional state.

**What doesn't exist:** Using heart rate variability (HRV), skin conductance, or accelerometer data from a wearable to dynamically adjust arc pacing. If your HRV shows high stress at the 10-minute mark, slow the arc transition down.

**Implementation path:** An optional wearable data adapter (Apple Watch via HealthKit, Garmin API) that feeds real-time physiological signals into the arc planner as soft constraints.

---

### 7. Collaborative Arc Sessions
**What exists:** Spotify's "Jam" (collaborative queue) and "Group Session" — these synchronize playback but make no attempt to reconcile multiple users' emotional states.

**What doesn't exist:** An arc engine that takes multiple users' stated emotional states and generates a shared arc that is a reasonable compromise — e.g., one person is "sad", another is "energetic", and the arc finds a path that moves them toward a shared target like "happy".

**Implementation path:** A multi-user arc planner that aggregates source emotion inputs (centroid or majority vote on the emotion graph) and plans toward a shared target.

---

### 8. Emotional Memory and Learning
**What exists:** Spotify Wrapped (annual summary). Daily Mix (recency-weighted). No service tracks your emotional journey over time.

**What doesn't exist:** A longitudinal emotional profile — understanding that you typically need 25 minutes to wind down after work on weekdays, or that you always start Monday mornings in "tense" and benefit from a "focused" arc.

**Implementation path:** Store session outcomes (source emotion, target emotion, duration, completion rate, time of day, day of week). Train a simple time-series model that predicts likely starting emotion and suggests arc parameters without the user needing to describe anything.

---

### 9. Causal Emotion Attribution
**What exists:** Post-hoc listening analytics ("you listened to X artist 47 times"). No causal signal about which tracks actually shifted mood.

**What doesn't exist:** Identifying which specific tracks in an arc were causally responsible for a successful mood shift — and using that signal to weight future track selection.

**Implementation path:** Treat the arc as an experiment. Track mood self-reports (or skip patterns as proxies) at multiple points in the session. Use a difference-in-differences approach to estimate which tracks at which positions drove the most change. Feed these estimates back into the track scoring in `arc_planner.py`.

---

### 10. Natural Language Arc Control
**What exists:** Flowstate already implements Claude-powered mood parsing. No other service allows natural language arc control.

**What doesn't exist (in Flowstate today):** Mid-session natural language commands — "slow this down", "more melancholic for now", "skip ahead to the peaceful part". The current implementation only parses mood at session start.

**Implementation path:** Expose a real-time arc modification API that accepts natural language mid-session instructions, parses them via Claude, and re-plans the remaining arc from the current position. This is a genuinely novel interaction paradigm for music apps.

---

### 11. Audio-Visual Emotional Synchronization
**What exists:** Spotify Canvas (looping videos). Apple Music lyrics sync. Neither is emotionally synchronized to arc position.

**What doesn't exist:** Visual elements (color gradients, particle animations, generative art) that evolve in sync with the emotional arc — so the visual state at the 30-minute mark of a "tense → peaceful" arc looks qualitatively different from the 5-minute mark.

**Flowstate's path:** The D3.js arc visualizer is in progress. Extending it to drive generative visual parameters (color, particle density, animation speed) from the current emotion node position in the arc is a natural extension.

---

### 12. Arc Sharing and Remix
**What exists:** Spotify playlist sharing. No emotional structure is preserved or shared.

**What doesn't exist:** Sharing an *arc template* — "this is my 40-minute commute decompression arc from tense to peaceful, built from Indian indie music" — that others can adopt and personalize against their own library.

**Implementation path:** Serialize the arc as source emotion, target emotion, emotion path, duration, and genre/language constraints. Allow users to share arc templates that other users can apply to their own seeded track libraries.

---

## Summary

| Limitation | Severity | Path to Fix |
|---|---|---|
| Emotion classifier not trained | High | Label dataset, train model, evaluate in MLflow |
| In-memory PKCE store | Medium | Migrate to Redis with TTL |
| yt-dlp fragility at scale | Medium | License audio API for production |
| No playback integration | High | Spotify Web Playback SDK |
| Static arc, no adaptation | High | Skip-event hook → re-plan from current node |
| No test coverage | High | Write unit tests for arc planner and mood parser |
| Hardcoded emotion graph | Low | Learn weights from skip/completion signals |
| Cold start | Medium | Prioritize top artists for immediate extraction |

| Market Gap | Uniqueness | Complexity |
|---|---|---|
| Skip-driven arc re-planning | High | Medium |
| Goal-directed emotional navigation | Very High | Low (already partially built) |
| Context-aware arc seeding | High | Medium |
| Personalized emotion graph | Very High | High |
| Multi-language emotional intelligence | High | Medium |
| Physiological feedback loop | High | High |
| Collaborative arc sessions | Very High | High |
| Emotional memory + longitudinal learning | Very High | High |
| Mid-session natural language control | Very High | Medium |
| Audio-visual emotional sync | Medium | Medium |
| Arc sharing and remix | Medium | Low |
