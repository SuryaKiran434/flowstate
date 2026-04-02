"""
Track ORM Models — Flowstate
------------------------------
Three tables:
  - Track:        Spotify track metadata (ID, name, artist, album, duration)
  - TrackFeature: Audio features extracted by yt-dlp + librosa pipeline
  - UserTrack:    Junction table linking users to their discovered tracks

Audio feature source: yt-dlp (YouTube) → librosa
  NOT Spotify Audio Features API — that endpoint is blocked in Development Mode
  and deprecated for new apps. The librosa pipeline works for all languages
  and music markets (Telugu, Tamil, Hindi, English, etc.)
"""

import uuid
from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey, func, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.session import Base


class Track(Base):
    __tablename__ = "tracks"

    id = Column(String(50), primary_key=True)  # Spotify track ID
    name = Column(String(500), nullable=False)
    artist_names = Column(String(500), nullable=True)
    album_name = Column(String(500), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    preview_url = Column(Text, nullable=True)  # Stored but not relied upon
    popularity = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TrackFeature(Base):
    """
    42-dimensional audio feature vector extracted via yt-dlp + librosa.

    Feature breakdown:
      mfcc_mean (13)       — timbral texture averages
      mfcc_std  (13)       — timbral texture variance
      chroma_mean (12)     — harmonic/pitch class content
      spectral_centroid (1)— brightness (high = bright/tinny, low = warm)
      zero_crossing_rate(1)— noisiness / percussiveness
      rms_energy (1)       — loudness proxy
      tempo_librosa (1)    — BPM, primary energy indicator

    Spotify Audio Features (valence, energy, danceability, etc.) are intentionally
    absent — those endpoints are blocked in Development Mode and deprecated for
    new apps. This pipeline computes equivalent or richer features independently.
    """

    __tablename__ = "track_features"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    track_id = Column(
        String(50), ForeignKey("tracks.id"), nullable=False, unique=True, index=True
    )

    # ── librosa features (yt-dlp audio source) ────────────────────
    mfcc_mean = Column(JSONB, nullable=True)  # list[float] len=13
    mfcc_std = Column(JSONB, nullable=True)  # list[float] len=13
    chroma_mean = Column(JSONB, nullable=True)  # list[float] len=12
    spectral_centroid = Column(Float, nullable=True)  # Hz
    zero_crossing_rate = Column(Float, nullable=True)  # 0.0 – 1.0
    rms_energy = Column(Float, nullable=True)  # RMS amplitude
    tempo_librosa = Column(Float, nullable=True)  # BPM

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserTrack(Base):
    """Junction table: which users have which tracks in their seeded library."""

    __tablename__ = "user_tracks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    track_id = Column(String(50), ForeignKey("tracks.id"), nullable=False, index=True)
    saved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
