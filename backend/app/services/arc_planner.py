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

# Perceptual distance matrix between emotion states.
# Lower weight = smoother, more natural transition for listeners.
# Derived from valence/energy proximity + music theory (e.g., relative modes).
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

# Approximate tracks per minute for each emotion state (used for session sizing)
TRACKS_PER_MINUTE: dict[str, float] = {
    "energetic": 0.25,   # ~4 min avg track
    "happy": 0.27,
    "euphoric": 0.25,
    "peaceful": 0.20,    # ~5 min avg track
    "focused": 0.22,
    "romantic": 0.20,
    "nostalgic": 0.22,
    "neutral": 0.25,
    "melancholic": 0.20,
    "sad": 0.18,
    "tense": 0.28,
    "angry": 0.30,
}


@dataclass
class TrackCandidate:
    track_id: UUID
    spotify_id: str
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
    """Priority queue entry for Dijkstra."""
    cost: float
    node: str = field(compare=False)
    path: list[str] = field(compare=False)


class ArcPlanner:
    """
    Generates an emotionally coherent playlist arc.

    Usage:
        planner = ArcPlanner()
        arc = planner.plan(
            source="tense",
            target="peaceful",
            duration_minutes=45,
            track_pool=[...]   # list of TrackCandidate
        )
    """

    def __init__(self, graph: dict[str, dict[str, float]] = None):
        self.graph = graph or EMOTION_GRAPH

    def find_emotional_path(self, source: str, target: str) -> list[str]:
        """
        Modified Dijkstra on the emotion graph.
        Returns the sequence of emotion nodes from source to target.

        Time complexity: O((V + E) log V) where V=12 nodes, E=~30 edges
        """
        if source == target:
            return [source]

        if source not in self.graph:
            raise ValueError(f"Unknown source emotion: {source}")
        if target not in self.graph:
            raise ValueError(f"Unknown target emotion: {target}")

        # Priority queue: (cost, current_node, path)
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

            neighbors = self.graph.get(current_node, {})
            for neighbor, edge_weight in neighbors.items():
                new_cost = current_cost + edge_weight
                if neighbor not in visited or visited[neighbor] > new_cost:
                    heapq.heappush(pq, _PQEntry(
                        cost=new_cost,
                        node=neighbor,
                        path=path + [neighbor]
                    ))

        # No path found — return direct [source, target] as fallback
        return [source, target]

    def _allocate_tracks_per_segment(
        self,
        path: list[str],
        duration_minutes: int
    ) -> list[int]:
        """
        Distribute track slots across path segments proportionally.
        First and last segments get slightly more tracks for a proper start/end.
        """
        n = len(path)
        if n == 1:
            total_tracks = max(5, int(duration_minutes * TRACKS_PER_MINUTE[path[0]]))
            return [total_tracks]

        # Estimate total tracks
        avg_rate = np.mean([TRACKS_PER_MINUTE[e] for e in path])
        total_tracks = max(n * 3, int(duration_minutes * avg_rate))

        # Base allocation per segment
        base = total_tracks // n
        remainder = total_tracks % n

        allocation = [base] * n

        # Give start and end segments a bit more weight
        allocation[0] += max(1, remainder // 2)
        allocation[-1] += remainder - remainder // 2

        return [max(2, a) for a in allocation]

    def _select_tracks_for_segment(
        self,
        emotion: str,
        track_pool: list[TrackCandidate],
        n_tracks: int,
        energy_direction: str = "neutral",  # "ascending" | "descending" | "neutral"
        used_track_ids: Optional[set] = None,
    ) -> list[TrackCandidate]:
        """
        Select the best n_tracks from the pool for a given emotion segment.
        Filters by emotion label, sorts by energy to create smooth transitions.
        """
        used_track_ids = used_track_ids or set()

        # Filter: matching emotion, not yet used
        candidates = [
            t for t in track_pool
            if t.emotion_label == emotion and t.track_id not in used_track_ids
        ]

        # Fallback: if not enough labeled tracks, relax to confidence > 0.4
        if len(candidates) < n_tracks:
            fallback = [
                t for t in track_pool
                if t.emotion_label == emotion
                or t.emotion_confidence < 0.5  # borderline tracks work as bridges
                and t.track_id not in used_track_ids
            ]
            candidates = list({t.track_id: t for t in candidates + fallback}.values())

        # Sort by energy for smooth transitions within segment
        if energy_direction == "ascending":
            candidates.sort(key=lambda t: t.energy)
        elif energy_direction == "descending":
            candidates.sort(key=lambda t: t.energy, reverse=True)
        else:
            # Neutral: sort by confidence descending (best matches first)
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
        Main entry point. Returns a structured arc with ordered tracks.

        Returns:
            {
                "arc_path": ["tense", "neutral", "focused", "peaceful"],
                "segments": [
                    {
                        "emotion": "tense",
                        "tracks": [TrackCandidate, ...],
                        "segment_index": 0
                    },
                    ...
                ],
                "tracks": [TrackCandidate, ...],  # flat ordered list
                "total_tracks": 12,
            }
        """
        # Step 1: Find emotional path
        arc_path = self.find_emotional_path(source, target)

        # Step 2: Allocate track counts per segment
        allocation = self._allocate_tracks_per_segment(arc_path, duration_minutes)

        # Step 3: Determine energy direction per segment transition
        energy_directions = self._compute_energy_directions(arc_path)

        # Step 4: Select tracks for each segment
        segments = []
        used_ids: set[UUID] = set()
        flat_tracks: list[TrackCandidate] = []

        for i, (emotion, n_tracks, direction) in enumerate(
            zip(arc_path, allocation, energy_directions)
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
                "emotion": emotion,
                "segment_index": i,
                "tracks": selected,
                "energy_direction": direction,
            })
            flat_tracks.extend(selected)

        return {
            "arc_path": arc_path,
            "segments": segments,
            "tracks": flat_tracks,
            "total_tracks": len(flat_tracks),
        }

    def _compute_energy_directions(self, path: list[str]) -> list[str]:
        """
        For each segment, determine if energy should ascend, descend, or stay neutral.
        Based on relative energy levels of consecutive emotion nodes.
        """
        # Approximate energy centers per emotion
        energy_centers = {
            "energetic": 0.85, "euphoric": 0.85, "angry": 0.85, "tense": 0.75,
            "happy": 0.65, "focused": 0.50, "neutral": 0.45, "romantic": 0.40,
            "nostalgic": 0.38, "peaceful": 0.25, "melancholic": 0.25, "sad": 0.20,
        }

        directions = []
        for i, emotion in enumerate(path):
            if i == len(path) - 1:
                directions.append("neutral")
            else:
                curr_energy = energy_centers.get(emotion, 0.5)
                next_energy = energy_centers.get(path[i + 1], 0.5)
                if next_energy > curr_energy + 0.1:
                    directions.append("ascending")
                elif next_energy < curr_energy - 0.1:
                    directions.append("descending")
                else:
                    directions.append("neutral")

        return directions
