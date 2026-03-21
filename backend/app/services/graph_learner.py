"""
Graph Learner — Flowstate
---------------------------
Learns per-user emotion transition weights from skip and play telemetry,
producing a personalised copy of the arc-planner emotion graph.

Algorithm
---------
For every consecutive pair of tracks (A → B) a user has encountered:

  positive signal:  track A was played through (played=True, skipped=False)
                    then the user continued to track B
  negative signal:  track B was skipped (skipped=True) after arriving from A

Weight adjustment per transition:
  multiplier = 1.0
             + skips(A→B) * SKIP_PENALTY          # penalise avoided transitions
             - completions(A→B) * COMPLETION_BONUS  # reward preferred transitions
  final_weight = base_weight * clamp(multiplier, MIN_MULT, MAX_MULT)

A minimum of MIN_SIGNALS total observations is required before personalisation
is applied; otherwise None is returned so callers fall back to the global graph.

Output
------
  load_user_graph(user_id, db) → dict | None
    Returns a personalised graph dict (same schema as EMOTION_GRAPH), or None
    if the user has insufficient listening history.

  explain_adjustments(user_id, db) → list[dict]
    Returns a human-readable list of which edges were adjusted and by how much,
    for the diagnostic /arc/user-graph endpoint.
"""

from collections import defaultdict
from copy import deepcopy

from app.services.arc_planner import EMOTION_GRAPH

# ── Tuning constants ──────────────────────────────────────────────────────────

SKIP_PENALTY      = 0.4   # each skip adds this to the multiplier (makes edge heavier)
COMPLETION_BONUS  = 0.25  # each completion subtracts this (makes edge lighter)
MIN_MULT          = 0.4   # never reduce an edge below 40 % of its base weight
MAX_MULT          = 3.0   # never inflate an edge above 3× its base weight
MIN_SIGNALS       = 5     # minimum total observations before personalisation kicks in


class GraphLearner:
    """
    Learns personalized emotion graph weights from a user's session telemetry.
    Stateless — all data is fetched fresh from the DB on each call.
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def load_user_graph(self, user_id: str, db) -> dict | None:
        """
        Return a personalised emotion graph for this user, or None if the user
        has fewer than MIN_SIGNALS observed transitions (not enough data yet).
        """
        completions, skips = self._query_signals(user_id, db)
        total = sum(completions.values()) + sum(skips.values())
        if total < MIN_SIGNALS:
            return None

        return self._apply_adjustments(completions, skips)

    def explain_adjustments(self, user_id: str, db) -> list[dict]:
        """
        Return a list of edge adjustments for diagnostics.
        Each entry: {from, to, base_weight, adjusted_weight, completions, skips, multiplier}
        Only edges that were actually adjusted are included.
        """
        completions, skips = self._query_signals(user_id, db)
        total = sum(completions.values()) + sum(skips.values())
        if total < MIN_SIGNALS:
            return []

        adjusted = self._apply_adjustments(completions, skips)
        result   = []

        for from_e, neighbors in EMOTION_GRAPH.items():
            for to_e, base_w in neighbors.items():
                adj_w = adjusted.get(from_e, {}).get(to_e, base_w)
                if abs(adj_w - base_w) > 0.01:   # only report changed edges
                    key  = (from_e, to_e)
                    mult = adj_w / base_w if base_w else 1.0
                    result.append({
                        "from":            from_e,
                        "to":              to_e,
                        "base_weight":     round(base_w, 3),
                        "adjusted_weight": round(adj_w, 3),
                        "completions":     completions[key],
                        "skips":           skips[key],
                        "multiplier":      round(mult, 3),
                    })

        return sorted(result, key=lambda x: abs(x["adjusted_weight"] - x["base_weight"]), reverse=True)

    # ── DB signal query ───────────────────────────────────────────────────────

    def _query_signals(
        self, user_id: str, db
    ) -> tuple[defaultdict, defaultdict]:
        """
        Query consecutive-track pairs across all completed/active sessions for
        this user. Returns (completions, skips) defaultdict counters keyed by
        (from_emotion, to_emotion) tuples.
        """
        completions: defaultdict = defaultdict(int)
        skips:       defaultdict = defaultdict(int)

        try:
            from sqlalchemy import text
            rows = db.execute(text("""
                SELECT
                    st1.emotion_label  AS from_emotion,
                    st2.emotion_label  AS to_emotion,
                    st1.played         AS from_played,
                    st2.skipped        AS to_skipped,
                    st2.played         AS to_played
                FROM session_tracks st1
                JOIN session_tracks st2
                    ON  st2.session_id = st1.session_id
                    AND st2.position   = st1.position + 1
                JOIN sessions s ON s.id = st1.session_id
                WHERE s.user_id          = cast(:uid AS uuid)
                  AND s.status           IN ('active', 'completed', 'abandoned')
                  AND st1.emotion_label  IS NOT NULL
                  AND st2.emotion_label  IS NOT NULL
                  AND st1.emotion_label  != st2.emotion_label
            """), {"uid": user_id}).fetchall()

        except Exception:
            return completions, skips

        for row in rows:
            key = (row.from_emotion, row.to_emotion)
            if row.to_skipped:
                skips[key] += 1
            elif row.from_played and row.to_played:
                # Both sides of the transition were played — positive signal
                completions[key] += 1

        return completions, skips

    # ── Weight adjustment ─────────────────────────────────────────────────────

    def _apply_adjustments(
        self,
        completions: defaultdict,
        skips: defaultdict,
    ) -> dict:
        adjusted = deepcopy(EMOTION_GRAPH)

        for from_e, neighbors in adjusted.items():
            for to_e in neighbors:
                key       = (from_e, to_e)
                n_skips   = skips[key]
                n_comps   = completions[key]

                if n_skips == 0 and n_comps == 0:
                    continue  # no signal for this edge — keep default

                mult = 1.0 + n_skips * SKIP_PENALTY - n_comps * COMPLETION_BONUS
                mult = max(MIN_MULT, min(MAX_MULT, mult))
                neighbors[to_e] = round(neighbors[to_e] * mult, 4)

        return adjusted
