"""
Unit tests for arc template endpoints.

Covers:
- POST /templates      — publish template, emotion validation
- GET  /templates      — list with filters, pagination, author names
- GET  /templates/{id} — single template, 404
- POST /templates/{id}/remix — fixed-path arc generation, remix_count increment,
                               library_not_ready propagation, warnings
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.templates import (
    publish_template,
    list_templates,
    get_template,
    remix_template,
    PublishRequest,
    RemixRequest,
)
from app.models.arc_template import ArcTemplate


# ─── Helpers ──────────────────────────────────────────────────────────────────

USER_ID    = str(uuid4())
TMPL_ID    = uuid4()
VALID_PATH = ["tense", "neutral", "peaceful"]


def _make_template(**kwargs):
    tmpl = MagicMock(spec=ArcTemplate)
    tmpl.id             = TMPL_ID
    tmpl.user_id        = uuid4()
    tmpl.display_name   = "My Template"
    tmpl.description    = "A test template"
    tmpl.source_emotion = "tense"
    tmpl.target_emotion = "peaceful"
    tmpl.arc_path       = list(VALID_PATH)
    tmpl.duration_mins  = 30
    tmpl.remix_count    = 0
    tmpl.created_at     = None
    for k, v in kwargs.items():
        setattr(tmpl, k, v)
    return tmpl


def _make_db(template=None, templates=None, user=None, users=None):
    db          = MagicMock()
    tmpl_query  = db.query.return_value
    # Support chained filter().first() and filter().count() / .all()
    tmpl_query.filter.return_value.first.return_value    = template
    tmpl_query.filter.return_value.count.return_value    = len(templates) if templates else 0
    order_chain = (
        tmpl_query.filter.return_value
        .order_by.return_value
        .offset.return_value
        .limit.return_value
    )
    order_chain.all.return_value = templates or []
    # user lookup
    tmpl_query.filter.return_value.all.return_value = users or (
        [user] if user else []
    )
    db.add    = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock(side_effect=lambda obj: None)
    return db


# ─── POST /templates ──────────────────────────────────────────────────────────

class TestPublishTemplate:
    def test_creates_and_returns_template_id(self):
        db = _make_db()
        new_tmpl = _make_template()

        def _refresh(obj):
            obj.id = TMPL_ID

        db.refresh.side_effect = _refresh

        body = PublishRequest(
            display_name="My Template",
            source_emotion="tense",
            target_emotion="peaceful",
            arc_path=list(VALID_PATH),
            duration_mins=30,
        )

        with patch("app.api.v1.endpoints.templates.ArcTemplate", return_value=new_tmpl):
            result = publish_template(body=body, user_id=USER_ID, db=db)

        assert "template_id" in result
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_rejects_invalid_emotion_in_arc_path(self):
        db = _make_db()
        body = PublishRequest(
            display_name="Bad",
            source_emotion="tense",
            target_emotion="peaceful",
            arc_path=["tense", "BADEMOTION", "peaceful"],
            duration_mins=30,
        )
        with pytest.raises(HTTPException) as exc:
            publish_template(body=body, user_id=USER_ID, db=db)
        assert exc.value.status_code == 422
        assert "BADEMOTION" in str(exc.value.detail)

    def test_rejects_invalid_source_emotion(self):
        db = _make_db()
        body = PublishRequest(
            display_name="Bad",
            source_emotion="BADSOURCE",
            target_emotion="peaceful",
            arc_path=list(VALID_PATH),
            duration_mins=30,
        )
        with pytest.raises(HTTPException) as exc:
            publish_template(body=body, user_id=USER_ID, db=db)
        assert exc.value.status_code == 422

    def test_rejects_invalid_target_emotion(self):
        db = _make_db()
        body = PublishRequest(
            display_name="Bad",
            source_emotion="tense",
            target_emotion="BADTARGET",
            arc_path=list(VALID_PATH),
            duration_mins=30,
        )
        with pytest.raises(HTTPException) as exc:
            publish_template(body=body, user_id=USER_ID, db=db)
        assert exc.value.status_code == 422

    def test_description_is_optional(self):
        db = _make_db()
        new_tmpl = _make_template()
        db.refresh.side_effect = lambda obj: None

        body = PublishRequest(
            display_name="No desc",
            source_emotion="tense",
            target_emotion="peaceful",
            arc_path=list(VALID_PATH),
            duration_mins=30,
        )
        with patch("app.api.v1.endpoints.templates.ArcTemplate", return_value=new_tmpl):
            result = publish_template(body=body, user_id=USER_ID, db=db)
        assert "template_id" in result


# ─── GET /templates ───────────────────────────────────────────────────────────

class TestListTemplates:
    def _db_for_list(self, templates, users=None):
        db          = MagicMock()
        q           = MagicMock()
        db.query.return_value = q
        # Filtering chain
        q.filter.return_value = q
        q.count.return_value  = len(templates)
        q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = templates
        # User lookup (second query() call)
        user_q = MagicMock()
        user_q.filter.return_value.all.return_value = users or []
        db.query.side_effect = [q, user_q]
        return db

    def test_returns_total_and_templates(self):
        tmpls = [_make_template(), _make_template(id=uuid4())]
        db    = self._db_for_list(tmpls)
        result = list_templates(limit=20, offset=0, source=None, target=None,
                                user_id=USER_ID, db=db)
        assert result["total"] == 2
        assert len(result["templates"]) == 2

    def test_template_dict_has_required_fields(self):
        tmpls  = [_make_template()]
        db     = self._db_for_list(tmpls)
        result = list_templates(limit=20, offset=0, source=None, target=None,
                                user_id=USER_ID, db=db)
        item = result["templates"][0]
        for field in ("id", "display_name", "source_emotion", "target_emotion",
                      "arc_path", "duration_mins", "remix_count", "author"):
            assert field in item

    def test_empty_list_when_no_templates(self):
        db     = self._db_for_list([])
        result = list_templates(limit=20, offset=0, source=None, target=None,
                                user_id=USER_ID, db=db)
        assert result["total"] == 0
        assert result["templates"] == []

    def test_invalid_source_filter_ignored(self):
        """An invalid emotion filter should just not be applied (no error)."""
        tmpls  = [_make_template()]
        db     = self._db_for_list(tmpls)
        # Should not raise
        result = list_templates(limit=20, offset=0, source="NOTANEMOTION",
                                target=None, user_id=USER_ID, db=db)
        assert "templates" in result


# ─── GET /templates/{id} ──────────────────────────────────────────────────────

class TestGetTemplate:
    def test_returns_template_with_author(self):
        tmpl = _make_template()
        author = MagicMock()
        author.display_name = "Alice"
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [tmpl, author]

        result = get_template(template_id=TMPL_ID, user_id=USER_ID, db=db)
        assert result["display_name"] == "My Template"
        assert result["author"] == "Alice"

    def test_raises_404_when_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(HTTPException) as exc:
            get_template(template_id=TMPL_ID, user_id=USER_ID, db=db)
        assert exc.value.status_code == 404

    def test_author_empty_string_when_user_deleted(self):
        tmpl = _make_template()
        db   = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [tmpl, None]
        result = get_template(template_id=TMPL_ID, user_id=USER_ID, db=db)
        assert result["author"] == ""


# ─── POST /templates/{id}/remix ───────────────────────────────────────────────

class TestRemixTemplate:
    def _mock_arc(self, has_gaps=False, missing=None):
        return {
            "arc_path":          list(VALID_PATH),
            "segments":          [],
            "tracks":            [],
            "total_tracks":      0,
            "total_duration_ms": 0,
            "readiness": {
                "has_gaps":         has_gaps,
                "missing_emotions": missing or [],
                "pool_size":        10,
            },
        }

    def test_increments_remix_count(self):
        tmpl = _make_template(remix_count=3)
        db   = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = tmpl

        body = RemixRequest()
        with patch("app.api.v1.endpoints.templates.learner.load_user_graph", return_value=None), \
             patch("app.api.v1.endpoints.templates._base_planner.plan_from_db",
                   return_value=self._mock_arc()):
            remix_template(template_id=TMPL_ID, body=body, user_id=USER_ID, db=db)

        assert tmpl.remix_count == 4
        db.commit.assert_called_once()

    def test_returns_template_provenance_fields(self):
        tmpl = _make_template()
        db   = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = tmpl

        body = RemixRequest()
        with patch("app.api.v1.endpoints.templates.learner.load_user_graph", return_value=None), \
             patch("app.api.v1.endpoints.templates._base_planner.plan_from_db",
                   return_value=self._mock_arc()):
            result = remix_template(template_id=TMPL_ID, body=body, user_id=USER_ID, db=db)

        assert result["template_id"]   == str(TMPL_ID)
        assert result["template_name"] == "My Template"
        assert "remixed_from"          in result
        assert "personalised"          in result

    def test_returns_arc_fields(self):
        tmpl = _make_template()
        db   = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = tmpl

        body = RemixRequest()
        with patch("app.api.v1.endpoints.templates.learner.load_user_graph", return_value=None), \
             patch("app.api.v1.endpoints.templates._base_planner.plan_from_db",
                   return_value=self._mock_arc()):
            result = remix_template(template_id=TMPL_ID, body=body, user_id=USER_ID, db=db)

        for field in ("arc_path", "segments", "tracks", "total_tracks",
                      "total_duration_ms", "duration_minutes", "warnings", "readiness"):
            assert field in result

    def test_raises_404_when_template_missing(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(HTTPException) as exc:
            remix_template(template_id=TMPL_ID, body=RemixRequest(),
                           user_id=USER_ID, db=db)
        assert exc.value.status_code == 404

    def test_propagates_library_not_ready(self):
        tmpl = _make_template()
        db   = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = tmpl

        not_ready = {
            "error":   "library_not_ready",
            "message": "Still processing",
            "arc_path": [], "segments": [], "tracks": [], "total_tracks": 0,
        }
        body = RemixRequest()
        with patch("app.api.v1.endpoints.templates.learner.load_user_graph", return_value=None), \
             patch("app.api.v1.endpoints.templates._base_planner.plan_from_db",
                   return_value=not_ready):
            with pytest.raises(HTTPException) as exc:
                remix_template(template_id=TMPL_ID, body=body, user_id=USER_ID, db=db)
        assert exc.value.status_code == 202

    def test_warning_emitted_when_has_gaps(self):
        tmpl = _make_template()
        db   = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = tmpl

        body = RemixRequest()
        with patch("app.api.v1.endpoints.templates.learner.load_user_graph", return_value=None), \
             patch("app.api.v1.endpoints.templates._base_planner.plan_from_db",
                   return_value=self._mock_arc(has_gaps=True, missing=["euphoric"])):
            result = remix_template(template_id=TMPL_ID, body=body, user_id=USER_ID, db=db)

        assert len(result["warnings"]) > 0
        assert "euphoric" in result["warnings"][0]

    def test_duration_override_respected(self):
        tmpl = _make_template(duration_mins=30)
        db   = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = tmpl

        body = RemixRequest(duration_mins=60)
        with patch("app.api.v1.endpoints.templates.learner.load_user_graph", return_value=None) as _, \
             patch("app.api.v1.endpoints.templates._base_planner.plan_from_db",
                   return_value=self._mock_arc()) as mock_plan:
            remix_template(template_id=TMPL_ID, body=body, user_id=USER_ID, db=db)

        call_kwargs = mock_plan.call_args.kwargs
        assert call_kwargs.get("duration_minutes") == 60

    def test_personalised_true_when_user_graph_available(self):
        tmpl = _make_template()
        db   = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = tmpl

        fake_graph = {"tense": {"neutral": 2.0}}
        body = RemixRequest()
        with patch("app.api.v1.endpoints.templates.learner.load_user_graph",
                   return_value=fake_graph), \
             patch("app.services.arc_planner.ArcPlanner.plan_from_db",
                   return_value=self._mock_arc()):
            # Use a fresh ArcPlanner that gets patched
            from app.services.arc_planner import ArcPlanner
            with patch.object(ArcPlanner, "plan_from_db", return_value=self._mock_arc()):
                result = remix_template(template_id=TMPL_ID, body=body, user_id=USER_ID, db=db)
        assert result["personalised"] is True
