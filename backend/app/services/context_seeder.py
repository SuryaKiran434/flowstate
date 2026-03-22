"""
Context Seeder — Flowstate
----------------------------
Infers a suggested arc based on contextual signals without requiring
the user to describe their mood:

  1. Time of day + day of week (from server clock)
  2. Recent session history (last 5 sessions from DB)

Claude synthesises these into a source→target suggestion with a
plain-English explanation. Falls back to a time-of-day heuristic
when the API key is unavailable or the API call fails.

Example output:
    {
        "source": "tense",
        "target": "peaceful",
        "interpretation": "It's Sunday evening and your last session was high-energy — time to decompress",
        "confidence": 0.82,
        "context_signals": ["late evening", "prior energetic session", "weekend"],
        "method": "claude",
    }
"""

import json
from datetime import datetime, timezone

import httpx

from app.core.config import get_settings
from app.services.mood_parser import VALID_EMOTIONS, EMOTION_DESCRIPTIONS
from app.services.longitudinal_analyzer import LongitudinalAnalyzer

# ── Time-of-day buckets ───────────────────────────────────────────────────────

_TIME_BUCKETS = [
    (6,  10, "early morning"),
    (10, 13, "late morning"),
    (13, 17, "afternoon"),
    (17, 20, "early evening"),
    (20, 23, "late evening"),
    (23, 24, "night"),
    (0,   6, "night"),
]

# (source, target) heuristics keyed by time bucket
_TIME_HEURISTICS: dict[str, tuple[str, str]] = {
    "early morning": ("neutral",     "focused"),
    "late morning":  ("focused",     "energetic"),
    "afternoon":     ("neutral",     "focused"),
    "early evening": ("neutral",     "happy"),
    "late evening":  ("tense",       "peaceful"),
    "night":         ("melancholic", "peaceful"),
}

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_ADJUST_SYSTEM_PROMPT = f"""You are a context-aware arc suggestion engine for Flowstate, a mood-arc music app.

You will be given:
1. The current time of day and day of week
2. The user's recent session history (last few sessions, if any)

Your job: suggest the single most appropriate emotional arc for this user RIGHT NOW.

Valid emotions:
{json.dumps({k: v for k, v in EMOTION_DESCRIPTIONS.items()}, indent=2)}

Rules:
- Source and target must be different valid emotions from the list above
- Base your suggestion on the time of day, typical human energy patterns, and recent history
- If recent sessions were abandoned early, the user may have been in the wrong mood — account for that
- Late evening / weekend evening → usually wind-down arcs (tense→peaceful, energetic→calm)
- Morning → usually build-up arcs (neutral→energetic, focused→happy)
- Post-energetic session → lower energy target is appropriate
- Keep interpretation concise, personalised, and warm — one sentence max

Respond with ONLY valid JSON, no other text:
{{
  "source": "<emotion_label>",
  "target": "<emotion_label>",
  "interpretation": "<one personalised sentence explaining why this arc fits right now>",
  "confidence": <float 0.0–1.0>,
  "context_signals": ["<signal 1>", "<signal 2>"]
}}"""


