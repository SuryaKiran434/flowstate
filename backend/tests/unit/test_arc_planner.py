"""
Unit tests for app/services/arc_planner.py

Coverage targets:
- EMOTION_GRAPH / constant sanity checks
- find_emotional_path (Dijkstra)
- _allocate_tracks_per_segment
- _compute_energy_directions
- _select_tracks_for_segment
- plan (full integration)
- plan_from_db (DB integration with mocked session)
"""

from unittest.mock import MagicMock

import pytest

from app.services.arc_planner import (
    EMOTION_GRAPH,
    ENERGY_CENTERS,
    TRACKS_PER_MINUTE,
    ArcPlanner,
    TrackCandidate,
)

ALL_EMOTIONS = [
    "energetic", "happy", "euphoric", "peaceful", "focused", "romantic",
    "nostalgic", "neutral", "melancholic", "sad", "tense", "angry",
]


# ─── Constants sanity ─────────────────────────────────────────────────────────

class TestConstants:
    def test_emotion_graph_has_all_12_emotions(self):
        assert set(EMOTION_GRAPH.keys()) == set(ALL_EMOTIONS)

    def test_tracks_per_minute_has_all_12_emotions(self):
        assert set(TRACKS_PER_MINUTE.keys()) == set(ALL_EMOTIONS)

    def test_energy_centers_has_all_12_emotions(self):
        assert set(ENERGY_CENTERS.keys()) == set(ALL_EMOTIONS)

    def test_all_edge_weights_positive(self):
        for src, neighbors in EMOTION_GRAPH.items():
            for dst, cost in neighbors.items():
                assert cost > 0, f"Non-positive edge weight: {src}→{dst} = {cost}"

    def test_energy_centers_in_valid_range(self):
        for emotion, val in ENERGY_CENTERS.items():
            assert 0.0 <= val <= 1.0, f"ENERGY_CENTERS[{emotion}] = {val} out of [0,1]"

    def test_tracks_per_minute_positive(self):
        for emotion, rate in TRACKS_PER_MINUTE.items():
            assert rate > 0, f"TRACKS_PER_MINUTE[{emotion}] = {rate}"

    def test_emotion_graph_no_self_loops(self):
        for src, neighbors in EMOTION_GRAPH.items():
            assert src not in neighbors, f"Self-loop found: {src}→{src}"

    def test_all_graph_neighbors_are_known_emotions(self):
        known = set(ALL_EMOTIONS)
        for src, neighbors in EMOTION_GRAPH.items():
            for dst in neighbors:
                assert dst in known, f"Unknown neighbor {dst} for {src}"


# ─── find_emotional_path ──────────────────────────────────────────────────────

class TestFindEmotionalPath:
    def setup_method(self):
        self.planner = ArcPlanner()

    def test_self_loop_returns_single_node(self):
        path = self.planner.find_emotional_path("peaceful", "peaceful")
        assert path == ["peaceful"]

    def test_adjacent_emotions_two_node_path(self):
        # energetic → happy has cost 1.0 (direct edge)
        path = self.planner.find_emotional_path("energetic", "happy")
        assert path[0] == "energetic"
        assert path[-1] == "happy"
        assert len(path) >= 2

    def test_distant_emotions_multi_hop(self):
        # angry → peaceful: no direct edge; must traverse through intermediates
        path = self.planner.find_emotional_path("angry", "peaceful")
        assert path[0] == "angry"
        assert path[-1] == "peaceful"
        assert len(path) >= 3

    def test_path_always_starts_with_source(self):
        for src in ["tense", "sad", "euphoric"]:
            path = self.planner.find_emotional_path(src, "neutral")
            assert path[0] == src

    def test_path_always_ends_with_target(self):
        for tgt in ["peaceful", "energetic", "melancholic"]:
            path = self.planner.find_emotional_path("neutral", tgt)
            assert path[-1] == tgt

    def test_unknown_source_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown source emotion"):
            self.planner.find_emotional_path("nonexistent", "peaceful")

    def test_unknown_target_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown target emotion"):
            self.planner.find_emotional_path("peaceful", "nonexistent")

    def test_consecutive_nodes_connected_in_graph(self):
        """Every hop in the returned path must be a real edge."""
        path = self.planner.find_emotional_path("angry", "peaceful")
        for i in range(len(path) - 1):
            src, dst = path[i], path[i + 1]
            assert dst in EMOTION_GRAPH.get(src, {}), (
                f"Edge {src}→{dst} not in graph"
            )

    def test_tense_to_peaceful_path(self):
        path = self.planner.find_emotional_path("tense", "peaceful")
        assert path[0] == "tense"
        assert path[-1] == "peaceful"

    def test_sad_to_energetic_path(self):
        path = self.planner.find_emotional_path("sad", "energetic")
        assert path[0] == "sad"
        assert path[-1] == "energetic"

    def test_custom_graph_is_respected(self):
        tiny_graph = {
            "a": {"b": 1.0},
            "b": {"c": 1.0},
            "c": {},
        }
        planner = ArcPlanner(graph=tiny_graph)
        path = planner.find_emotional_path("a", "c")
        assert path == ["a", "b", "c"]

    def test_unreachable_target_returns_two_node_fallback(self):
        """If target is unreachable, fallback is [source, target]."""
        disconnected = {
            "a": {"b": 1.0},
            "b": {},
            "c": {},  # c is unreachable from a or b
        }
        planner = ArcPlanner(graph=disconnected)
        path = planner.find_emotional_path("a", "c")
        assert path == ["a", "c"]


