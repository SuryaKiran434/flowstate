"""
Arc Planning Service — Flowstate
---------------------------------
Generates an emotionally coherent track sequence that bridges
a source emotion to a target emotion using graph-based path planning.

Algorithm:
1. Build a weighted emotion graph (nodes = emotions, edges = transition costs)
2. Read the lowest-cost emotional path source → target out of a cached
   all-pairs (Floyd-Warshall) table keyed on that graph's contents
3. For each node along the path, query the feature store for best-matching tracks
4. Sequence tracks within each segment by energy gradient (smooth transitions)

Author: Surya Kiran Katragadda
"""

import heapq
import random
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


# ─── Emotion Graph ────────────────────────────────────────────────────────────

# Tracks classified below this confidence are treated as noise and excluded from
# arc selection. Set conservatively (0.35) — uniform-random over 12 emotions is
# 0.083, so 0.35 keeps anything meaningfully above chance while removing the
# garbage predictions that historically polluted segments.
MIN_INFERENCE_CONFIDENCE: float = 0.35

# Used when borrowing tracks from adjacent emotions to fill a short segment.
# We want tracks the model was reasonably sure about — the previous policy of
# "borrow low-confidence neighbours as bridges" added noise, not coherence.
ADJACENT_BORROW_MIN_CONFIDENCE: float = 0.5


EMOTION_GRAPH: dict[str, dict[str, float]] = {
    "energetic": {"happy": 1.0, "euphoric": 1.2, "focused": 2.0, "tense": 2.5},
    "happy": {"energetic": 1.0, "euphoric": 1.2, "romantic": 1.5, "neutral": 2.0},
    "euphoric": {"happy": 1.2, "energetic": 1.2, "romantic": 2.0},
    "peaceful": {"neutral": 1.0, "nostalgic": 1.5, "focused": 1.5, "romantic": 2.0},
    "focused": {"neutral": 1.0, "peaceful": 1.5, "energetic": 2.0, "melancholic": 2.5},
    "romantic": {"happy": 1.5, "nostalgic": 1.5, "peaceful": 2.0, "melancholic": 2.5},
    "nostalgic": {"melancholic": 1.5, "romantic": 1.5, "peaceful": 2.0, "neutral": 2.0},
    "neutral": {"peaceful": 1.0, "focused": 1.0, "nostalgic": 2.0, "happy": 2.0},
    "melancholic": {"sad": 1.5, "nostalgic": 1.5, "neutral": 2.5, "focused": 3.0},
    "sad": {"melancholic": 1.5, "neutral": 3.0, "nostalgic": 2.5},
    "tense": {"energetic": 2.5, "neutral": 2.0, "focused": 1.5, "angry": 1.5},
    "angry": {"tense": 1.5, "energetic": 2.5, "neutral": 3.5},
}

TRACKS_PER_MINUTE: dict[str, float] = {
    "energetic": 0.25,
    "happy": 0.27,
    "euphoric": 0.25,
    "peaceful": 0.20,
    "focused": 0.22,
    "romantic": 0.20,
    "nostalgic": 0.22,
    "neutral": 0.25,
    "melancholic": 0.20,
    "sad": 0.18,
    "tense": 0.28,
    "angry": 0.30,
}

# Approximate energy center per emotion — used for transition direction logic
ENERGY_CENTERS: dict[str, float] = {
    "energetic": 0.85,
    "euphoric": 0.85,
    "angry": 0.85,
    "tense": 0.75,
    "happy": 0.65,
    "focused": 0.50,
    "neutral": 0.45,
    "romantic": 0.40,
    "nostalgic": 0.38,
    "peaceful": 0.25,
    "melancholic": 0.25,
    "sad": 0.20,
}


@dataclass
class TrackCandidate:
    track_id: str  # UUID string from track_features.track_id
    spotify_id: str  # Spotify track ID
    title: str
    artist: str
    duration_ms: int
    emotion_label: str
    emotion_confidence: float
    energy: float
    valence: float
    tempo: float
    language: str = "en"  # BCP-47-style code inferred from Unicode script


# ─── All-pairs shortest paths ─────────────────────────────────────────────────
#
# The emotion graph is tiny (12 nodes, ~40 edges), so one Floyd-Warshall pass
# (12^3 = 1728 relaxations) is cheaper than a single Dijkstra run in practice —
# and it answers every source/target query afterwards for free.
#
# The result is memoised on a *content* digest of the graph, never on identity
# or on "the global graph".  GraphLearner.load_user_graph() returns a distinct
# personalised graph per user, and serving one user's shortest paths to another
# would be a correctness bug, not a performance one.


