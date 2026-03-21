"""
Unit tests for GraphLearner — personalised emotion graph weights.

Covers:
- _query_signals: counts completions and skips correctly from DB rows
- _query_signals: returns empty dicts on DB error (never raises)
- _apply_adjustments: skip penalty increases edge weight
- _apply_adjustments: completion bonus decreases edge weight
- _apply_adjustments: multiplier clamped to [MIN_MULT, MAX_MULT]
- _apply_adjustments: edges with no signal are unchanged
- load_user_graph: returns None when total signals < MIN_SIGNALS
- load_user_graph: returns modified dict when enough signals exist
- load_user_graph: returned graph has same structure as EMOTION_GRAPH
- explain_adjustments: only returns edges that actually changed
- explain_adjustments: returns empty list when insufficient data
- GET /arc/user-graph endpoint: personalised=False when no data
- GET /arc/user-graph endpoint: personalised=True and adjustments populated
"""

from collections import defaultdict
from copy import deepcopy
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.services.arc_planner import EMOTION_GRAPH
from app.services.graph_learner import (
    GraphLearner,
    SKIP_PENALTY,
    COMPLETION_BONUS,
    MIN_MULT,
    MAX_MULT,
    MIN_SIGNALS,
)

USER_ID = str(uuid4())


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_row(from_e, to_e, from_played=True, to_skipped=False, to_played=False):
    r = MagicMock()
    r.from_emotion = from_e
    r.to_emotion   = to_e
    r.from_played  = from_played
    r.to_skipped   = to_skipped
    r.to_played    = to_played
    return r


def _make_db(rows):
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = rows
    return db


# ─── _query_signals ───────────────────────────────────────────────────────────

class TestQuerySignals:
    def test_played_rows_counted_as_completions(self):
        rows = [_make_row("tense", "neutral", from_played=True, to_played=True)]
        gl   = GraphLearner()
        comps, skips = gl._query_signals(USER_ID, _make_db(rows))
        assert comps[("tense", "neutral")] == 1
        assert skips[("tense", "neutral")]  == 0

    def test_skipped_rows_counted_as_skips(self):
        rows = [_make_row("tense", "neutral", to_skipped=True)]
        gl   = GraphLearner()
        comps, skips = gl._query_signals(USER_ID, _make_db(rows))
        assert skips[("tense", "neutral")]  == 1
        assert comps[("tense", "neutral")] == 0

    def test_db_error_returns_empty(self):
        db = MagicMock()
        db.execute.side_effect = Exception("DB failure")
        gl = GraphLearner()
        comps, skips = gl._query_signals(USER_ID, db)
        assert len(comps) == 0
        assert len(skips)  == 0

    def test_multiple_rows_aggregated(self):
        rows = [
            _make_row("tense", "neutral", from_played=True, to_played=True),
            _make_row("tense", "neutral", from_played=True, to_played=True),
            _make_row("tense", "neutral", to_skipped=True),
        ]
        gl   = GraphLearner()
        comps, skips = gl._query_signals(USER_ID, _make_db(rows))
        assert comps[("tense", "neutral")] == 2
        assert skips[("tense", "neutral")]  == 1

    def test_unplayed_from_track_not_counted_as_completion(self):
        # from_played=False means user skipped the from-track — not a clean transition
        rows = [_make_row("tense", "neutral", from_played=False, to_played=True)]
        gl   = GraphLearner()
        comps, skips = gl._query_signals(USER_ID, _make_db(rows))
        assert comps[("tense", "neutral")] == 0


# ─── _apply_adjustments ───────────────────────────────────────────────────────

class TestApplyAdjustments:
    def test_skip_penalty_increases_weight(self):
        gl    = GraphLearner()
        base  = EMOTION_GRAPH["tense"]["focused"]
        skips = defaultdict(int, {("tense", "focused"): 1})
        comps = defaultdict(int)

        adjusted = gl._apply_adjustments(comps, skips)
        new_w    = adjusted["tense"]["focused"]

        assert new_w > base
        expected = base * max(MIN_MULT, min(MAX_MULT, 1.0 + 1 * SKIP_PENALTY))
        assert abs(new_w - expected) < 0.001

    def test_completion_bonus_decreases_weight(self):
        gl    = GraphLearner()
        base  = EMOTION_GRAPH["tense"]["focused"]
        comps = defaultdict(int, {("tense", "focused"): 1})
        skips = defaultdict(int)

        adjusted = gl._apply_adjustments(comps, skips)
        new_w    = adjusted["tense"]["focused"]

        assert new_w < base
        expected = base * max(MIN_MULT, min(MAX_MULT, 1.0 - 1 * COMPLETION_BONUS))
        assert abs(new_w - expected) < 0.001

    def test_multiplier_clamped_at_max(self):
        gl    = GraphLearner()
        skips = defaultdict(int, {("tense", "focused"): 100})  # extreme skip count
        comps = defaultdict(int)

        adjusted = gl._apply_adjustments(comps, skips)
        base_w   = EMOTION_GRAPH["tense"]["focused"]
        # multiplier should be clamped to MAX_MULT
        assert adjusted["tense"]["focused"] <= base_w * MAX_MULT + 0.001

    def test_multiplier_clamped_at_min(self):
        gl    = GraphLearner()
        comps = defaultdict(int, {("tense", "focused"): 100})  # extreme completions
        skips = defaultdict(int)

        adjusted = gl._apply_adjustments(comps, skips)
        base_w   = EMOTION_GRAPH["tense"]["focused"]
        assert adjusted["tense"]["focused"] >= base_w * MIN_MULT - 0.001

    def test_edges_with_no_signal_unchanged(self):
        gl       = GraphLearner()
        comps    = defaultdict(int)
        skips    = defaultdict(int)
        adjusted = gl._apply_adjustments(comps, skips)

        for from_e, neighbors in EMOTION_GRAPH.items():
            for to_e, base_w in neighbors.items():
                assert abs(adjusted[from_e][to_e] - base_w) < 0.001