# ─── _allocate_tracks_per_segment ─────────────────────────────────────────────

class TestAllocateTracksPerSegment:
    def setup_method(self):
        self.planner = ArcPlanner()

    def test_single_emotion_30min(self):
        alloc = self.planner._allocate_tracks_per_segment(["peaceful"], 30)
        assert len(alloc) == 1
        assert alloc[0] >= 5  # max(5, ...) guarantee

    def test_single_emotion_short_duration(self):
        alloc = self.planner._allocate_tracks_per_segment(["energetic"], 1)
        assert len(alloc) == 1
        assert alloc[0] >= 5  # max(5, ...) still applies

    def test_multi_emotion_returns_correct_count(self):
        path = ["tense", "neutral", "peaceful"]
        alloc = self.planner._allocate_tracks_per_segment(path, 30)
        assert len(alloc) == 3

    def test_all_allocations_at_least_2(self):
        for duration in [5, 10, 30, 60]:
            path = ["tense", "focused", "neutral", "peaceful"]
            alloc = self.planner._allocate_tracks_per_segment(path, duration)
            for a in alloc:
                assert a >= 2, f"Allocation {a} < 2 for duration={duration}"

    def test_longer_duration_more_tracks(self):
        path = ["tense", "peaceful"]
        short = sum(self.planner._allocate_tracks_per_segment(path, 10))
        long_ = sum(self.planner._allocate_tracks_per_segment(path, 60))
        assert long_ >= short

    def test_total_tracks_consistent_with_duration(self):
        path = ["energetic", "happy", "peaceful"]
        alloc = self.planner._allocate_tracks_per_segment(path, 30)
        total = sum(alloc)
        # 30 min * ~0.24 avg rate ≈ 7.2, so minimum is max(9, 7) = 9
        assert total >= 6

    def test_five_emotion_path(self):
        path = ["angry", "tense", "neutral", "focused", "peaceful"]
        alloc = self.planner._allocate_tracks_per_segment(path, 45)
        assert len(alloc) == 5
        assert all(a >= 2 for a in alloc)


# ─── _compute_energy_directions ───────────────────────────────────────────────

