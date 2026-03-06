"""
Arc Planning Service — Flowstate
---------------------------------
Generates an emotionally coherent track sequence that bridges
a source emotion to a target emotion using graph-based path planning.

Algorithm:
1. Build a weighted emotion graph (nodes = emotions, edges = transition costs)
2. Run modified Dijkstra to find the lowest-cost emotional path from source → target
3. For each node along the path, query the feature store for best-matching tracks
4. Sequence tracks within each segment by energy gradient (smooth transitions)

Author: Surya Kiran Katragadda
"""

import heapq
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

import numpy as np


# ─── Emotion Graph ────────────────────────────────────────────────────────────

EMOTION_GRAPH: dict[str, dict[str, float]] = {
    "energetic":   {"happy": 1.0, "euphoric": 1.2, "focused": 2.0, "tense": 2.5},
    "happy":       {"energetic": 1.0, "euphoric": 1.2, "romantic": 1.5, "neutral": 2.0},
    "euphoric":    {"happy": 1.2, "energetic": 1.2, "romantic": 2.0},
    "peaceful":    {"neutral": 1.0, "nostalgic": 1.5, "focused": 1.5, "romantic": 2.0},
    "focused":     {"neutral": 1.0, "peaceful": 1.5, "energetic": 2.0, "melancholic": 2.5},
    "romantic":    {"happy": 1.5, "nostalgic": 1.5, "peaceful": 2.0, "melancholic": 2.5},
    "nostalgic":   {"melancholic": 1.5, "romantic": 1.5, "peaceful": 2.0, "neutral": 2.0},
    "neutral":     {"peaceful": 1.0, "focused": 1.0, "nostalgic": 2.0, "happy": 2.0},
    "melancholic": {"sad": 1.5, "nostalgic": 1.5, "neutral": 2.5, "focused": 3.0},
    "sad":         {"melancholic": 1.5, "neutral": 3.0, "nostalgic": 2.5},
    "tense":       {"energetic": 2.5, "neutral": 2.0, "focused": 1.5, "angry": 1.5},
    "angry":       {"tense": 1.5, "energetic": 2.5, "neutral": 3.5},
}

TRACKS_PER_MINUTE: dict[str, float] = {
    "energetic": 0.25, "happy": 0.27, "euphoric": 0.25,
    "peaceful": 0.20,  "focused": 0.22, "romantic": 0.20,
    "nostalgic": 0.22, "neutral": 0.25, "melancholic": 0.20,
    "sad": 0.18,       "tense": 0.28,  "angry": 0.30,
}

# Approximate energy center per emotion — used for transition direction logic
ENERGY_CENTERS: dict[str, float] = {
    "energetic": 0.85, "euphoric": 0.85, "angry": 0.85, "tense": 0.75,
    "happy": 0.65,     "focused": 0.50,  "neutral": 0.45, "romantic": 0.40,
    "nostalgic": 0.38, "peaceful": 0.25, "melancholic": 0.25, "sad": 0.20,
}


@dataclass
class TrackCandidate:
    track_id: str          # UUID string from track_features.track_id
    spotify_id: str        # Spotify track ID
    title: str
    artist: str
    duration_ms: int
    emotion_label: str
    emotion_confidence: float
    energy: float
    valence: float
    tempo: float