# ─── load_user_graph ──────────────────────────────────────────────────────────

class TestLoadUserGraph:
    def test_returns_none_when_signals_below_minimum(self):
        rows = [_make_row("tense", "neutral", from_played=True, to_played=True)]
        # 1 completion < MIN_SIGNALS
        assert len(rows) < MIN_SIGNALS
        gl = GraphLearner()
        assert gl.load_user_graph(USER_ID, _make_db(rows)) is None

    def test_returns_graph_when_enough_signals(self):
        rows = [
            _make_row("tense", "neutral", from_played=True, to_played=True)
            for _ in range(MIN_SIGNALS)
        ]
        gl     = GraphLearner()
        result = gl.load_user_graph(USER_ID, _make_db(rows))
        assert result is not None
        assert isinstance(result, dict)

    def test_returned_graph_has_same_structure_as_default(self):
        rows = [
            _make_row("tense", "neutral", from_played=True, to_played=True)
            for _ in range(MIN_SIGNALS)
        ]
        gl     = GraphLearner()
        result = gl.load_user_graph(USER_ID, _make_db(rows))
        # Every node and edge from EMOTION_GRAPH should be present
        for from_e, neighbors in EMOTION_GRAPH.items():
            assert from_e in result
            for to_e in neighbors:
                assert to_e in result[from_e]

    def test_skipped_edge_weight_higher_than_global(self):
        rows = [
            _make_row("tense", "focused", to_skipped=True)
            for _ in range(MIN_SIGNALS)
        ]
        gl     = GraphLearner()
        result = gl.load_user_graph(USER_ID, _make_db(rows))
        assert result["tense"]["focused"] > EMOTION_GRAPH["tense"]["focused"]


# ─── explain_adjustments ──────────────────────────────────────────────────────

class TestExplainAdjustments:
    def test_returns_empty_list_below_minimum_signals(self):
        rows = [_make_row("tense", "neutral", from_played=True, to_played=True)]
        gl   = GraphLearner()
        assert gl.explain_adjustments(USER_ID, _make_db(rows)) == []

    def test_returns_changed_edges_only(self):
        rows = [
            _make_row("tense", "focused", to_skipped=True)
            for _ in range(MIN_SIGNALS)
        ]
        gl     = GraphLearner()
        result = gl.explain_adjustments(USER_ID, _make_db(rows))
        # At least the tense→focused edge should appear
        assert any(r["from"] == "tense" and r["to"] == "focused" for r in result)
        # Untouched edges should not appear
        edge_pairs = {(r["from"], r["to"]) for r in result}
        assert ("tense", "neutral") not in edge_pairs  # not touched

    def test_result_contains_required_fields(self):
        rows = [
            _make_row("tense", "focused", to_skipped=True)
            for _ in range(MIN_SIGNALS)
        ]
        gl    = GraphLearner()
        items = gl.explain_adjustments(USER_ID, _make_db(rows))
        assert len(items) > 0
        for item in items:
            for field in ("from", "to", "base_weight", "adjusted_weight",
                          "completions", "skips", "multiplier"):
                assert field in item


# ─── GET /arc/user-graph endpoint ─────────────────────────────────────────────

class TestUserGraphEndpoint:
    def test_not_personalised_when_no_data(self):
        from app.api.v1.endpoints.arc import get_user_graph

        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []

        result = get_user_graph(user_id=USER_ID, db=db)

        assert result["personalised"] is False
        assert result["adjustments"]  == []
        assert "global_graph" in result

    def test_personalised_when_enough_signals(self):
        from app.api.v1.endpoints.arc import get_user_graph

        rows = [
            _make_row("tense", "focused", to_skipped=True)
            for _ in range(MIN_SIGNALS)
        ]
        db = _make_db(rows)

        result = get_user_graph(user_id=USER_ID, db=db)

        assert result["personalised"] is True
        assert len(result["adjustments"]) > 0

    def test_generate_arc_includes_personalised_flag(self):
        """generate_arc response must include personalised boolean."""
        from app.api.v1.endpoints.arc import generate_arc, ArcRequest
        import asyncio

        db   = MagicMock()
        db.execute.return_value.fetchall.return_value = []  # no signals → not personalised

        mock_arc = {
            "arc_path": ["tense", "peaceful"], "segments": [], "tracks": [],
            "total_tracks": 0, "total_duration_ms": 0,
            "readiness": {"has_gaps": False, "missing_emotions": [], "pool_size": 0},
        }
        mock_mood = {
            "source": "tense", "target": "peaceful",
            "interpretation": "...", "method": "fallback",
        }

        async def run():
            with patch("app.api.v1.endpoints.arc.parser.parse", return_value=mock_mood), \
                 patch("app.api.v1.endpoints.arc.planner.plan_from_db", return_value=mock_arc):
                return await generate_arc(
                    request=ArcRequest(mood_text="I feel tense", duration_minutes=20),
                    user_id=USER_ID,
                    db=db,
                )

        result = asyncio.get_event_loop().run_until_complete(run())
        assert "personalised" in result
        assert result["personalised"] is False
