"""
Shared pytest fixtures for Flowstate unit tests.
"""

import pytest
from unittest.mock import MagicMock

from app.services.arc_planner import TrackCandidate


@pytest.fixture
def make_track():
    """
    Factory fixture. Returns a callable that builds a TrackCandidate.
    Each call auto-increments the counter so track_ids are unique by default.
    """
    counter = {"n": 0}

    def _make(
        track_id=None,
        spotify_id=None,
        title=None,
        artist="Test Artist",
        duration_ms=210_000,        # 3.5 minutes
        emotion_label="neutral",
        emotion_confidence=0.80,
        energy=0.50,
        valence=0.50,
        tempo=120.0,
    ) -> TrackCandidate:
        counter["n"] += 1
        n = counter["n"]
        return TrackCandidate(
            track_id=track_id or f"uuid-{n:04d}",
            spotify_id=spotify_id or f"spotify{n:04d}",
            title=title or f"Track {n}",
            artist=artist,
            duration_ms=duration_ms,
            emotion_label=emotion_label,
            emotion_confidence=emotion_confidence,
            energy=energy,
            valence=valence,
            tempo=tempo,
        )

    return _make


@pytest.fixture
def diverse_pool(make_track):
    """
    36-track pool: 3 tracks per emotion, covering all 12 emotions.
    Each track gets a unique track_id.
    """
    all_emotions = [
        "energetic", "happy", "euphoric", "peaceful", "focused", "romantic",
        "nostalgic", "neutral", "melancholic", "sad", "tense", "angry",
    ]
    pool = []
    energy_map = {
        "energetic": 0.85, "euphoric": 0.85, "angry": 0.85, "tense": 0.75,
        "happy": 0.65, "focused": 0.50, "neutral": 0.45, "romantic": 0.40,
        "nostalgic": 0.38, "peaceful": 0.25, "melancholic": 0.25, "sad": 0.20,
    }
    for emotion in all_emotions:
        for _ in range(3):
            pool.append(make_track(
                emotion_label=emotion,
                emotion_confidence=0.85,
                energy=energy_map[emotion],
            ))
    return pool


@pytest.fixture
def mock_settings_with_key():
    """Pydantic Settings mock with a valid Anthropic API key."""
    s = MagicMock()
    s.anthropic_api_key = "sk-ant-test-key"
    return s


@pytest.fixture
def mock_settings_no_key():
    """Pydantic Settings mock with no Anthropic API key (fallback path)."""
    s = MagicMock()
    s.anthropic_api_key = ""
    return s
