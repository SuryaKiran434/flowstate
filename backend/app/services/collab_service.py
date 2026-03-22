"""
Collaborative Arc Service — Flowstate
--------------------------------------
Manages multi-user arc sessions where N participants each contribute a source
emotion and a shared arc is planned toward a common target.

Aggregation strategy:
  For each emotion in the graph, compute the sum of shortest-path distances to
  every participant's source emotion (Dijkstra).  The emotion with the minimum
  total distance is the "centroid" — the most musically central starting point
  for a group with divergent emotional states.

Usage:
    svc = CollabArcService()
    session = svc.create_session(host_id, "peaceful", 30, db)
    svc.join_session(session.invite_code, guest_id, "sad", db)
    arc = svc.generate_arc(session.invite_code, host_id, db)
"""

import heapq
import random
import string
from typing import Optional

from app.models.collab import CollabSession, CollabParticipant
from app.services.arc_planner import ArcPlanner, EMOTION_GRAPH
from app.services.mood_parser import VALID_EMOTIONS


class CollabError(Exception):
    """Base exception for collab service errors."""


class SessionNotFoundError(CollabError):
    pass


class NotHostError(CollabError):
    pass


class AlreadyJoinedError(CollabError):
    pass


class SessionClosedError(CollabError):
    pass


def _shortest_distances(source: str, graph: dict[str, dict[str, float]]) -> dict[str, float]:
    """
    Dijkstra from source → dict of {emotion: min_cost}.
    Unreachable nodes get infinity.
    """
    dist: dict[str, float] = {e: float("inf") for e in graph}
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


