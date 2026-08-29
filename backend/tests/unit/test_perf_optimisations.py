"""
Unit tests — behaviour preservation for the arc/language performance work
=========================================================================

These tests exist to prove that a set of purely-performance changes did not
change what the system returns.  Each block names the optimisation it guards:

  1. load_track_pool_from_db  — no ORDER BY RANDOM() in the SQL
  2. find_emotional_path      — cached Floyd-Warshall replaces per-call Dijkstra
     resolve_replan_source    — distance-matrix lookup replaces N Dijkstras
  3. plan()                   — pool bucketed by emotion once, not per segment
  4. _select_tracks_for_segment — no dead shuffle, heapq top-k instead of sort
  5. language_detector.detect — ASCII fast path + lru_cache
  6. collab _shortest_distances — reuses the cached all-pairs matrix

The Dijkstra implementation that shipped before the change is reproduced here
verbatim as `_legacy_dijkstra_path` / `_legacy_shortest_distances` and used as
the oracle, so "same as before" is asserted against real old code rather than
against hand-copied expectations.
"""

import copy
import heapq
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

from app.services.arc_planner import (
    EMOTION_GRAPH,
    ArcPlanner,
    TrackCandidate,
    _all_pairs_shortest_paths,
    _graph_signature,
    all_pairs_shortest_paths,
)
from app.services.collab_service import CollabArcService, _shortest_distances
from app.services.language_detector import detect

ALL_EMOTIONS = sorted(EMOTION_GRAPH)


# ═══ Legacy implementations, kept as oracles ═════════════════════════════════


@dataclass(order=True)
class _LegacyPQEntry:
    cost: float
    node: str = field(compare=False)
    path: list = field(compare=False)


def _legacy_dijkstra_path(graph, source, target):
    """The pre-optimisation ArcPlanner.find_emotional_path body, verbatim."""
    if source == target:
        return [source]

    pq = [_LegacyPQEntry(cost=0.0, node=source, path=[source])]
    visited: dict = {}

    while pq:
        entry = heapq.heappop(pq)
        current_cost, current_node, path = entry.cost, entry.node, entry.path

        if current_node in visited and visited[current_node] <= current_cost:
            continue
        visited[current_node] = current_cost

        if current_node == target:
            return path

        for neighbor, edge_weight in graph.get(current_node, {}).items():
            new_cost = current_cost + edge_weight
            if neighbor not in visited or visited[neighbor] > new_cost:
                heapq.heappush(
                    pq,
                    _LegacyPQEntry(
                        cost=new_cost, node=neighbor, path=path + [neighbor]
                    ),
                )

    return [source, target]


def _legacy_shortest_distances(source, graph):
    """The pre-optimisation collab_service._shortest_distances body, verbatim."""
    dist = {e: float("inf") for e in graph}
    dist[source] = 0.0
    pq = [(0.0, source)]

    while pq:
        cost, node = heapq.heappop(pq)
        if cost > dist[node]:
            continue
        for neighbour, weight in graph.get(node, {}).items():
            new_cost = cost + weight
            if new_cost < dist.get(neighbour, float("inf")):
                dist[neighbour] = new_cost
                heapq.heappush(pq, (new_cost, neighbour))

    return dist


def _path_cost(graph, path):
    """Total edge weight of `path`, or inf if any hop is not a real edge."""
    if len(path) == 1:
        return 0.0
    total = 0.0
    for src, dst in zip(path, path[1:]):
        if dst not in graph.get(src, {}):
            return float("inf")
        total += graph[src][dst]
    return total


@pytest.fixture
def personalised_graph():
    """
    Stand-in for what GraphLearner.load_user_graph() hands back: the global
    graph with one edge re-weighted from this user's telemetry.  sad→neutral
    drops 3.0 → 0.1, which is enough to re-route several paths.
    """
    graph = copy.deepcopy(EMOTION_GRAPH)
    graph["sad"]["neutral"] = 0.1
    return graph


# ═══ 1. load_track_pool_from_db — ORDER BY RANDOM() removed ══════════════════


