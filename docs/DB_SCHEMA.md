# Database Schema — Flowstate

## Overview

PostgreSQL 15 with the `pgvector` extension for similarity search on track embeddings.

---

## Tables

### `users`
Spotify user profiles synced at OAuth login.

```sql
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spotify_id      VARCHAR(255) UNIQUE NOT NULL,
    display_name    VARCHAR(255),
    email           VARCHAR(255),
    access_token    TEXT,               -- encrypted
    refresh_token   TEXT,               -- encrypted
    token_expires_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
```

---

### `tracks`
Core track metadata from Spotify.

```sql
CREATE TABLE tracks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spotify_id      VARCHAR(255) UNIQUE NOT NULL,
    title           VARCHAR(500) NOT NULL,
    artist          VARCHAR(500) NOT NULL,
    album           VARCHAR(500),
    duration_ms     INTEGER,
    preview_url     TEXT,               -- 30s clip URL
    language        VARCHAR(50),        -- e.g. 'te', 'ta', 'hi', 'en'
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_tracks_spotify_id ON tracks(spotify_id);
```

---

### `track_features`
Raw + derived audio features per track.

```sql
CREATE TABLE track_features (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    track_id            UUID REFERENCES tracks(id) ON DELETE CASCADE,
    -- Spotify Audio Features API
    valence             FLOAT,          -- 0.0 - 1.0 (sad to happy)
    energy              FLOAT,          -- 0.0 - 1.0 (calm to energetic)
    tempo               FLOAT,          -- BPM
    danceability        FLOAT,
    loudness            FLOAT,          -- dB
    acousticness        FLOAT,
    instrumentalness    FLOAT,
    speechiness         FLOAT,
    -- librosa derived features
    mfcc_mean           FLOAT[13],      -- MFCC means
    mfcc_std            FLOAT[13],      -- MFCC std devs
    chroma_mean         FLOAT[12],      -- Chroma means
    spectral_centroid   FLOAT,
    zero_crossing_rate  FLOAT,
    -- pgvector embedding for similarity search
    embedding           vector(50),
    extracted_at        TIMESTAMPTZ DEFAULT now(),
    UNIQUE(track_id)
);

CREATE INDEX idx_track_features_embedding
    ON track_features USING ivfflat (embedding vector_cosine_ops);
```

---

### `track_emotions`
ML-predicted emotion labels per track.

```sql
CREATE TABLE track_emotions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    track_id        UUID REFERENCES tracks(id) ON DELETE CASCADE,
    emotion         VARCHAR(50) NOT NULL,   -- primary emotion label
    confidence      FLOAT NOT NULL,         -- 0.0 - 1.0
    emotion_scores  JSONB,                  -- scores for all 12 classes
    model_version   VARCHAR(50),
    predicted_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(track_id, model_version)
);

CREATE INDEX idx_track_emotions_emotion ON track_emotions(emotion);
CREATE INDEX idx_track_emotions_track_id ON track_emotions(track_id);
```

---

### `emotion_nodes`
The 12 nodes in the emotion graph.

```sql
CREATE TABLE emotion_nodes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(50) UNIQUE NOT NULL,
    display_name    VARCHAR(100),
    description     TEXT,
    valence_range   FLOAT[2],   -- [min, max] expected valence
    energy_range    FLOAT[2],   -- [min, max] expected energy
    color_hex       VARCHAR(7), -- UI color
    centroid        vector(50)  -- feature space centroid
);

-- Seed data: 12 emotion nodes
INSERT INTO emotion_nodes (name, display_name, valence_range, energy_range, color_hex) VALUES
    ('energetic',   'Energetic',   '{0.6, 1.0}', '{0.7, 1.0}', '#FF6B35'),
    ('happy',       'Happy',       '{0.7, 1.0}', '{0.4, 0.8}', '#FFD700'),
    ('euphoric',    'Euphoric',    '{0.8, 1.0}', '{0.8, 1.0}', '#FF69B4'),
    ('peaceful',    'Peaceful',    '{0.5, 0.8}', '{0.0, 0.3}', '#7EC8E3'),
    ('focused',     'Focused',     '{0.4, 0.7}', '{0.3, 0.6}', '#6B8CFF'),
    ('romantic',    'Romantic',    '{0.5, 0.9}', '{0.2, 0.5}', '#FF85A1'),
    ('nostalgic',   'Nostalgic',   '{0.3, 0.6}', '{0.2, 0.5}', '#C3A6FF'),
    ('neutral',     'Neutral',     '{0.3, 0.6}', '{0.2, 0.5}', '#9E9E9E'),
    ('melancholic', 'Melancholic', '{0.1, 0.4}', '{0.1, 0.4}', '#5B6EFF'),
    ('sad',         'Sad',         '{0.0, 0.3}', '{0.0, 0.3}', '#4A90D9'),
    ('tense',       'Tense',       '{0.2, 0.5}', '{0.6, 0.9}', '#FF4444'),
    ('angry',       'Angry',       '{0.0, 0.3}', '{0.7, 1.0}', '#CC0000');
```

---

### `emotion_edges`
Directed transitions between emotion nodes with perceptual distance weights.

```sql
CREATE TABLE emotion_edges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_emotion  VARCHAR(50) REFERENCES emotion_nodes(name),
    target_emotion  VARCHAR(50) REFERENCES emotion_nodes(name),
    weight          FLOAT NOT NULL,     -- lower = smoother transition
    bidirectional   BOOLEAN DEFAULT false,
    UNIQUE(source_emotion, target_emotion)
);

CREATE INDEX idx_emotion_edges_source ON emotion_edges(source_emotion);
```

---

### `sessions`
User listening sessions.

```sql
CREATE TABLE sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    source_emotion  VARCHAR(50) NOT NULL,
    target_emotion  VARCHAR(50) NOT NULL,
    duration_mins   INTEGER NOT NULL,
    status          VARCHAR(20) DEFAULT 'generated',  -- generated|active|completed|abandoned
    arc_path        TEXT[],             -- ordered emotion node names
    created_at      TIMESTAMPTZ DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_status ON sessions(status);
```

---

### `session_tracks`
Ordered tracks within a session.

```sql
CREATE TABLE session_tracks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES sessions(id) ON DELETE CASCADE,
    track_id        UUID REFERENCES tracks(id),
    position        INTEGER NOT NULL,
    emotion_label   VARCHAR(50),
    arc_segment     INTEGER,            -- which segment of the arc this belongs to
    played          BOOLEAN DEFAULT false,
    skipped         BOOLEAN DEFAULT false,
    played_at       TIMESTAMPTZ,
    UNIQUE(session_id, position)
);

CREATE INDEX idx_session_tracks_session_id ON session_tracks(session_id);
```

---

### `user_tracks`
Junction table: which users have which tracks in their Spotify library.

```sql
CREATE TABLE user_tracks (
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    track_id        UUID REFERENCES tracks(id) ON DELETE CASCADE,
    added_at        TIMESTAMPTZ,        -- when added to Spotify library
    synced_at       TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, track_id)
);
```

---

## ERD (Text)

```
users ──────────────── user_tracks ──────────── tracks
  │                                                │
  │                                        track_features
  │                                        track_emotions
  │
  └── sessions ──── session_tracks ──── tracks

emotion_nodes ── emotion_edges ── emotion_nodes
```

---

## Migration Strategy

Using **Alembic** for version-controlled migrations.

```bash
# Create a new migration
alembic revision --autogenerate -m "add session_tracks table"

# Apply migrations
alembic upgrade head

# Roll back one step
alembic downgrade -1
```