class ContextSeeder:
    """Suggests an arc based on time-of-day and recent session history."""

    def __init__(self):
        self.settings = get_settings()
        self.api_url  = "https://api.anthropic.com/v1/messages"
        self._analyzer = LongitudinalAnalyzer()

    async def suggest(self, user_id: str, db) -> dict:
        """
        Return a suggested arc for this user at this moment.
        Always returns a valid dict — never raises.
        """
        now        = datetime.now(timezone.utc)
        time_label = self._time_bucket(now.hour)
        day_label  = _DAYS[now.weekday()]
        is_weekend = now.weekday() >= 5

        recent_sessions = self._load_recent_sessions(db, user_id)

        # Longitudinal pattern: dominant source emotion for this time slot
        slot_pattern = self._analyzer.get_time_slot_pattern(user_id, db, time_label)

        context_signals = [time_label, day_label]
        if is_weekend:
            context_signals.append("weekend")
        for s in recent_sessions[:2]:
            context_signals.append(
                f"recent session: {s['source']}→{s['target']} ({s['status']})"
            )
        if slot_pattern:
            context_signals.append(
                f"historical pattern: usually starts {time_label} with {slot_pattern['source']}"
                f" ({slot_pattern['count']} times)"
            )

        if self.settings.anthropic_api_key:
            try:
                result = await self._call_claude(
                    now, day_label, time_label, recent_sessions, slot_pattern
                )
                result["context_signals"] = context_signals
                result["method"] = "claude"
                return result
            except Exception as e:
                print(f"Context seeder Claude call failed: {e} — using heuristic fallback")

        return self._heuristic(time_label, recent_sessions, context_signals, slot_pattern)

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _load_recent_sessions(self, db, user_id: str) -> list[dict]:
        """Load up to 5 most recent sessions for this user."""
        try:
            from sqlalchemy import text
            rows = db.execute(text("""
                SELECT source_emotion, target_emotion, status, started_at, completed_at
                FROM sessions
                WHERE user_id = cast(:uid as uuid)
                ORDER BY created_at DESC
                LIMIT 5
            """), {"uid": user_id}).fetchall()

            return [
                {
                    "source":   r.source_emotion,
                    "target":   r.target_emotion,
                    "status":   r.status,
                    "duration": (
                        int((r.completed_at - r.started_at).total_seconds() / 60)
                        if r.completed_at and r.started_at else None
                    ),
                }
                for r in rows
            ]
        except Exception:
            return []

    # ── Claude call ───────────────────────────────────────────────────────────

    async def _call_claude(
        self,
        now: datetime,
        day_label: str,
        time_label: str,
        recent_sessions: list[dict],
        slot_pattern: dict | None = None,
    ) -> dict:
        context_lines = [
            f"Current time: {now.strftime('%H:%M')} ({time_label})",
            f"Day of week: {day_label}",
        ]
        if recent_sessions:
            context_lines.append("Recent sessions (newest first):")
            for s in recent_sessions:
                dur = f", {s['duration']} min" if s["duration"] else ""
                context_lines.append(f"  - {s['source']} → {s['target']} [{s['status']}{dur}]")
        else:
            context_lines.append("No recent session history.")
        if slot_pattern:
            context_lines.append(
                f"Historical pattern: this user most often starts {time_label} sessions"
                f" from '{slot_pattern['source']}' ({slot_pattern['count']} times)."
            )

        context = "\n".join(context_lines)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self.api_url,
                headers={
                    "Content-Type":      "application/json",
                    "x-api-key":         self.settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model":      "claude-haiku-4-5",
                    "max_tokens": 200,
                    "system":     _ADJUST_SYSTEM_PROMPT,
                    "messages":   [{"role": "user", "content": context}],
                },
            )
            response.raise_for_status()
            data = response.json()

            raw = data["content"][0]["text"].strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            parsed = json.loads(raw)
            source = parsed.get("source", "").lower()
            target = parsed.get("target", "").lower()

            if source not in VALID_EMOTIONS:
                raise ValueError(f"Invalid source: {source}")
            if target not in VALID_EMOTIONS:
                raise ValueError(f"Invalid target: {target}")
            if source == target:
                target = self._adjacent_down(source)

            return {
                "source":         source,
                "target":         target,
                "interpretation": parsed.get("interpretation", f"From {source} to {target}"),
                "confidence":     float(parsed.get("confidence", 0.7)),
            }

    # ── Heuristic fallback ────────────────────────────────────────────────────

    def _heuristic(
        self,
        time_label: str,
        recent_sessions: list[dict],
        context_signals: list[str],
        slot_pattern: dict | None = None,
    ) -> dict:
        source, target = _TIME_HEURISTICS.get(time_label, ("neutral", "peaceful"))

        # Use longitudinal pattern if confident enough
        if slot_pattern and slot_pattern["source"] in VALID_EMOTIONS:
            source = slot_pattern["source"]

        # If the last session ended at a high-energy target, wind down from there
        if recent_sessions:
            last = recent_sessions[0]
            high_energy = {"energetic", "euphoric", "angry", "tense"}
            if last["status"] in ("completed", "active") and last["target"] in high_energy:
                source = last["target"]
                target = "peaceful"

        interpretation = (
            f"Based on the {time_label} and your listening history, "
            f"a {source} → {target} journey feels right"
        )

        return {
            "source":          source,
            "target":          target,
            "interpretation":  interpretation,
            "confidence":      0.6,
            "context_signals": context_signals,
            "method":          "heuristic",
        }

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _time_bucket(hour: int) -> str:
        for start, end, label in _TIME_BUCKETS:
            if start <= hour < end:
                return label
        return "night"

    @staticmethod
    def _adjacent_down(emotion: str) -> str:
        """Return a naturally lower-energy adjacent emotion."""
        down = {
            "energetic": "happy", "euphoric": "happy",  "angry":       "tense",
            "tense":     "neutral", "happy":  "neutral", "focused":     "peaceful",
            "romantic":  "peaceful", "nostalgic": "peaceful", "neutral": "peaceful",
            "melancholic": "sad",  "sad":    "neutral",  "peaceful":    "neutral",
        }
        return down.get(emotion, "peaceful")