class TestNoOrderByRandom:
    def _mock_db(self, rows):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = rows
        return db

    def _row(self, name, artist, label, conf, spotify_id):
        r = MagicMock()
        r.track_id = f"uuid-{spotify_id}"
        r.spotify_id = spotify_id
        r.name = name
        r.artist_names = artist
        r.duration_ms = 200_000
        r.energy = 0.5
        r.valence = 0.5
        r.emotion_label = label
        r.emotion_confidence = conf
        r.tempo_librosa = 120.0
        return r

    def _executed_sql(self, rows=()):
        """Run load_track_pool_from_db and return the SQL text it executed."""
        planner = ArcPlanner()
        db = self._mock_db(list(rows))
        planner.load_track_pool_from_db(db, "user-123")
        args, _kwargs = db.execute.call_args
        return str(args[0])

    def test_sql_no_longer_sorts_the_whole_library(self):
        """
        ORDER BY RANDOM() forced a full sort of every matching row and could not
        use an index.  _select_tracks_for_segment randomises in Python, so the
        DB-side shuffle was redundant.
        """
        sql = self._executed_sql().upper()
        assert "ORDER BY" not in sql
        assert "RANDOM()" not in sql

    def test_sql_still_filters_and_joins_as_before(self):
        """Removing the ORDER BY must not have disturbed the rest of the query."""
        sql = self._executed_sql()
        for fragment in (
            "FROM user_tracks ut",
            "JOIN tracks t ON ut.track_id = t.id",
            "JOIN track_features tf ON t.id = tf.track_id",
            "tf.emotion_label IS NOT NULL",
            "tf.emotion_confidence >= :min_conf",
            "t.duration_ms > 0",
        ):
            assert fragment in sql

    def test_pool_contents_are_unchanged_by_row_order(self):
        """
        The returned pool must not depend on the order the DB hands rows back —
        that is what made the DB-side shuffle safe to delete.
        """
        planner = ArcPlanner()
        rows = [
            self._row("Alpha", "A", "happy", 0.9, "sp1"),
            self._row("Beta", "B", "sad", 0.8, "sp2"),
            self._row("Gamma", "C", "tense", 0.7, "sp3"),
        ]
        forward = planner.load_track_pool_from_db(self._mock_db(rows), "u")
        backward = planner.load_track_pool_from_db(self._mock_db(rows[::-1]), "u")

        assert {t.spotify_id for t in forward} == {t.spotify_id for t in backward}
        assert len(forward) == len(backward) == 3


# ═══ 2. Cached all-pairs shortest paths ══════════════════════════════════════


# Pairs where Floyd-Warshall picks a different — but exactly equal cost —
# optimal path than the old Dijkstra did.  Both algorithms are correct; the
# old heap only compared cost, so which of several equal-cost paths it
# surfaced was an artefact of heap ordering.  Listed explicitly so the change
# is documented and any *further* drift fails loudly.
KNOWN_EQUAL_COST_ALTERNATES = frozenset(
    {
        ("angry", "neutral"),
        ("angry", "nostalgic"),
        ("angry", "peaceful"),
        ("energetic", "neutral"),
        ("focused", "happy"),
        ("focused", "nostalgic"),
        ("melancholic", "peaceful"),
        ("neutral", "melancholic"),
        ("neutral", "sad"),
        ("sad", "angry"),
        ("sad", "energetic"),
        ("sad", "tense"),
        ("tense", "romantic"),
    }
)


