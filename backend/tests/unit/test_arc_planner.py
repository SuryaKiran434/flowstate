"""
Unit tests for ArcPlanner service.

Run with:
    pytest tests/unit/test_arc_planner.py -v
"""

import pytest
from uuid import uuid4

from app.services.arc_planner import ArcPlanner, TrackCandidate


# ─── Fixtures ────────────────────────────────────────────────────────────────

def make_track(emotion: str, energy: float = 0.5, confidence: float = 0.8) -> TrackCandidate:
    return TrackCandidate(
        track_id=uuid4(),
        spotify_id=f"spotify_{uuid4().hex[:8]}",
        title=f"Track ({emotion})",
        artist="Test Artist",
        duration_ms=210_000,
        emotion_label=emotion,
        emotion_confidence=confidence,
        energy=energy,
        valence=0.5,
        tempo=120.0,
    )


def make_pool(emotions: list[str], tracks_per_emotion: int = 10) -> list[TrackCandidate]:
    pool = []
    for emotion in emotions:
        for i in range(tracks_per_emotion):
            pool.append(make_track(emotion, energy=0.1 + i * 0.08))
    return pool


# ─── ArcPlanner.find_emotional_path ─────────────────────────────────────────

class TestFindEmotionalPath:

    def test_same_source_and_target(self):
        planner = ArcPlanner()
        path = planner.find_emotional_path("peaceful", "peaceful")
        assert path == ["peaceful"]

    def test_direct_neighbor_path(self):
        planner = ArcPlanner()
        path = planner.find_emotional_path("neutral", "peaceful")
        assert path[0] == "neutral"
        assert path[-1] == "peaceful"
        assert len(path) >= 2

    def test_multi_hop_path(self):
        planner = ArcPlanner()
        path = planner.find_emotional_path("tense", "peaceful")
        assert path[0] == "tense"
        assert path[-1] == "peaceful"
        assert len(path) >= 3  # should require intermediate nodes

    def test_all_nodes_reachable(self):
        planner = ArcPlanner()
        emotions = list(planner.graph.keys())
        for source in emotions:
            for target in emotions:
                path = planner.find_emotional_path(source, target)
                assert path[0] == source
                assert path[-1] == target

    def test_unknown_source_raises(self):
        planner = ArcPlanner()
        with pytest.raises(ValueError, match="Unknown source emotion"):
            planner.find_emotional_path("unknown_emotion", "peaceful")

    def test_unknown_target_raises(self):
        planner = ArcPlanner()
        with pytest.raises(ValueError, match="Unknown target emotion"):
            planner.find_emotional_path("peaceful", "unknown_emotion")

    def test_path_contains_only_valid_nodes(self):
        planner = ArcPlanner()
        valid_nodes = set(planner.graph.keys())
        path = planner.find_emotional_path("angry", "sad")
        for node in path:
            assert node in valid_nodes


# ─── ArcPlanner.plan ─────────────────────────────────────────────────────────

class TestPlan:

    def test_returns_expected_structure(self):
        planner = ArcPlanner()
        pool = make_pool(["tense", "neutral", "focused", "peaceful"])
        result = planner.plan("tense", "peaceful", 45, pool)

        assert "arc_path" in result
        assert "segments" in result
        assert "tracks" in result
        assert "total_tracks" in result

    def test_arc_path_starts_and_ends_correctly(self):
        planner = ArcPlanner()
        pool = make_pool(["tense", "neutral", "focused", "peaceful"])
        result = planner.plan("tense", "peaceful", 45, pool)

        assert result["arc_path"][0] == "tense"
        assert result["arc_path"][-1] == "peaceful"

    def test_no_duplicate_tracks(self):
        planner = ArcPlanner()
        pool = make_pool(["happy", "neutral", "peaceful"], tracks_per_emotion=20)
        result = planner.plan("happy", "peaceful", 30, pool)

        track_ids = [t.track_id for t in result["tracks"]]
        assert len(track_ids) == len(set(track_ids)), "Duplicate tracks found in arc"

    def test_total_tracks_matches_flat_list(self):
        planner = ArcPlanner()
        pool = make_pool(["energetic", "happy", "neutral"], tracks_per_emotion=15)
        result = planner.plan("energetic", "neutral", 30, pool)

        assert result["total_tracks"] == len(result["tracks"])

    def test_segments_cover_full_arc_path(self):
        planner = ArcPlanner()
        pool = make_pool(["tense", "neutral", "focused", "peaceful"], tracks_per_emotion=15)
        result = planner.plan("tense", "peaceful", 45, pool)

        segment_emotions = [s["emotion"] for s in result["segments"]]
        assert segment_emotions == result["arc_path"]

    def test_short_duration_still_returns_tracks(self):
        planner = ArcPlanner()
        pool = make_pool(["happy", "peaceful"], tracks_per_emotion=10)
        result = planner.plan("happy", "peaceful", 10, pool)

        assert result["total_tracks"] >= 2

    def test_same_emotion_arc(self):
        planner = ArcPlanner()
        pool = make_pool(["peaceful"], tracks_per_emotion=15)
        result = planner.plan("peaceful", "peaceful", 20, pool)

        assert result["arc_path"] == ["peaceful"]
        assert result["total_tracks"] >= 1


# ─── ArcPlanner._compute_energy_directions ───────────────────────────────────

class TestEnergyDirections:

    def test_descending_path_has_descending_directions(self):
        planner = ArcPlanner()
        # energetic -> peaceful should be mostly descending
        path = ["energetic", "neutral", "peaceful"]
        directions = planner._compute_energy_directions(path)

        assert "descending" in directions

    def test_last_segment_is_always_neutral(self):
        planner = ArcPlanner()
        path = ["tense", "neutral", "peaceful"]
        directions = planner._compute_energy_directions(path)

        assert directions[-1] == "neutral"

    def test_single_node_path(self):
        planner = ArcPlanner()
        path = ["peaceful"]
        directions = planner._compute_energy_directions(path)

        assert directions == ["neutral"]