@dataclass(order=True)
class _PQEntry:
    cost: float
    node: str = field(compare=False)
    path: list[str] = field(compare=False)


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

    def load_track_pool_from_db(self, db, user_id: str) -> list[TrackCandidate]:
        """
        Load all classified tracks for a user from the DB in one query.
        Returns a list of TrackCandidate objects ready for arc planning.
        """
        from sqlalchemy import text

        rows = db.execute(text("""
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
        """), {"uid": user_id}).fetchall()

        return [
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
            )
            for r in rows
            if r.emotion_label is not None
        ]

    def plan_from_db(
        self,
        source: str,
        target: str,
        duration_minutes: int,
        db,
        user_id: str,
    ) -> dict:
        """
        Production entry point. Loads track pool from DB then plans the arc.
        """
        track_pool = self.load_track_pool_from_db(db, user_id)

        if not track_pool:
            return {
                "error": "library_not_ready",
                "message": "Your library is still being processed. Please try again shortly.",
                "arc_path": [],
                "segments": [],
                "tracks": [],
                "total_tracks": 0,
            }

        return self.plan(source, target, duration_minutes, track_pool)

    # ── Core planning ─────────────────────────────────────────────────────────

    def find_emotional_path(self, source: str, target: str) -> list[str]:
        """Modified Dijkstra on the emotion graph."""
        if source == target:
            return [source]
        if source not in self.graph:
            raise ValueError(f"Unknown source emotion: {source}")
        if target not in self.graph:
            raise ValueError(f"Unknown target emotion: {target}")

        pq = [_PQEntry(cost=0.0, node=source, path=[source])]
        visited: dict[str, float] = {}

        while pq:
            entry = heapq.heappop(pq)
            current_cost, current_node, path = entry.cost, entry.node, entry.path

            if current_node in visited and visited[current_node] <= current_cost:
                continue
            visited[current_node] = current_cost

            if current_node == target:
                return path

            for neighbor, edge_weight in self.graph.get(current_node, {}).items():
                new_cost = current_cost + edge_weight
                if neighbor not in visited or visited[neighbor] > new_cost:
                    heapq.heappush(pq, _PQEntry(
                        cost=new_cost,
                        node=neighbor,
                        path=path + [neighbor]
                    ))

        return [source, target]

    def _allocate_tracks_per_segment(
        self,
        path: list[str],
        duration_minutes: int,
    ) -> list[int]:
        n = len(path)
        if n == 1:
            return [max(5, int(duration_minutes * TRACKS_PER_MINUTE[path[0]]))]

        avg_rate    = np.mean([TRACKS_PER_MINUTE[e] for e in path])
        total       = max(n * 3, int(duration_minutes * avg_rate))
        base        = total // n
        remainder   = total % n
        allocation  = [base] * n
        allocation[0]  += max(1, remainder // 2)
        allocation[-1] += remainder - remainder // 2
        return [max(2, a) for a in allocation]

    def _compute_energy_directions(self, path: list[str]) -> list[str]:
        directions = []
        for i, emotion in enumerate(path):
            if i == len(path) - 1:
                directions.append("neutral")
            else:
                curr = ENERGY_CENTERS.get(emotion, 0.5)
                nxt  = ENERGY_CENTERS.get(path[i + 1], 0.5)
                if nxt > curr + 0.1:
                    directions.append("ascending")
                elif nxt < curr - 0.1:
                    directions.append("descending")
                else:
                    directions.append("neutral")
        return directions

    def _select_tracks_for_segment(
        self,
        emotion: str,
        track_pool: list[TrackCandidate],
        n_tracks: int,
        energy_direction: str = "neutral",
        used_track_ids: Optional[set] = None,
    ) -> list[TrackCandidate]:
        used_track_ids = used_track_ids or set()

        candidates = [
            t for t in track_pool
            if t.emotion_label == emotion and t.track_id not in used_track_ids
        ]

        # Fallback: borrow low-confidence tracks from adjacent emotions
        if len(candidates) < n_tracks:
            adjacent = set(self.graph.get(emotion, {}).keys())
            fallback = [
                t for t in track_pool
                if t.emotion_label in adjacent
                and t.emotion_confidence < 0.65   # borderline = good bridge
                and t.track_id not in used_track_ids
                and t not in candidates
            ]
            candidates = candidates + fallback

        if energy_direction == "ascending":
            candidates.sort(key=lambda t: t.energy)
        elif energy_direction == "descending":
            candidates.sort(key=lambda t: t.energy, reverse=True)
        else:
            candidates.sort(key=lambda t: t.emotion_confidence, reverse=True)

        return candidates[:n_tracks]

    def plan(
        self,
        source: str,
        target: str,
        duration_minutes: int,
        track_pool: list[TrackCandidate],
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
        arc_path   = self.find_emotional_path(source, target)
        allocation = self._allocate_tracks_per_segment(arc_path, duration_minutes)
        directions = self._compute_energy_directions(arc_path)

        segments   = []
        used_ids:  set[str] = set()
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
            )
            for t in selected:
                used_ids.add(t.track_id)

            segments.append({
                "emotion":          emotion,
                "segment_index":    i,
                "tracks":           selected,
                "energy_direction": direction,
                "track_count":      len(selected),
            })
            flat_tracks.extend(selected)

        # Diagnostic: which emotions in the path had no tracks?
        emotion_counts = {e: 0 for e in arc_path}
        for seg in segments:
            emotion_counts[seg["emotion"]] = seg["track_count"]
        missing = [e for e, c in emotion_counts.items() if c == 0]

        total_duration_ms = sum(t.duration_ms for t in flat_tracks)

        return {
            "arc_path":          arc_path,
            "segments":          segments,
            "tracks":            flat_tracks,
            "total_tracks":      len(flat_tracks),
            "total_duration_ms": total_duration_ms,
            "readiness": {
                "pool_size":        len(track_pool),
                "missing_emotions": missing,
                "has_gaps":         len(missing) > 0,
            },
        }