class TestAllPairsMatchesDijkstra:
    def setup_method(self):
        self.planner = ArcPlanner()

    def test_cost_identical_to_dijkstra_for_all_144_pairs(self):
        """The headline invariant: same optimal cost for every source/target."""
        for src in ALL_EMOTIONS:
            for tgt in ALL_EMOTIONS:
                new = self.planner.find_emotional_path(src, tgt)
                old = _legacy_dijkstra_path(EMOTION_GRAPH, src, tgt)
                assert _path_cost(EMOTION_GRAPH, new) == _path_cost(
                    EMOTION_GRAPH, old
                ), f"{src}->{tgt}: {new} costs more than Dijkstra's {old}"

    def test_path_identical_to_dijkstra_except_documented_ties(self):
        for src in ALL_EMOTIONS:
            for tgt in ALL_EMOTIONS:
                new = self.planner.find_emotional_path(src, tgt)
                old = _legacy_dijkstra_path(EMOTION_GRAPH, src, tgt)
                if (src, tgt) in KNOWN_EQUAL_COST_ALTERNATES:
                    assert new != old, (
                        f"{src}->{tgt} now matches Dijkstra exactly; "
                        "drop it from KNOWN_EQUAL_COST_ALTERNATES"
                    )
                else:
                    assert new == old, f"{src}->{tgt}: {new} != Dijkstra's {old}"

    def test_every_returned_path_is_a_real_walk(self):
        for src in ALL_EMOTIONS:
            for tgt in ALL_EMOTIONS:
                path = self.planner.find_emotional_path(src, tgt)
                assert path[0] == src
                assert path[-1] == tgt
                assert len(path) == len(set(path)), f"{src}->{tgt} revisits a node"
                for a, b in zip(path, path[1:]):
                    assert b in EMOTION_GRAPH[a], f"{a}->{b} is not an edge"

    def test_distance_matrix_matches_dijkstra_for_all_pairs(self):
        for src in ALL_EMOTIONS:
            oracle = _legacy_shortest_distances(src, EMOTION_GRAPH)
            for tgt in ALL_EMOTIONS:
                assert self.planner.emotional_distance(src, tgt) == oracle[tgt]

    def test_self_path_and_unknown_nodes_behave_as_before(self):
        assert self.planner.find_emotional_path("peaceful", "peaceful") == ["peaceful"]
        with pytest.raises(ValueError, match="Unknown source emotion"):
            self.planner.find_emotional_path("nope", "peaceful")
        with pytest.raises(ValueError, match="Unknown target emotion"):
            self.planner.find_emotional_path("peaceful", "nope")

    def test_unreachable_target_still_returns_two_node_fallback(self):
        planner = ArcPlanner(graph={"a": {"b": 1.0}, "b": {}, "c": {}})
        assert planner.find_emotional_path("a", "c") == ["a", "c"]
        assert planner.emotional_distance("a", "c") == float("inf")

    def test_matches_dijkstra_on_a_personalised_graph_too(self, personalised_graph):
        planner = ArcPlanner(graph=personalised_graph)
        for src in ALL_EMOTIONS:
            for tgt in ALL_EMOTIONS:
                new = planner.find_emotional_path(src, tgt)
                old = _legacy_dijkstra_path(personalised_graph, src, tgt)
                assert _path_cost(personalised_graph, new) == _path_cost(
                    personalised_graph, old
                )


