# Database Schema — Flowstate

## Overview

PostgreSQL 15 with the `pgvector` extension for similarity search on track embeddings.

**Audio feature source:** yt-dlp (YouTube) → librosa. Spotify's `/audio-features` endpoint is blocked in Development Mode and deprecated for new apps — Flowstate's pipeline is fully independent and works for all languages and markets.

---

## Tables

### `users`
Spotify user profiles synced at OAuth login.

```sql
CREATE TABLE users (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spotify_id       VARCHAR(255) UNIQUE NOT NULL,
    display_name     VARCHAR(255),
    email            VARCHAR(255),
    access_token     TEXT,               -- Spotify access token (refreshed automatically)
    refresh_token    TEXT,               -- Spotify refresh token (long-lived)
    token_expires_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_at       TIMESTAMPTZ DEFAULT now()
);
```

---

### `tracks`
Core track metadata from Spotify Search API.

```sql
CREATE TABLE tracks (
    id           VARCHAR(50) PRIMARY KEY,  -- Spotify track ID
    name         VARCHAR(500) NOT NULL,
    artist_names VARCHAR(500),
    album_name   VARCHAR(500),
    duration_ms  INTEGER,
    preview_url  TEXT,                     -- Stored but not relied upon for feature extraction
    popularity   INTEGER,
    created_at   TIMESTAMPTZ DEFAULT now()
);
```

---

### `track_features`
42-dimensional audio feature vector per track, extracted via yt-dlp + librosa.

```sql
CREATE TABLE track_features (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    track_id           VARCHAR(50) REFERENCES tracks(id) ON DELETE CASCADE,

    -- ── librosa features (yt-dlp audio source) ───────────────────
    -- MFCCs: timbral texture
    mfcc_mean          JSONB,        -- float[13] — per-coefficient mean
    mfcc_std           JSONB,        -- float[13] — per-coefficient std dev

    -- Chroma: harmonic/pitch class content
    chroma_mean        JSONB,        -- float[12] — mean per pitch class

    -- Spectral: brightness and noisiness
    spectral_centroid  FLOAT,        -- Hz — higher = brighter sound
    zero_crossing_rate FLOAT,        -- 0.0–1.0 — higher = noisier/more percussive
    rms_energy         FLOAT,        -- RMS amplitude — loudness proxy

    -- Rhythm
    tempo_librosa      FLOAT,        -- BPM — primary energy indicator

    -- ── pgvector embedding (Phase 3) ─────────────────────────────
    -- Populated after emotion classifier training
    embedding          vector(42),   -- 42-dim feature vector for similarity search

    created_at         TIMESTAMPTZ DEFAULT now(),
    updated_at         TIMESTAMPTZ DEFAULT now(),
    UNIQUE(track_id)
);

CREATE INDEX idx_track_features_embedding
    ON track_features USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

**Why not Spotify Audio Features (valence, energy, danceability)?**
Spotify's `/audio-features` endpoint returns 403 Forbidden in Development Mode
and was deprecated for new apps in 2025 (Extended Quota requires 250k MAU).
The librosa pipeline extracts equivalent or richer features directly from audio.

---

### `track_emotions`
ML-predicted emotion labels per track (populated in Phase 3).

```sql
CREATE TABLE track_emotions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    track_id       VARCHAR(50) REFERENCES tracks(id) ON DELETE CASCADE,
    emotion        VARCHAR(50) NOT NULL,   -- primary emotion label
    confidence     FLOAT NOT NULL,         -- 0.0 – 1.0
    emotion_scores JSONB,                  -- scores for all 12 classes
    model_version  VARCHAR(50),
    predicted_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(track_id, model_version)
);

CREATE INDEX idx_track_emotions_emotion  ON track_emotions(emotion);
CREATE INDEX idx_track_emotions_track_id ON track_emotions(track_id);
```

---

### `emotion_nodes`
The 12 nodes in the emotion graph.

```sql
CREATE TABLE emotion_nodes (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(50) UNIQUE NOT NULL,
    display_name  VARCHAR(100),
    description   TEXT,
    -- Feature space ranges (derived from librosa features, not Spotify features)
    tempo_range   FLOAT[2],    -- [min_bpm, max_bpm]
    energy_range  FLOAT[2],    -- [min_rms, max_rms]
    color_hex     VARCHAR(7),  -- UI color
    centroid      vector(42)   -- 42-dim feature space centroid
);