def _generate_invite_code(length: int = 6) -> str:
    """Alphanumeric uppercase invite code, e.g. 'AZ3K7Q'."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


class CollabArcService:
    """Multi-user collaborative arc session manager."""

    def __init__(self, planner: Optional[ArcPlanner] = None):
        self._planner = planner or ArcPlanner()

    # ── Session lifecycle ──────────────────────────────────────────────────────

    def create_session(
        self,
        host_user_id: str,
        target_emotion: str,
        duration_minutes: int,
        db,
    ) -> CollabSession:
        """
        Create a new collab session.  Host is automatically added as participant
        with a placeholder source emotion of 'neutral' — they should call
        join_session() afterward to set their own state, or the host's emotion
        can be set via the same join endpoint.
        """
        target_emotion = target_emotion.lower()
        if target_emotion not in VALID_EMOTIONS:
            raise CollabError(f"Invalid target emotion: {target_emotion}")

        # Ensure unique invite code
        code = _generate_invite_code()
        while db.query(CollabSession).filter_by(invite_code=code).first():
            code = _generate_invite_code()

        session = CollabSession(
            host_user_id=str(host_user_id),
            invite_code=code,
            target_emotion=target_emotion,
            duration_minutes=duration_minutes,
            status="open",
        )
        db.add(session)
        db.flush()  # get session.id without commit
        return session

    def join_session(
        self,
        invite_code: str,
        user_id: str,
        source_emotion: str,
        db,
    ) -> CollabSession:
        """
        Join an open collab session with a source emotion.
        If the user already has a participant row, update their source emotion.
        Raises SessionNotFoundError for unknown codes, SessionClosedError when
        the session is no longer open.
        """
        session = db.query(CollabSession).filter_by(invite_code=invite_code.upper()).first()
        if not session:
            raise SessionNotFoundError(f"Session '{invite_code}' not found")
        if session.status != "open":
            raise SessionClosedError(f"Session '{invite_code}' is {session.status}")

        source_emotion = source_emotion.lower()
        if source_emotion not in VALID_EMOTIONS:
            raise CollabError(f"Invalid source emotion: {source_emotion}")

        existing = db.query(CollabParticipant).filter_by(
            session_id=session.id,
            user_id=str(user_id),
        ).first()

        if existing:
            existing.source_emotion = source_emotion
        else:
            db.add(CollabParticipant(
                session_id=session.id,
                user_id=str(user_id),
                source_emotion=source_emotion,
            ))

        db.flush()
        return session

    def get_session(self, invite_code: str, db) -> dict:
        """Return session metadata + all participants."""
        session = db.query(CollabSession).filter_by(invite_code=invite_code.upper()).first()
        if not session:
            raise SessionNotFoundError(f"Session '{invite_code}' not found")

        participants = db.query(CollabParticipant).filter_by(session_id=session.id).all()

        return {
            "invite_code":        session.invite_code,
            "host_user_id":       str(session.host_user_id),
            "target_emotion":     session.target_emotion,
            "duration_minutes":   session.duration_minutes,
            "status":             session.status,
            "aggregated_source":  session.aggregated_source,
            "participant_count":  len(participants),
            "participants": [
                {
                    "user_id":        str(p.user_id),
                    "source_emotion": p.source_emotion,
                    "joined_at":      p.joined_at.isoformat() if p.joined_at else None,
                }
                for p in participants
            ],
            "arc": session.arc_json,
        }

    def generate_arc(
        self,
        invite_code: str,
        requesting_user_id: str,
        db,
    ) -> dict:
        """
        Generate a shared arc for all participants.
        Only the host can trigger generation.
        Aggregates all source emotions to find the graph centroid, then plans
        from centroid → session.target_emotion using the host's track library.
        Sets session.status = 'ready' and stores arc in arc_json.
        """
        session = db.query(CollabSession).filter_by(invite_code=invite_code.upper()).first()
        if not session:
            raise SessionNotFoundError(f"Session '{invite_code}' not found")
        if str(session.host_user_id) != str(requesting_user_id):
            raise NotHostError("Only the session host can generate the arc")
        if session.status == "ready":
            # Already generated — return cached result
            return session.arc_json

        participants = db.query(CollabParticipant).filter_by(session_id=session.id).all()
        if not participants:
            raise CollabError("No participants have joined yet")

        source_emotions = [p.source_emotion for p in participants]
        centroid = self.aggregate_source_emotion(source_emotions)

        session.status = "generating"
        session.aggregated_source = centroid
        db.flush()

        arc = self._planner.plan_from_db(
            source=centroid,
            target=session.target_emotion,
            duration_minutes=session.duration_minutes,
            db=db,
            user_id=str(session.host_user_id),
        )

        # Attach collab metadata to the result
        arc_result = {
            **arc,
            "collab_meta": {
                "invite_code":     session.invite_code,
                "participant_count": len(participants),
                "source_emotions": source_emotions,
                "aggregated_source": centroid,
                "target_emotion":  session.target_emotion,
            },
        }

        session.arc_json = arc_result
        session.status = "ready"
        db.commit()

        return arc_result

    # ── Aggregation ────────────────────────────────────────────────────────────

    def aggregate_source_emotion(self, source_emotions: list[str]) -> str:
        """
        Find the graph-centroid emotion for a list of source emotions.

        For each candidate emotion, sum the shortest-path distances from all
        source emotions to that candidate (using bidirectional Dijkstra).
        The candidate with the lowest total distance is the centroid.

        Ties broken alphabetically for determinism.
        Single-emotion lists return that emotion unchanged.
        """
        if not source_emotions:
            return "neutral"
        if len(source_emotions) == 1:
            return source_emotions[0]

        # Pre-compute Dijkstra from every unique source
        unique_sources = list(set(source_emotions))
        dist_from = {s: _shortest_distances(s, EMOTION_GRAPH) for s in unique_sources}

        # For each candidate, sum cost of reaching it from every participant's source
        best_emotion = "neutral"
        best_total = float("inf")

        for candidate in sorted(VALID_EMOTIONS):   # sorted for determinism
            total = 0.0
            for src in source_emotions:
                d = dist_from[src].get(candidate, float("inf"))
                total += d
            if total < best_total:
                best_total = total
                best_emotion = candidate

        return best_emotion