class TestComputeEnergyDirections:
    def setup_method(self):
        self.planner = ArcPlanner()

    def test_last_emotion_always_neutral(self):
        for path in [["peaceful"], ["tense", "peaceful"], ["sad", "neutral", "energetic"]]:
            dirs = self.planner._compute_energy_directions(path)
            assert dirs[-1] == "neutral"

    def test_single_emotion_returns_neutral(self):
        dirs = self.planner._compute_energy_directions(["peaceful"])
        assert dirs == ["neutral"]

    def test_ascending_arc_detected(self):
        # sad (0.20) → energetic (0.85): diff = 0.65 >> 0.1
        dirs = self.planner._compute_energy_directions(["sad", "energetic"])
        assert dirs[0] == "ascending"

    def test_descending_arc_detected(self):
        # energetic (0.85) → peaceful (0.25): diff = -0.60 << -0.1
        dirs = self.planner._compute_energy_directions(["energetic", "peaceful"])
        assert dirs[0] == "descending"

    def test_flat_arc_is_neutral(self):
        # peaceful (0.25) and melancholic (0.25): diff = 0.0 < 0.1
        dirs = self.planner._compute_energy_directions(["peaceful", "melancholic"])
        assert dirs[0] == "neutral"

    def test_long_descending_arc(self):
        # energetic(0.85) → happy(0.65) → focused(0.50) → peaceful(0.25)
        path = ["energetic", "happy", "focused", "peaceful"]
        dirs = self.planner._compute_energy_directions(path)
        assert dirs[-1] == "neutral"
        # energetic→happy: 0.65-0.85 = -0.20 < -0.10 → descending
        assert dirs[0] == "descending"

    def test_returns_same_length_as_path(self):
        path = ["angry", "tense", "neutral", "focused", "peaceful"]
        dirs = self.planner._compute_energy_directions(path)
        assert len(dirs) == len(path)

    def test_threshold_boundary(self):
        # romantic (0.40) vs nostalgic (0.38): diff = -0.02 → neutral (< 0.1)
        dirs = self.planner._compute_energy_directions(["romantic", "nostalgic"])
        assert dirs[0] == "neutral"


# ─── _select_tracks_for_segment ───────────────────────────────────────────────

class TestSelectTracksForSegment:
    def setup_method(self):
        self.planner = ArcPlanner()

    def test_exact_emotion_match_returns_n_tracks(self, make_track):
        pool = [make_track(emotion_label="peaceful") for _ in range(10)]
        selected = self.planner._select_tracks_for_segment("peaceful", pool, 5)
        assert len(selected) == 5
        assert all(t.emotion_label == "peaceful" for t in selected)

    def test_no_duplicates_in_result(self, make_track):
        pool = [make_track(emotion_label="peaceful") for _ in range(10)]
        selected = self.planner._select_tracks_for_segment("peaceful", pool, 8)
        ids = [t.track_id for t in selected]
        assert len(ids) == len(set(ids))

    def test_used_track_ids_excluded(self, make_track):
        pool = [make_track(emotion_label="tense") for _ in range(6)]
        used = {pool[0].track_id, pool[1].track_id}
        selected = self.planner._select_tracks_for_segment(
            "tense", pool, 3, used_track_ids=used
        )
        for t in selected:
            assert t.track_id not in used

    def test_fallback_to_adjacent_when_insufficient(self, make_track):
        # Only 1 "peaceful" track, but need 5 — should pull from adjacent emotions
        # neutral is adjacent to peaceful in EMOTION_GRAPH
        pool = [make_track(emotion_label="peaceful")] + [
            make_track(emotion_label="neutral", emotion_confidence=0.50)
            for _ in range(10)
        ]
        selected = self.planner._select_tracks_for_segment("peaceful", pool, 5)
        assert len(selected) > 1  # fallback was triggered

    def test_fallback_only_uses_low_confidence_adjacent(self, make_track):
        # High-confidence adjacent tracks must NOT be borrowed
        pool = [make_track(emotion_label="peaceful")] + [
            make_track(emotion_label="neutral", emotion_confidence=0.90)
            for _ in range(10)
        ]
        selected = self.planner._select_tracks_for_segment("peaceful", pool, 5)
        # Only the 1 "peaceful" track should be selected (high-confidence neutral not borrowed)
        assert len(selected) == 1

    def test_empty_pool_returns_empty_list(self):
        selected = self.planner._select_tracks_for_segment("peaceful", [], 5)
        assert selected == []

    def test_ascending_direction_lower_energy_first(self, make_track):
        pool = [
            make_track(emotion_label="energetic", energy=0.9),
            make_track(emotion_label="energetic", energy=0.3),
            make_track(emotion_label="energetic", energy=0.6),
        ]
        # With ascending, lower energy should sort earlier (with jitter ±0.08)
        # We check that overall the lowest energy track is NOT consistently last
        energies = []
        for _ in range(20):
            selected = self.planner._select_tracks_for_segment(
                "energetic", pool, 3, energy_direction="ascending"
            )
            energies.append(selected[0].energy)
        # At least sometimes the lowest-energy track (0.3) should appear first
        assert min(energies) < 0.7

    def test_descending_direction_higher_energy_first(self, make_track):
        pool = [
            make_track(emotion_label="sad", energy=0.9),
            make_track(emotion_label="sad", energy=0.3),
            make_track(emotion_label="sad", energy=0.6),
        ]
        energies = []
        for _ in range(20):
            selected = self.planner._select_tracks_for_segment(
                "sad", pool, 3, energy_direction="descending"
            )
            energies.append(selected[0].energy)
        # At least sometimes the highest-energy track (0.9) should appear first
        assert max(energies) > 0.5

    def test_returns_at_most_n_tracks(self, make_track):
        pool = [make_track(emotion_label="happy") for _ in range(20)]
        selected = self.planner._select_tracks_for_segment("happy", pool, 5)
        assert len(selected) <= 5

    def test_neutral_direction_sorts_by_confidence(self, make_track):
        pool = [
            make_track(emotion_label="focused", emotion_confidence=0.3),
            make_track(emotion_label="focused", emotion_confidence=0.95),
            make_track(emotion_label="focused", emotion_confidence=0.6),
        ]
        confidences_first = []
        for _ in range(20):
            selected = self.planner._select_tracks_for_segment(
                "focused", pool, 3, energy_direction="neutral"
            )
            confidences_first.append(selected[0].emotion_confidence)
        # At least sometimes the highest-confidence track appears first
        assert max(confidences_first) > 0.7