def _graph_signature(graph: dict[str, dict[str, float]]) -> tuple:
    """Canonical, hashable digest of a weighted graph — the APSP cache key."""
    return tuple(
        (node, tuple(sorted(edges.items()))) for node, edges in sorted(graph.items())
    )


@lru_cache(maxsize=256)
def _all_pairs_shortest_paths(signature: tuple):
    """
    Floyd-Warshall over a graph signature.

    Returns (nodes, index, dist, nxt):
        nodes — list of node names, positionally aligned with the matrices
        index — {node: matrix position}
        dist  — dist[i][j] = total cost of the cheapest i→j walk (inf if none)
        nxt   — nxt[i][j] = position of the next hop on that walk (None if none)

    Cached on `signature`, so callers must go through all_pairs_shortest_paths().
    """
    nodes = [node for node, _ in signature]
    index = {node: i for i, node in enumerate(nodes)}
    n = len(nodes)
    inf = float("inf")

    dist: list[list[float]] = [[inf] * n for _ in range(n)]
    nxt: list[list[Optional[int]]] = [[None] * n for _ in range(n)]
    for i in range(n):
        dist[i][i] = 0.0
        nxt[i][i] = i

    for node, edges in signature:
        i = index[node]
        for neighbour, weight in edges:
            j = index.get(neighbour)
            # A neighbour that is not itself a key is a dead end: it has no
            # outgoing edges and find_emotional_path() rejects it as a target,
            # so it can never be an intermediate hop. Dropping it matches the
            # reachability the old Dijkstra produced.
            if j is None:
                continue
            if weight < dist[i][j]:
                dist[i][j] = weight
                nxt[i][j] = j

    for k in range(n):
        dist_k = dist[k]
        for i in range(n):
            dist_ik = dist[i][k]
            if dist_ik == inf:
                continue
            dist_i, nxt_i, nxt_ik = dist[i], nxt[i], nxt[i][k]
            for j in range(n):
                if dist_k[j] == inf:
                    continue
                candidate = dist_ik + dist_k[j]
                if candidate < dist_i[j]:
                    dist_i[j] = candidate
                    nxt_i[j] = nxt_ik

    return nodes, index, dist, nxt


def all_pairs_shortest_paths(graph: dict[str, dict[str, float]]):
    """Cached Floyd-Warshall for `graph`. See _all_pairs_shortest_paths()."""
    return _all_pairs_shortest_paths(_graph_signature(graph))