class TestApspCacheIsKeyedOnGraphContent:
    """
    Regression guard for the one way this optimisation could become a
    correctness bug: GraphLearner.load_user_graph() returns a different graph
    per user, so a cache keyed on anything but graph *content* would serve one
    user's shortest paths to another.
    """

    def test_signature_differs_when_a_single_weight_differs(self, personalised_graph):
        assert _graph_signature(EMOTION_GRAPH) != _graph_signature(personalised_graph)

    def test_signature_is_stable_across_equal_but_distinct_dicts(self):
        clone = copy.deepcopy(EMOTION_GRAPH)
        assert clone is not EMOTION_GRAPH
        assert _graph_signature(clone) == _graph_signature(EMOTION_GRAPH)

    def test_signature_ignores_key_insertion_order(self):
        reordered = {k: dict(sorted(v.items())) for k, v in sorted(EMOTION_GRAPH.items(), reverse=True)}
        assert _graph_signature(reordered) == _graph_signature(EMOTION_GRAPH)

    def test_personalised_graph_is_not_served_from_the_global_entry(
        self, personalised_graph
    ):
        global_planner = ArcPlanner()
        # Warm the cache with the global graph first — this is the ordering that
        # would expose a cache keyed on "the global graph".
        baseline = {
            (s, t): global_planner.find_emotional_path(s, t)
            for s in ALL_EMOTIONS
            for t in ALL_EMOTIONS
        }

        user_planner = ArcPlanner(graph=personalised_graph)

        # The personalised weight must be visible, not the global one.
        assert user_planner.emotional_distance("sad", "neutral") == 0.1
        assert global_planner.emotional_distance("sad", "neutral") == 3.0

        # ...and at least one route must actually differ, or the fixture is
        # not exercising anything.
        differing = [
            (s, t)
            for s in ALL_EMOTIONS
            for t in ALL_EMOTIONS
            if user_planner.find_emotional_path(s, t) != baseline[(s, t)]
        ]
        assert differing, "personalised graph produced identical paths everywhere"

        # The global planner's answers must be untouched by the interleaving.
        after = {
            (s, t): global_planner.find_emotional_path(s, t)
            for s in ALL_EMOTIONS
            for t in ALL_EMOTIONS
        }
        assert after == baseline

    def test_two_users_with_different_graphs_do_not_share_results(self):
        graph_a = copy.deepcopy(EMOTION_GRAPH)
        graph_a["neutral"]["happy"] = 0.1
        graph_b = copy.deepcopy(EMOTION_GRAPH)
        graph_b["neutral"]["focused"] = 0.1

        planner_a = ArcPlanner(graph=graph_a)
        planner_b = ArcPlanner(graph=graph_b)

        # Interleave, alternating users, to catch any last-write-wins caching.
        for _ in range(3):
            assert planner_a.emotional_distance("neutral", "happy") == 0.1
            assert planner_b.emotional_distance("neutral", "happy") == 2.0
            assert planner_b.emotional_distance("neutral", "focused") == 0.1
            assert planner_a.emotional_distance("neutral", "focused") == 1.0

    def test_repeat_calls_hit_the_cache(self, personalised_graph):
        _all_pairs_shortest_paths.cache_clear()

        all_pairs_shortest_paths(EMOTION_GRAPH)
        all_pairs_shortest_paths(personalised_graph)
        assert _all_pairs_shortest_paths.cache_info().misses == 2

        for _ in range(10):
            all_pairs_shortest_paths(EMOTION_GRAPH)
            all_pairs_shortest_paths(copy.deepcopy(EMOTION_GRAPH))
            all_pairs_shortest_paths(personalised_graph)

        info = _all_pairs_shortest_paths.cache_info()
        assert info.misses == 2, "an equal-content graph was treated as a new key"
        assert info.hits == 30


class TestResolveReplanSource:
    """
    resolve_replan_source used to rank neighbours by len(path) — hop count —
    which ignores edge weights and contradicted its own docstring.  It now ranks
    by true path cost.  No pre-existing test asserted the hop-count behaviour.
    """

    def setup_method(self):
        self.planner = ArcPlanner()

    def test_picks_the_neighbour_with_the_lowest_true_cost(self):
        for skipped in ALL_EMOTIONS:
            for target in ALL_EMOTIONS:
                chosen = self.planner.resolve_replan_source(skipped, target)
                neighbours = list(EMOTION_GRAPH[skipped])
                assert chosen in neighbours
                best = min(
                    self.planner.emotional_distance(n, target) for n in neighbours
                )
                assert self.planner.emotional_distance(chosen, target) == best

    def test_never_worse_than_the_old_hop_count_choice(self):
        """The semantics change is strictly an improvement, never a regression."""
        for skipped in ALL_EMOTIONS:
            for target in ALL_EMOTIONS:
                neighbours = list(EMOTION_GRAPH[skipped])
                old = min(
                    neighbours,
                    key=lambda n: len(_legacy_dijkstra_path(EMOTION_GRAPH, n, target)),
                )
                new = self.planner.resolve_replan_source(skipped, target)
                assert self.planner.emotional_distance(
                    new, target
                ) <= self.planner.emotional_distance(old, target)

    def test_weighted_ranking_beats_hop_count_on_a_known_case(self):
        # sad's neighbours: melancholic (3 hops, cost 3.0 to focused) and
        # neutral (2 hops, cost 1.0).  Hop count used to prefer melancholic.
        assert self.planner.resolve_replan_source("sad", "focused") == "neutral"

    def test_stays_put_when_there_are_no_neighbours(self):
        planner = ArcPlanner(graph={"lonely": {}})
        assert planner.resolve_replan_source("lonely", "peaceful") == "lonely"

    def test_is_deterministic(self):
        first = [
            self.planner.resolve_replan_source(s, t)
            for s in ALL_EMOTIONS
            for t in ALL_EMOTIONS
        ]
        for _ in range(5):
            again = [
                self.planner.resolve_replan_source(s, t)
                for s in ALL_EMOTIONS
                for t in ALL_EMOTIONS
            ]
            assert again == first


