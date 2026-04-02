"""
Longitudinal Analyzer — Flowstate
------------------------------------
Analyses a user's session history to surface emotional listening patterns:

- Completion rate, total sessions, total minutes
- Consecutive-day streak
- Top starting emotions and most-travelled arc pairs
- Per-time-slot dominant source emotion (used by ContextSeeder)
- Recent arc timeline (last 8 sessions)

All methods accept an injected DB session and return plain dicts — no ORM
objects leave this module. All DB errors are caught and return empty/zero
values so the calling endpoint is never disrupted by a missing table.
"""

import datetime
import logging
from collections import Counter

from sqlalchemy import text

log = logging.getLogger(__name__)

# Time-slot boundaries (hour ranges, inclusive start / exclusive end)
_TIME_SLOTS = [
    (6, 10, "early morning"),
    (10, 13, "late morning"),
    (13, 17, "afternoon"),
    (17, 20, "early evening"),
    (20, 23, "late evening"),
    (23, 24, "night"),
    (0, 6, "night"),
]

_MIN_SLOT_SESSIONS = (
    3  # require this many sessions in a time slot before trusting its pattern
)


def _time_bucket(hour: int) -> str:
    for start, end, label in _TIME_SLOTS:
        if start <= hour < end:
            return label
    return "night"