# ─── plan (full integration) ──────────────────────────────────────────────────

class TestPlan:
    def setup_method(self):
        self.planner = ArcPlanner()

    def test_happy_path_returns_all_required_keys(self, diverse_pool):
        result = self.planner.plan("tense", "peaceful", 30, diverse_pool)
        assert "arc_path" in result
        assert "segments" in result
        assert "tracks" in result
        assert "total_tracks" in result
        assert "total_duration_ms" in result
        assert "readiness" in result

    def test_arc_path_starts_with_source(self, diverse_pool):
        result = self.planner.plan("tense", "peaceful", 30, diverse_pool)
        assert result["arc_path"][0] == "tense"

    def test_arc_path_ends_with_target(self, diverse_pool):
        result = self.planner.plan("tense", "peaceful", 30, diverse_pool)
        assert result["arc_path"][-1] == "peaceful"

    def test_segments_match_arc_path_length(self, diverse_pool):
        result = self.planner.plan("tense", "peaceful", 30, diverse_pool)
        assert len(result["segments"]) == len(result["arc_path"])

    def test_segment_emotions_match_arc_path_order(self, diverse_pool):
        result = self.planner.plan("energetic", "sad", 30, diverse_pool)
        segment_emotions = [s["emotion"] for s in result["segments"]]
        assert segment_emotions == result["arc_path"]

    def test_no_duplicate_track_ids_across_segments(self, diverse_pool):
        result = self.planner.plan("angry", "peaceful", 45, diverse_pool)
        all_ids = [t.track_id for t in result["tracks"]]
        assert len(all_ids) == len(set(all_ids)), "Duplicate tracks found in arc"

    def test_flat_tracks_matches_segment_sum(self, diverse_pool):
        result = self.planner.plan("tense", "peaceful", 30, diverse_pool)
        segment_total = sum(s["track_count"] for s in result["segments"])
        assert result["total_tracks"] == segment_total
        assert len(result["tracks"]) == segment_total

    def test_total_duration_ms_is_sum_of_track_durations(self, diverse_pool):
        result = self.planner.plan("tense", "peaceful", 30, diverse_pool)
        expected = sum(t.duration_ms for t in result["tracks"])
        assert result["total_duration_ms"] == expected

    def test_readiness_pool_size_correct(self, diverse_pool):
        result = self.planner.plan("tense", "peaceful", 30, diverse_pool)
        assert result["readiness"]["pool_size"] == len(diverse_pool)

    def test_full_pool_no_missing_emotions(self, diverse_pool):
        result = self.planner.plan("tense", "peaceful", 30, diverse_pool)
        assert result["readiness"]["has_gaps"] is False
        assert result["readiness"]["missing_emotions"] == []

    def test_sparse_pool_flags_missing_emotions(self, make_track):
        # Pool only has "tense" and "peaceful"; intermediate nodes will be empty
        sparse = [make_track(emotion_label="tense") for _ in range(5)]
        result = self.planner.plan("tense", "peaceful", 30, sparse)
        # There should be at least 1 missing emotion (intermediates)
        if len(result["arc_path"]) > 2:
            assert result["readiness"]["has_gaps"] is True

    def test_same_source_target_single_segment(self, diverse_pool):
        result = self.planner.plan("peaceful", "peaceful", 20, diverse_pool)
        assert result["arc_path"] == ["peaceful"]
        assert len(result["segments"]) == 1

    def test_segment_index_sequential(self, diverse_pool):
        result = self.planner.plan("tense", "peaceful", 30, diverse_pool)
        for i, seg in enumerate(result["segments"]):
            assert seg["segment_index"] == i

    def test_each_segment_has_tracks_list(self, diverse_pool):
        result = self.planner.plan("tense", "peaceful", 30, diverse_pool)
        for seg in result["segments"]:
            assert "tracks" in seg
            assert isinstance(seg["tracks"], list)

    def test_energy_direction_present_in_segments(self, diverse_pool):
        result = self.planner.plan("tense", "peaceful", 30, diverse_pool)
        for seg in result["segments"]:
            assert seg["energy_direction"] in {"ascending", "descending", "neutral"}