# ═══ 3 & 4. Segment selection: bucketing, no shuffle, heapq top-k ════════════


def _track(n, emotion, energy=0.5, confidence=0.8):
    return TrackCandidate(
        track_id=f"uuid-{n:04d}",
        spotify_id=f"sp{n:04d}",
        title=f"Track {n}",
        artist="Artist",
        duration_ms=210_000,
        emotion_label=emotion,
        emotion_confidence=confidence,
        energy=energy,
        valence=0.5,
        tempo=120.0,
    )


@pytest.fixture
def wide_pool():
    """120 tracks, 10 per emotion, with spread-out energy and confidence."""
    pool = []
    n = 0
    for emotion in ALL_EMOTIONS:
        for i in range(10):
            n += 1
            pool.append(
                _track(
                    n,
                    emotion,
                    energy=round(0.05 + i * 0.09, 4),
                    confidence=round(0.50 + i * 0.045, 4),
                )
            )
    return pool


class TestBucketing:
    def test_buckets_partition_the_pool_exactly(self, wide_pool):
        buckets = ArcPlanner._bucket_pool_by_emotion(wide_pool)
        assert sum(len(v) for v in buckets.values()) == len(wide_pool)
        for emotion, tracks in buckets.items():
            assert all(t.emotion_label == emotion for t in tracks)

    def test_buckets_preserve_pool_order(self, wide_pool):
        buckets = ArcPlanner._bucket_pool_by_emotion(wide_pool)
        for emotion, tracks in buckets.items():
            expected = [t for t in wide_pool if t.emotion_label == emotion]
            assert [t.track_id for t in tracks] == [t.track_id for t in expected]

    def test_empty_pool_buckets_to_nothing(self):
        assert ArcPlanner._bucket_pool_by_emotion([]) == {}

    def test_passing_buckets_gives_the_same_result_as_omitting_them(self, wide_pool):
        planner = ArcPlanner()
        buckets = planner._bucket_pool_by_emotion(wide_pool)

        with patch("app.services.arc_planner.random.uniform", return_value=0.0):
            for direction in ("ascending", "descending", "neutral"):
                without = planner._select_tracks_for_segment(
                    "peaceful", wide_pool, 6, energy_direction=direction
                )
                with_buckets = planner._select_tracks_for_segment(
                    "peaceful",
                    wide_pool,
                    6,
                    energy_direction=direction,
                    buckets=buckets,
                )
                assert [t.track_id for t in without] == [
                    t.track_id for t in with_buckets
                ]

    def test_adjacent_fallback_still_borrows_the_same_tracks(self):
        """Bucketed fallback must borrow the same set as the old full scan."""
        planner = ArcPlanner()
        pool = [_track(1, "peaceful")]
        pool += [_track(10 + i, "neutral", confidence=0.9) for i in range(5)]
        pool += [_track(20 + i, "nostalgic", confidence=0.9) for i in range(5)]
        pool += [_track(30 + i, "angry", confidence=0.99) for i in range(5)]
        pool += [_track(40 + i, "neutral", confidence=0.30) for i in range(5)]

        selected = planner._select_tracks_for_segment("peaceful", pool, 8)
        labels = {t.emotion_label for t in selected}

        # angry is not adjacent to peaceful, and 0.30-confidence neutrals are
        # below ADJACENT_BORROW_MIN_CONFIDENCE.
        assert "angry" not in labels
        assert labels <= set(EMOTION_GRAPH["peaceful"]) | {"peaceful"}
        assert all(t.emotion_confidence >= 0.5 for t in selected)
        assert len(selected) == 8

    def test_plan_only_scans_the_relevant_buckets(self, wide_pool):
        """
        Bucketing is O(n) once instead of O(segments x n).  Assert the pool is
        walked exactly once regardless of how many segments the arc has.
        """
        planner = ArcPlanner()
        arc_path = planner.find_emotional_path("angry", "peaceful")
        assert len(arc_path) >= 3  # multi-segment, so per-segment scans would show

        reads = {"n": 0}

        class CountingList(list):
            def __iter__(self):
                reads["n"] += 1
                return super().__iter__()

        planner.plan("angry", "peaceful", 40, CountingList(wide_pool))
        assert reads["n"] == 1, f"pool iterated {reads['n']} times, expected 1"