INSERT INTO emotion_nodes (name, display_name, tempo_range, energy_range, color_hex) VALUES
    ('energetic',   'Energetic',   '{140, 200}', '{0.08, 0.20}', '#FF6B35'),
    ('happy',       'Happy',       '{110, 160}', '{0.05, 0.15}', '#FFD700'),
    ('euphoric',    'Euphoric',    '{130, 180}', '{0.10, 0.20}', '#FF69B4'),
    ('peaceful',    'Peaceful',    '{60,  100}', '{0.01, 0.05}', '#7EC8E3'),
    ('focused',     'Focused',     '{90,  130}', '{0.03, 0.10}', '#6B8CFF'),
    ('romantic',    'Romantic',    '{70,  110}', '{0.02, 0.08}', '#FF85A1'),
    ('nostalgic',   'Nostalgic',   '{70,  110}', '{0.02, 0.08}', '#C3A6FF'),
    ('neutral',     'Neutral',     '{80,  120}', '{0.02, 0.08}', '#9E9E9E'),
    ('melancholic', 'Melancholic', '{60,  100}', '{0.01, 0.06}', '#5B6EFF'),
    ('sad',         'Sad',         '{50,  90}',  '{0.01, 0.05}', '#4A90D9'),
    ('tense',       'Tense',       '{120, 170}', '{0.06, 0.15}', '#FF4444'),
    ('angry',       'Angry',       '{140, 190}', '{0.08, 0.18}', '#CC0000');
```

---

### `emotion_edges`
Directed transitions between emotion nodes with perceptual distance weights.

```sql
CREATE TABLE emotion_edges (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_emotion VARCHAR(50) REFERENCES emotion_nodes(name),
    target_emotion VARCHAR(50) REFERENCES emotion_nodes(name),
    weight         FLOAT NOT NULL,     -- lower = smoother transition
    bidirectional  BOOLEAN DEFAULT false,
    UNIQUE(source_emotion, target_emotion)
);

CREATE INDEX idx_emotion_edges_source ON emotion_edges(source_emotion);
```

---

### `sessions`
User listening sessions.

```sql
CREATE TABLE sessions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID REFERENCES users(id) ON DELETE CASCADE,
    source_emotion VARCHAR(50) NOT NULL,
    target_emotion VARCHAR(50) NOT NULL,
    duration_mins  INTEGER NOT NULL,
    status         VARCHAR(20) DEFAULT 'generated',  -- generated|active|completed|abandoned
    arc_path       TEXT[],             -- ordered emotion node names
    created_at     TIMESTAMPTZ DEFAULT now(),
    started_at     TIMESTAMPTZ,
    completed_at   TIMESTAMPTZ
);

CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_status  ON sessions(status);
```

---

### `session_tracks`
Ordered tracks within a session.

```sql
CREATE TABLE session_tracks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID REFERENCES sessions(id) ON DELETE CASCADE,
    track_id     VARCHAR(50) REFERENCES tracks(id),
    position     INTEGER NOT NULL,
    emotion_label VARCHAR(50),
    arc_segment  INTEGER,
    played       BOOLEAN DEFAULT false,
    skipped      BOOLEAN DEFAULT false,
    played_at    TIMESTAMPTZ,
    UNIQUE(session_id, position)
);

CREATE INDEX idx_session_tracks_session_id ON session_tracks(session_id);
```

---

### `user_tracks`
Junction table: tracks seeded into a user's library via the Airflow pipeline.

```sql
CREATE TABLE user_tracks (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID REFERENCES users(id) ON DELETE CASCADE,
    track_id   VARCHAR(50) REFERENCES tracks(id) ON DELETE CASCADE,
    saved_at   TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, track_id)
);
```

---

## ERD

```
users ──────────────── user_tracks ──────────── tracks
  │                                                │
  │                                        track_features   ← yt-dlp + librosa
  │                                        track_emotions   ← ML classifier (Phase 3)
  │
  └── sessions ──── session_tracks ──── tracks

emotion_nodes ── emotion_edges ── emotion_nodes
```

---

## Migration Strategy

Using **Alembic** for version-controlled migrations.

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
```