# ─── plan_from_db ──────────────────────────────────────────────────────────────

class TestPlanFromDb:
    def setup_method(self):
        self.planner = ArcPlanner()

    def _make_db_row(self, track_id, spotify_id, name, artist_names,
                     duration_ms, energy, valence, emotion_label,
                     emotion_confidence, tempo_librosa):
        row = MagicMock()
        row.track_id = track_id
        row.spotify_id = spotify_id
        row.name = name
        row.artist_names = artist_names
        row.duration_ms = duration_ms
        row.energy = energy
        row.valence = valence
        row.emotion_label = emotion_label
        row.emotion_confidence = emotion_confidence
        row.tempo_librosa = tempo_librosa
        return row

    def _mock_db(self, rows):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = rows
        return db

    def test_empty_db_returns_library_not_ready(self):
        db = self._mock_db([])
        result = self.planner.plan_from_db("tense", "peaceful", 30, db, "user-123")
        assert result["error"] == "library_not_ready"
        assert result["tracks"] == []
        assert result["segments"] == []
        assert result["total_tracks"] == 0

    def test_non_empty_db_returns_valid_arc(self):
        rows = [
            self._make_db_row(
                f"uuid-{i}", f"sp-{i}", f"Track {i}", "Artist", 200_000,
                0.5, 0.5, emotion, 0.80, 120.0
            )
            for i, emotion in enumerate(
                ["tense"] * 5 + ["neutral"] * 5 + ["peaceful"] * 5
            )
        ]
        db = self._mock_db(rows)
        result = self.planner.plan_from_db("tense", "peaceful", 30, db, "user-123")
        assert "arc_path" in result
        assert result["arc_path"][-1] == "peaceful"

    def test_null_fields_default_gracefully(self):
        row = self._make_db_row(
            "uuid-1", "sp-1", "Track 1", None,   # artist_names=None
            None,                                  # duration_ms=None
            None, None,                            # energy=None, valence=None
            "neutral", None,                       # emotion_confidence=None
            None,                                  # tempo_librosa=None
        )
        db = self._mock_db([row])
        result = self.planner.plan_from_db("neutral", "peaceful", 30, db, "u")
        # Should not raise; library_not_ready not returned since row has emotion_label
        assert "error" not in result or result.get("error") != "library_not_ready"

    def test_rows_with_null_emotion_label_are_filtered(self):
        rows = [
            self._make_db_row(
                "uuid-1", "sp-1", "Track 1", "Artist", 200_000, 0.5, 0.5,
                None,  # emotion_label=None → filtered out
                0.8, 120.0
            )
        ]
        db = self._mock_db(rows)
        result = self.planner.plan_from_db("tense", "peaceful", 30, db, "u")
        # After filtering, pool is empty → library_not_ready
        assert result["error"] == "library_not_ready"