class TestTopKPreservesOrdering:
    """heapq.nsmallest/nlargest must be order-equivalent to sorted()[:n]."""

    def _reference(self, candidates, n, direction):
        if direction == "ascending":
            return sorted(candidates, key=lambda t: t.energy)[:n]
        if direction == "descending":
            return sorted(candidates, key=lambda t: t.energy, reverse=True)[:n]
        return sorted(candidates, key=lambda t: t.emotion_confidence, reverse=True)[:n]

    @pytest.mark.parametrize("direction", ["ascending", "descending", "neutral"])
    @pytest.mark.parametrize("n_tracks", [1, 3, 7, 10, 25])
    def test_matches_full_sort_then_slice(self, wide_pool, direction, n_tracks):
        planner = ArcPlanner()
        pool = [t for t in wide_pool if t.emotion_label == "peaceful"]
        with patch("app.services.arc_planner.random.uniform", return_value=0.0):
            got = planner._select_tracks_for_segment(
                "peaceful", pool, n_tracks, energy_direction=direction
            )
        expected = self._reference(pool, n_tracks, direction)
        assert [t.track_id for t in got] == [t.track_id for t in expected]

    def test_ascending_returns_energy_ascending(self, wide_pool):
        planner = ArcPlanner()
        pool = [t for t in wide_pool if t.emotion_label == "peaceful"]
        got = planner._select_tracks_for_segment(
            "peaceful", pool, 5, energy_direction="ascending"
        )
        energies = [t.energy for t in got]
        assert energies == sorted(energies)

    def test_descending_returns_energy_descending(self, wide_pool):
        planner = ArcPlanner()
        pool = [t for t in wide_pool if t.emotion_label == "peaceful"]
        got = planner._select_tracks_for_segment(
            "peaceful", pool, 5, energy_direction="descending"
        )
        energies = [t.energy for t in got]
        assert energies == sorted(energies, reverse=True)

    def test_neutral_returns_confidence_descending(self, wide_pool):
        planner = ArcPlanner()
        pool = [t for t in wide_pool if t.emotion_label == "peaceful"]
        got = planner._select_tracks_for_segment(
            "peaceful", pool, 5, energy_direction="neutral"
        )
        confidences = [t.emotion_confidence for t in got]
        assert confidences == sorted(confidences, reverse=True)

    def test_returns_everything_when_n_exceeds_the_pool(self, wide_pool):
        planner = ArcPlanner()
        pool = [t for t in wide_pool if t.emotion_label == "peaceful"]
        got = planner._select_tracks_for_segment("peaceful", pool, 500)
        assert len(got) == len(pool)

    def test_removed_shuffle_did_not_remove_randomness(self, wide_pool):
        """
        The shuffle was dead work (every branch re-sorted immediately), but the
        +/-0.01 jitter is load-bearing: near-equal-energy tracks must still
        swap around between runs.
        """
        planner = ArcPlanner()
        pool = [_track(i, "peaceful", energy=0.500 + (i % 2) * 0.001) for i in range(20)]
        seen = set()
        for _ in range(30):
            got = planner._select_tracks_for_segment(
                "peaceful", pool, 5, energy_direction="ascending"
            )
            seen.add(tuple(t.track_id for t in got))
        assert len(seen) > 1, "jitter no longer varies selection"


class TestPlanStillWellFormed:
    def test_plan_output_is_unchanged_in_shape(self, wide_pool):
        planner = ArcPlanner()
        arc = planner.plan("tense", "peaceful", 45, wide_pool)

        assert arc["arc_path"] == planner.find_emotional_path("tense", "peaceful")
        assert len(arc["segments"]) == len(arc["arc_path"])
        assert arc["total_tracks"] == len(arc["tracks"])
        assert arc["readiness"]["pool_size"] == len(wide_pool)

        ids = [t.track_id for t in arc["tracks"]]
        assert len(ids) == len(set(ids)), "plan() emitted a duplicate track"
        spotify_ids = [t.spotify_id for t in arc["tracks"]]
        assert len(spotify_ids) == len(set(spotify_ids))

    def test_segments_prefer_their_own_emotion(self, wide_pool):
        planner = ArcPlanner()
        arc = planner.plan("tense", "peaceful", 30, wide_pool)
        for segment in arc["segments"]:
            emotion = segment["emotion"]
            allowed = set(EMOTION_GRAPH[emotion]) | {emotion}
            assert all(t.emotion_label in allowed for t in segment["tracks"])