class LongitudinalAnalyzer:
    """Derives emotional listening patterns from the sessions + session_tracks tables."""

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_insights(self, user_id: str, db) -> dict:
        """
        Return a full insights snapshot for the user.

        Returns:
            {
                "total_sessions":       int,
                "completed_sessions":   int,
                "completion_rate":      float,   # 0–1
                "total_minutes":        int,
                "avg_session_mins":     float,
                "streak_days":          int,
                "top_starting_emotions":[{"emotion": str, "count": int, "pct": float}],
                "top_arcs":             [{"source": str, "target": str, "count": int}],
                "time_slot_patterns":   {slot_label: {"source": str, "count": int}},
                "recent_arcs":          [{"session_id", "date", "source_emotion",
                                          "target_emotion", "duration_mins",
                                          "status", "tracks_played", "tracks_skipped"}],
            }
        """
        try:
            stats = self._session_stats(user_id, db)
            streak = self._streak(user_id, db)
            top_emotions = self._top_starting_emotions(user_id, db)
            top_arcs = self._top_arcs(user_id, db)
            slot_patterns = self._time_slot_patterns(user_id, db)
            recent = self._recent_arcs(user_id, db)
        except Exception as exc:
            log.warning("LongitudinalAnalyzer.get_insights failed: %s", exc)
            return _empty_insights()

        total = stats["total"]
        completed = stats["completed"]
        minutes = stats["total_minutes"] or 0

        return {
            "total_sessions": total,
            "completed_sessions": completed,
            "completion_rate": round(completed / total, 3) if total else 0.0,
            "total_minutes": minutes,
            "avg_session_mins": round(minutes / completed, 1) if completed else 0.0,
            "streak_days": streak,
            "top_starting_emotions": top_emotions,
            "top_arcs": top_arcs,
            "time_slot_patterns": slot_patterns,
            "recent_arcs": recent,
        }

    def get_time_slot_pattern(self, user_id: str, db, time_label: str) -> dict | None:
        """
        Return the dominant source emotion for a given time slot, or None
        if the user has fewer than _MIN_SLOT_SESSIONS in that slot.

        Used by ContextSeeder to personalise arc suggestions.
        """
        try:
            patterns = self._time_slot_patterns(user_id, db)
            entry = patterns.get(time_label)
            if entry and entry["count"] >= _MIN_SLOT_SESSIONS:
                return entry
            return None
        except Exception:
            return None

    # ── DB queries ─────────────────────────────────────────────────────────────

    def _session_stats(self, user_id: str, db) -> dict:
        row = db.execute(
            text("""
            SELECT
                COUNT(*)                                                  AS total,
                COUNT(*) FILTER (WHERE status = 'completed')              AS completed,
                COALESCE(
                  SUM(duration_mins) FILTER (WHERE status = 'completed'),
                  0
                )                                                         AS total_minutes
            FROM sessions
            WHERE user_id = cast(:uid AS uuid)
              AND status IN ('completed', 'abandoned')
        """),
            {"uid": user_id},
        ).fetchone()
        return {
            "total": row.total or 0,
            "completed": row.completed or 0,
            "total_minutes": int(row.total_minutes or 0),
        }

    def _streak(self, user_id: str, db) -> int:
        """Count consecutive calendar days (UTC) ending today or yesterday."""
        rows = db.execute(
            text("""
            SELECT DISTINCT
                DATE(started_at AT TIME ZONE 'UTC') AS session_date
            FROM sessions
            WHERE user_id    = cast(:uid AS uuid)
              AND status     = 'completed'
              AND started_at IS NOT NULL
            ORDER BY session_date DESC
            LIMIT 90
        """),
            {"uid": user_id},
        ).fetchall()

        if not rows:
            return 0

        dates = [r.session_date for r in rows]
        today = datetime.date.today()
        streak = 0
        expected = today

        for d in dates:
            if d == expected:
                streak += 1
                expected = expected - datetime.timedelta(days=1)
            elif d == today - datetime.timedelta(days=1) and streak == 0:
                # Allow streak starting from yesterday
                streak += 1
                expected = d - datetime.timedelta(days=1)
            else:
                break
        return streak

    def _top_starting_emotions(self, user_id: str, db, limit: int = 5) -> list[dict]:
        rows = db.execute(
            text("""
            SELECT source_emotion, COUNT(*) AS cnt
            FROM sessions
            WHERE user_id = cast(:uid AS uuid)
              AND status IN ('completed', 'abandoned')
            GROUP BY source_emotion
            ORDER BY cnt DESC
            LIMIT :lim
        """),
            {"uid": user_id, "lim": limit},
        ).fetchall()

        total = sum(r.cnt for r in rows)
        return [
            {
                "emotion": r.source_emotion,
                "count": r.cnt,
                "pct": round(r.cnt / total * 100, 1) if total else 0.0,
            }
            for r in rows
        ]

    def _top_arcs(self, user_id: str, db, limit: int = 5) -> list[dict]:
        rows = db.execute(
            text("""
            SELECT source_emotion, target_emotion, COUNT(*) AS cnt
            FROM sessions
            WHERE user_id = cast(:uid AS uuid)
              AND status IN ('completed', 'abandoned')
            GROUP BY source_emotion, target_emotion
            ORDER BY cnt DESC
            LIMIT :lim
        """),
            {"uid": user_id, "lim": limit},
        ).fetchall()

        return [
            {"source": r.source_emotion, "target": r.target_emotion, "count": r.cnt}
            for r in rows
        ]

    def _time_slot_patterns(self, user_id: str, db) -> dict[str, dict]:
        """
        For each time slot, find the most-common source emotion.
        Returns {slot_label: {"source": str, "count": int}}.
        """
        rows = db.execute(
            text("""
            SELECT
                source_emotion,
                EXTRACT(HOUR FROM started_at AT TIME ZONE 'UTC')::int AS hour,
                COUNT(*) AS cnt
            FROM sessions
            WHERE user_id    = cast(:uid AS uuid)
              AND status     IN ('completed', 'abandoned')
              AND started_at IS NOT NULL
            GROUP BY source_emotion, hour
            ORDER BY hour, cnt DESC
        """),
            {"uid": user_id},
        ).fetchall()

        # Bucket by time slot, keep only the top emotion per slot
        slot_counts: dict[str, Counter] = {}
        for r in rows:
            slot = _time_bucket(r.hour)
            if slot not in slot_counts:
                slot_counts[slot] = Counter()
            slot_counts[slot][r.source_emotion] += r.cnt

        result = {}
        for slot, counter in slot_counts.items():
            top_emotion, top_count = counter.most_common(1)[0]
            result[slot] = {"source": top_emotion, "count": top_count}
        return result

    def _recent_arcs(self, user_id: str, db, limit: int = 8) -> list[dict]:
        rows = db.execute(
            text("""
            SELECT
                s.id              AS session_id,
                s.source_emotion,
                s.target_emotion,
                s.duration_mins,
                s.status,
                s.started_at,
                COUNT(st.id)                                       AS tracks_total,
                COUNT(st.id) FILTER (WHERE st.played  = true)      AS tracks_played,
                COUNT(st.id) FILTER (WHERE st.skipped = true)      AS tracks_skipped
            FROM sessions s
            LEFT JOIN session_tracks st ON st.session_id = s.id
            WHERE s.user_id = cast(:uid AS uuid)
              AND s.status  IN ('completed', 'abandoned')
            GROUP BY s.id, s.source_emotion, s.target_emotion,
                     s.duration_mins, s.status, s.started_at
            ORDER BY s.started_at DESC NULLS LAST
            LIMIT :lim
        """),
            {"uid": user_id, "lim": limit},
        ).fetchall()

        return [
            {
                "session_id": str(r.session_id),
                "date": r.started_at.date().isoformat() if r.started_at else None,
                "source_emotion": r.source_emotion,
                "target_emotion": r.target_emotion,
                "duration_mins": r.duration_mins,
                "status": r.status,
                "tracks_played": r.tracks_played or 0,
                "tracks_skipped": r.tracks_skipped or 0,
            }
            for r in rows
        ]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _empty_insights() -> dict:
    return {
        "total_sessions": 0,
        "completed_sessions": 0,
        "completion_rate": 0.0,
        "total_minutes": 0,
        "avg_session_mins": 0.0,
        "streak_days": 0,
        "top_starting_emotions": [],
        "top_arcs": [],
        "time_slot_patterns": {},
        "recent_arcs": [],
    }