class ArcPlanner:
    """
    Generates an emotionally coherent playlist arc.

    Usage:
        planner = ArcPlanner()

        # Option A: provide pre-built pool (testing/offline)
        arc = planner.plan(source="tense", target="peaceful",
                           duration_minutes=45, track_pool=[...])

        # Option B: query DB directly (production)
        arc = planner.plan_from_db(source="tense", target="peaceful",
                                   duration_minutes=45, db=db_session,
                                   user_id="uuid-string")
    """

    def __init__(self, graph: dict[str, dict[str, float]] = None):
        self.graph = graph or EMOTION_GRAPH

    # ── DB integration ────────────────────────────────────────────────────────

    def load_track_pool_from_db(
        self,
        db,
        user_id: str,
        excluded_spotify_ids: Optional[set] = None,
    ) -> list[TrackCandidate]:
        """
        Load all classified tracks for a user from the DB in one query.
        Returns a list of TrackCandidate objects ready for arc planning.
        Language is inferred on-the-fly from the track title + artist via
        Unicode script detection (no DB column required).
        """
        from sqlalchemy import text
        from app.services.language_detector import detect as detect_language

        rows = db.execute(
            text("""
            SELECT
                tf.track_id,
                t.id        AS spotify_id,
                t.name, t.artist_names,
                t.duration_ms,
                tf.energy, tf.valence,
                tf.emotion_label,
                tf.emotion_confidence,
                tf.tempo_librosa
            FROM user_tracks ut
            JOIN tracks t ON ut.track_id = t.id
            JOIN track_features tf ON t.id = tf.track_id
            WHERE ut.user_id = cast(:uid as uuid)
              AND tf.emotion_label IS NOT NULL
              AND tf.emotion_confidence >= :min_conf
              AND t.name IS NOT NULL
              AND t.duration_ms > 0
        """),
            {"uid": user_id, "min_conf": MIN_INFERENCE_CONFIDENCE},
        ).fetchall()

        excluded = excluded_spotify_ids or set()
        candidates = [
            TrackCandidate(
                track_id=str(r.track_id),
                spotify_id=r.spotify_id,
                title=r.name,
                artist=r.artist_names or "",
                duration_ms=r.duration_ms or 0,
                emotion_label=r.emotion_label,
                emotion_confidence=r.emotion_confidence or 0.5,
                energy=r.energy or 0.5,
                valence=r.valence or 0.5,
                tempo=r.tempo_librosa or 120.0,
                language=detect_language(r.name or "", r.artist_names or ""),
            )
            for r in rows
            if r.emotion_label is not None and r.spotify_id not in excluded
        ]

        # Deduplicate by normalised title — keep highest-confidence version of each song.
        # Prevents the same song appearing twice when multiple editions share a title.
        seen_titles: dict[str, TrackCandidate] = {}
        for t in candidates:
            key = t.title.lower().strip() if t.title else t.spotify_id
            if (
                key not in seen_titles
                or t.emotion_confidence > seen_titles[key].emotion_confidence
            ):
                seen_titles[key] = t
        return list(seen_titles.values())

    def plan_from_db(
        self,
        source: str,
        target: str,
        duration_minutes: int,
        db,
        user_id: str,
        excluded_spotify_ids: Optional[set] = None,
        fixed_arc_path: Optional[list[str]] = None,
        language_filter: Optional[list[str]] = None,
    ) -> dict:
        """
        Production entry point. Loads track pool from DB then plans the arc.

        language_filter — optional list of BCP-47 language codes (e.g. ['en', 'hi']).
          When provided, only tracks whose detected language matches are used.
          The classifier is language-agnostic (audio features only), so emotional
          coherence is preserved regardless of language mix.
        """
        track_pool = self.load_track_pool_from_db(
            db, user_id, excluded_spotify_ids=excluded_spotify_ids
        )

        if language_filter:
            langs = {lang.lower() for lang in language_filter}
            track_pool = [t for t in track_pool if t.language in langs]

        if not track_pool:
            return {
                "error": "library_not_ready",
                "message": "Your library is still being processed. Please try again shortly.",
                "arc_path": [],
                "segments": [],
                "tracks": [],
                "total_tracks": 0,
            }

        return self.plan(
            source, target, duration_minutes, track_pool, fixed_arc_path=fixed_arc_path
        )

    def resolve_replan_source(self, skipped_emotion: str, target: str) -> str:
        """
        When a user skips 2+ consecutive tracks in `skipped_emotion`, find the
        best neighbor node to re-enter from — the one with the shortest path
        to `target`, so the re-planned arc makes natural progress.

        Ranked by true path *cost*, not hop count: the graph is weighted, so a
        two-hop route over 3.5-cost edges is a worse re-entry than a three-hop
        route over 1.0-cost ones, and the old hop-count ranking contradicted
        this docstring. Each lookup is now an O(1) probe into the cached
        all-pairs matrix — it used to run a full Dijkstra per neighbour.
        """
        neighbors = list(self.graph.get(skipped_emotion, {}).keys())
        if not neighbors:
            return skipped_emotion  # no neighbors — stay put

        if target not in self.graph:
            raise ValueError(f"Unknown target emotion: {target}")

        # Fetch the matrix once, then probe it per neighbour. Going through
        # emotional_distance() here would re-hash the graph on every neighbour.
        _nodes, index, dist, _nxt = self._apsp()
        column = index[target]

        def _cost(neighbour: str) -> float:
            if neighbour not in index:
                raise ValueError(f"Unknown source emotion: {neighbour}")
            return dist[index[neighbour]][column]

        # min() keeps the first minimum, so ties break on graph edge order.
        return min(neighbors, key=_cost)

    # ── Core planning ─────────────────────────────────────────────────────────

    def _apsp(self):
        """Cached all-pairs shortest paths for the graph THIS planner holds."""
        return all_pairs_shortest_paths(self.graph)

    def emotional_distance(self, source: str, target: str) -> float:
        """
        Total edge cost of the cheapest source -> target walk.
        Infinity when target is unreachable. O(1) after the first call.
        """
        if source not in self.graph:
            raise ValueError(f"Unknown source emotion: {source}")
        if target not in self.graph:
            raise ValueError(f"Unknown target emotion: {target}")
        _nodes, index, dist, _nxt = self._apsp()
        return dist[index[source]][index[target]]

    def find_emotional_path(self, source: str, target: str) -> list[str]:
        """
        Lowest-cost path across the emotion graph.

        Reconstructed from the cached all-pairs successor matrix instead of
        re-running Dijkstra per call, which also drops the `path + [neighbor]`
        list copy the old heap push made on every edge relaxation.
        """
        if source == target:
            return [source]
        if source not in self.graph:
            raise ValueError(f"Unknown source emotion: {source}")
        if target not in self.graph:
            raise ValueError(f"Unknown target emotion: {target}")

        nodes, index, _dist, nxt = self._apsp()
        i, j = index[source], index[target]
        if nxt[i][j] is None:
            return [source, target]  # unreachable — same fallback as before

        path = [source]
        while i != j:
            i = nxt[i][j]
            path.append(nodes[i])
        return path

    def _allocate_tracks_per_segment(
        self,
        path: list[str],
        duration_minutes: int,
    ) -> list[int]:
        n = len(path)
        if n == 1:
            return [max(5, int(duration_minutes * TRACKS_PER_MINUTE[path[0]]))]

        rates = [TRACKS_PER_MINUTE[e] for e in path]
        avg_rate = sum(rates) / n
        total = max(n * 3, int(duration_minutes * avg_rate))

        # Largest-remainder (Hare quota) allocation by per-emotion rate.
        # Each segment's share is proportional to how many tracks-per-minute
        # that emotion needs (e.g. peaceful=0.20 vs angry=0.30) — faster
        # emotions get more tracks because their tracks are shorter.
        # Previous logic split `total // n` evenly then dumped the remainder
        # on allocation[0] via `max(1, remainder // 2)`, which added a track
        # to the opening segment even when total divided evenly across n.
        weights = [r / sum(rates) for r in rates]
        exact = [w * total for w in weights]
        allocation = [int(e) for e in exact]
        remainder = total - sum(allocation)
        # Distribute remainder to segments with the largest fractional parts.
        fractional = sorted(
            range(n), key=lambda i: exact[i] - int(exact[i]), reverse=True
        )
        for i in range(remainder):
            allocation[fractional[i]] += 1
        return [max(2, a) for a in allocation]

    def _compute_energy_directions(self, path: list[str]) -> list[str]:
        directions = []
        for i, emotion in enumerate(path):
            if i == len(path) - 1:
                directions.append("neutral")
            else:
                curr = ENERGY_CENTERS.get(emotion, 0.5)
                nxt = ENERGY_CENTERS.get(path[i + 1], 0.5)
                if nxt > curr + 0.1:
                    directions.append("ascending")
                elif nxt < curr - 0.1:
                    directions.append("descending")
                else:
                    directions.append("neutral")
        return directions

    @staticmethod
    def _bucket_pool_by_emotion(
        track_pool: list[TrackCandidate],
    ) -> dict[str, list[TrackCandidate]]:
        """
        Index the pool by emotion_label once so segment selection never has to
        rescan the whole library. Preserves pool order within each bucket.
        """
        buckets: dict[str, list[TrackCandidate]] = defaultdict(list)
        for track in track_pool:
            buckets[track.emotion_label].append(track)
        return buckets

    def _select_tracks_for_segment(
        self,
        emotion: str,
        track_pool: list[TrackCandidate],
        n_tracks: int,
        energy_direction: str = "neutral",
        used_track_ids: Optional[set] = None,
        buckets: Optional[dict[str, list[TrackCandidate]]] = None,
    ) -> list[TrackCandidate]:
        """
        `buckets` is `track_pool` pre-indexed by emotion_label. plan() builds it
        once and hands it to every segment; when omitted it is built here, so
        direct callers keep working with just the pool list.
        """
        used_track_ids = used_track_ids or set()
        if buckets is None:
            buckets = self._bucket_pool_by_emotion(track_pool)

        candidates = [
            t for t in buckets.get(emotion, ()) if t.track_id not in used_track_ids
        ]

        # Fallback when this emotion is under-represented in the user's library:
        # borrow tracks from adjacent emotions that the classifier was confident
        # about. A confidently-labelled "neutral" track is a better bridge to
        # "focused" than a 30%-confidence track of any label.
        if len(candidates) < n_tracks:
            existing_ids = {t.track_id for t in candidates}
            fallback = [
                t
                for adjacent in self.graph.get(emotion, {})
                for t in buckets.get(adjacent, ())
                if t.emotion_confidence >= ADJACENT_BORROW_MIN_CONFIDENCE
                and t.track_id not in used_track_ids
                and t.track_id not in existing_ids
            ]
            # Prefer highest-confidence neighbours first so borrowed tracks
            # don't drag the segment further from its intended emotion.
            fallback.sort(key=lambda t: t.emotion_confidence, reverse=True)
            candidates = candidates + fallback

        # Small noise breaks ties without reordering tracks with meaningfully
        # different energies — previous ±0.08 routinely flipped a 0.55-energy
        # track ahead of a 0.60 on "ascending" segments.
        #
        # nsmallest/nlargest are order-equivalent to sorted(...)[:n_tracks] but
        # cost O(n log n_tracks) instead of sorting every candidate. No shuffle
        # first: every branch below re-sorts immediately and the continuous
        # jitter already breaks ties, so shuffling was pure dead work.
        jitter = 0.01
        if energy_direction == "ascending":
            return heapq.nsmallest(
                n_tracks,
                candidates,
                key=lambda t: t.energy + random.uniform(-jitter, jitter),
            )
        if energy_direction == "descending":
            return heapq.nlargest(
                n_tracks,
                candidates,
                key=lambda t: t.energy + random.uniform(-jitter, jitter),
            )
        return heapq.nlargest(
            n_tracks,
            candidates,
            key=lambda t: t.emotion_confidence + random.uniform(-jitter, jitter),
        )

    def plan(
        self,
        source: str,
        target: str,
        duration_minutes: int,
        track_pool: list[TrackCandidate],
        fixed_arc_path: Optional[list[str]] = None,
    ) -> dict:
        """
        Main entry point. Returns a structured arc.

        Returns:
            {
                "arc_path": ["tense", "neutral", "peaceful"],
                "segments": [{"emotion": ..., "tracks": [...], ...}],
                "tracks": [...],   # flat ordered list
                "total_tracks": 12,
                "total_duration_ms": 2400000,
                "readiness": {     # diagnostic info
                    "pool_size": 715,
                    "coverage_pct": 98.2,
                    "missing_emotions": []
                }
            }
        """
        arc_path = fixed_arc_path or self.find_emotional_path(source, target)
        allocation = self._allocate_tracks_per_segment(arc_path, duration_minutes)
        directions = self._compute_energy_directions(arc_path)

        # Index the pool by emotion once, rather than rescanning it per segment.
        buckets = self._bucket_pool_by_emotion(track_pool)

        segments = []
        used_ids: set[str] = set()  # track_id UUIDs
        used_spotify_ids: set[str] = set()  # spotify_ids — second dedup layer
        flat_tracks: list[TrackCandidate] = []

        for i, (emotion, n_tracks, direction) in enumerate(
            zip(arc_path, allocation, directions)
        ):
            selected = self._select_tracks_for_segment(
                emotion=emotion,
                track_pool=track_pool,
                n_tracks=n_tracks,
                energy_direction=direction,
                used_track_ids=used_ids,
                buckets=buckets,
            )
            # Filter any that share a spotify_id already used (cross-segment safety net)
            selected = [t for t in selected if t.spotify_id not in used_spotify_ids]
            for t in selected:
                used_ids.add(t.track_id)
                used_spotify_ids.add(t.spotify_id)

            segments.append(
                {
                    "emotion": emotion,
                    "segment_index": i,
                    "tracks": selected,
                    "energy_direction": direction,
                    "track_count": len(selected),
                }
            )
            flat_tracks.extend(selected)

        # Diagnostic: which emotions in the path had no tracks?
        emotion_counts = {e: 0 for e in arc_path}
        for seg in segments:
            emotion_counts[seg["emotion"]] = seg["track_count"]
        missing = [e for e, c in emotion_counts.items() if c == 0]

        total_duration_ms = sum(t.duration_ms for t in flat_tracks)

        return {
            "arc_path": arc_path,
            "segments": segments,
            "tracks": flat_tracks,
            "total_tracks": len(flat_tracks),
            "total_duration_ms": total_duration_ms,
            "readiness": {
                "pool_size": len(track_pool),
                "missing_emotions": missing,
                "has_gaps": len(missing) > 0,
            },
        }