# ═══ 5. language_detector.detect ═════════════════════════════════════════════


class TestDetect:
    @pytest.mark.parametrize(
        ("title", "artist", "expected"),
        [
            # Telugu (U+0C00-U+0C7F)
            ("పాట పేరు", "గాయకుడు", "te"),
            ("Butta Bomma", "అర్మాన్ మాలిక్", "te"),
            # Tamil (U+0B80-U+0BFF)
            ("பாடல் தலைப்பு", "ஏ.ஆர். ரகுமான்", "ta"),
            ("Vaseegara", "பாம்பே ஜெயஶ்రீ", "ta"),
            # Hindi / Devanagari (U+0900-U+097F)
            ("तुम ही हो", "Arijit Singh", "hi"),
            ("Song Name", "आशा भोसले", "hi"),
            # Korean / Hangul (U+AC00-U+D7AF)
            ("봄날", "방탄소년단", "ko"),
            ("Dynamite", "방탄소년단", "ko"),
            # English / Latin — the ASCII fast path
            ("Shape of You", "Ed Sheeran", "en"),
            ("", "", "en"),
            ("", "Adele", "en"),
            ("Hello", "", "en"),
        ],
    )
    def test_known_scripts(self, title, artist, expected):
        assert detect(title, artist) == expected

    def test_ascii_fast_path_cannot_skip_a_real_script(self):
        """
        The fast path bails on cp < 0x0590.  Assert that really is below every
        range, so no supported script can be skipped by it.
        """
        from app.services.language_detector import (
            _LOWEST_SCRIPT_CODEPOINT,
            _SCRIPT_RANGES,
        )

        assert _LOWEST_SCRIPT_CODEPOINT == 0x0590
        assert all(lo >= _LOWEST_SCRIPT_CODEPOINT for lo, _hi, _lang in _SCRIPT_RANGES)

    def test_every_ascii_and_latin_codepoint_is_english(self):
        for cp in range(0x0000, 0x0590):
            assert detect(chr(cp), "") == "en", f"U+{cp:04X} misdetected"

    def test_first_codepoint_of_every_range_is_still_detected(self):
        from app.services.language_detector import _SCRIPT_RANGES

        for lo, hi, lang in _SCRIPT_RANGES:
            # The list is ordered most-specific-first and the ranges do not
            # overlap, so the first match for a range's own bounds is its lang.
            assert detect(chr(lo), "") == lang, f"U+{lo:04X}"
            assert detect(chr(hi), "") == lang, f"U+{hi:04X}"

    def test_script_wins_over_leading_latin(self):
        assert detect("Tum Hi Ho (तुम ही हो)", "Arijit Singh") == "hi"

    def test_caching_returns_identical_results(self):
        pairs = [
            ("Shape of You", "Ed Sheeran"),
            ("తెలుగు పాట", "గాయకుడు"),
            ("봄날", "BTS"),
            ("तुम ही हो", "Arijit Singh"),
        ]
        first = [detect(t, a) for t, a in pairs]
        for _ in range(50):
            assert [detect(t, a) for t, a in pairs] == first

    def test_repeat_calls_hit_the_cache(self):
        detect.cache_clear()
        for _ in range(100):
            detect("Shape of You", "Ed Sheeran")
        info = detect.cache_info()
        assert info.misses == 1
        assert info.hits == 99

    def test_cache_does_not_confuse_title_and_artist(self):
        detect.cache_clear()
        assert detect("తెలుగు", "Latin") == "te"
        assert detect("Latin", "తెలుగు") == "te"
        assert detect("Latin", "Latin") == "en"
        assert detect("తెలుగు", "தமிழ்") == "te"
        assert detect("தமிழ்", "తెలుగు") == "ta"


# ═══ 6. collab_service._shortest_distances ═══════════════════════════════════


class TestCollabDistances:
    def test_matches_legacy_dijkstra_for_every_source(self):
        """
        Bit-for-bit equality on the global graph.  This is the case that
        matters for the alphabetical tie-break in aggregate_source_emotion:
        EMOTION_GRAPH's weights sum exactly, so genuine ties stay exact ties
        and cannot be flipped by float noise.
        """
        for src in ALL_EMOTIONS:
            assert _shortest_distances(src, EMOTION_GRAPH) == _legacy_shortest_distances(
                src, EMOTION_GRAPH
            )

    def test_matches_legacy_dijkstra_on_a_personalised_graph(self, personalised_graph):
        """
        Personalised weights (0.1 here) are not exactly representable, and
        Floyd-Warshall accumulates partial sums in a different order than
        Dijkstra, so results agree to float tolerance rather than bit-exactly.
        Such graphs have no exact ties for the tolerance to disturb.
        """
        for src in ALL_EMOTIONS:
            got = _shortest_distances(src, personalised_graph)
            want = _legacy_shortest_distances(src, personalised_graph)
            assert set(got) == set(want)
            for emotion in want:
                assert got[emotion] == pytest.approx(want[emotion], abs=1e-9)

    def test_keys_cover_the_whole_graph(self):
        d = _shortest_distances("peaceful", EMOTION_GRAPH)
        assert set(d) == set(EMOTION_GRAPH)
        assert d["peaceful"] == 0.0

    def test_unreachable_nodes_get_infinity(self):
        graph = {"a": {"b": 1.0}, "b": {}, "c": {}}
        d = _shortest_distances("a", graph)
        assert d == {"a": 0.0, "b": 1.0, "c": float("inf")}

    def test_unknown_source_yields_all_infinite(self):
        d = _shortest_distances("nope", EMOTION_GRAPH)
        assert set(d) == set(EMOTION_GRAPH)
        assert all(v == float("inf") for v in d.values())


class TestAggregateSourceEmotion:
    def setup_method(self):
        self.svc = CollabArcService()

    def test_matches_a_legacy_dijkstra_reimplementation(self):
        from app.services.mood_parser import VALID_EMOTIONS

        def legacy_aggregate(source_emotions):
            if not source_emotions:
                return "neutral"
            if len(source_emotions) == 1:
                return source_emotions[0]
            dist_from = {
                s: _legacy_shortest_distances(s, EMOTION_GRAPH)
                for s in set(source_emotions)
            }
            best_emotion, best_total = "neutral", float("inf")
            for candidate in sorted(VALID_EMOTIONS):
                total = sum(
                    dist_from[s].get(candidate, float("inf")) for s in source_emotions
                )
                if total < best_total:
                    best_total, best_emotion = total, candidate
            return best_emotion

        cases = [
            [],
            ["sad"],
            ["sad", "energetic"],
            ["angry", "peaceful"],
            ["happy", "sad", "focused"],
            ["tense", "tense", "peaceful"],
            ["euphoric", "melancholic", "nostalgic", "angry"],
            list(ALL_EMOTIONS),
        ]
        for case in cases:
            assert self.svc.aggregate_source_emotion(case) == legacy_aggregate(case), (
                f"diverged for {case}"
            )

    def test_ties_break_alphabetically(self):
        """
        Determinism guard: the winner must be the alphabetically first emotion
        achieving the minimum total distance.
        """
        from app.services.mood_parser import VALID_EMOTIONS

        for case in (
            ["sad", "energetic"],
            ["angry", "peaceful"],
            ["happy", "sad", "focused"],
            ["euphoric", "melancholic"],
        ):
            chosen = self.svc.aggregate_source_emotion(case)
            totals = {
                candidate: sum(
                    _shortest_distances(s, EMOTION_GRAPH)[candidate] for s in case
                )
                for candidate in VALID_EMOTIONS
            }
            best = min(totals.values())
            winners = sorted(c for c, v in totals.items() if v == best)
            assert chosen == winners[0], f"{case}: expected {winners[0]}, got {chosen}"

    def test_result_is_order_independent_and_repeatable(self):
        case = ["happy", "sad", "focused", "angry"]
        expected = self.svc.aggregate_source_emotion(case)
        for permutation in ([*case[::-1]], case[1:] + case[:1], case):
            assert self.svc.aggregate_source_emotion(permutation) == expected
