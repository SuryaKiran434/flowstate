"""
Unit tests for app/services/mood_parser.py

Coverage targets:
- parse() routing (Claude path / fallback path / empty input)
- _call_claude() success, markdown fences, HTTP errors, invalid JSON
- _adjacent_emotion() all 12 emotions
- _fallback_from_keywords() keyword detection, negative/positive routing
- _fallback() return structure
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.mood_parser import VALID_EMOTIONS, MoodParser


def _build_parser(settings):
    """Construct a MoodParser with a mocked get_settings."""
    with patch("app.services.mood_parser.get_settings", return_value=settings):
        return MoodParser()


def _make_httpx_response(payload: dict, status_code: int = 200):
    """Build a mock httpx.Response that returns payload from .json()."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=MagicMock(),
        )
    else:
        mock_resp.raise_for_status = MagicMock()  # no-op
    return mock_resp


def _patch_httpx(mock_resp):
    """Context manager that patches httpx.AsyncClient to return mock_resp."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return patch("httpx.AsyncClient", return_value=mock_client)


# ─── parse() routing ──────────────────────────────────────────────────────────

class TestParseRouting:
    async def test_empty_string_returns_fallback(self, mock_settings_no_key):
        parser = _build_parser(mock_settings_no_key)
        result = await parser.parse("")
        assert result["method"] == "fallback"
        assert result["source"] == "neutral"
        assert result["target"] == "peaceful"

    async def test_whitespace_only_returns_fallback(self, mock_settings_no_key):
        parser = _build_parser(mock_settings_no_key)
        result = await parser.parse("   ")
        assert result["method"] == "fallback"

    async def test_no_api_key_skips_claude(self, mock_settings_no_key):
        parser = _build_parser(mock_settings_no_key)
        result = await parser.parse("I feel stressed")
        assert result["method"] == "fallback"

    async def test_with_api_key_uses_claude(self, mock_settings_with_key):
        parser = _build_parser(mock_settings_with_key)
        payload = {"content": [{"text": '{"source":"tense","target":"peaceful","interpretation":"test"}'}]}
        mock_resp = _make_httpx_response(payload)
        with _patch_httpx(mock_resp):
            result = await parser.parse("I feel tense and want to relax")
        assert result["method"] == "claude"
        assert result["source"] == "tense"
        assert result["target"] == "peaceful"

    async def test_claude_exception_falls_back_to_keywords(self, mock_settings_with_key):
        parser = _build_parser(mock_settings_with_key)
        mock_resp = _make_httpx_response({}, status_code=500)
        with _patch_httpx(mock_resp):
            result = await parser.parse("I feel stressed")
        assert result["method"] == "fallback"

    async def test_result_always_has_required_keys(self, mock_settings_no_key):
        parser = _build_parser(mock_settings_no_key)
        result = await parser.parse("whatever")
        for key in ("source", "target", "interpretation", "method"):
            assert key in result

    async def test_result_emotions_are_valid(self, mock_settings_no_key):
        parser = _build_parser(mock_settings_no_key)
        result = await parser.parse("I feel sad and want to be happy")
        assert result["source"] in VALID_EMOTIONS
        assert result["target"] in VALID_EMOTIONS


# ─── _call_claude() ───────────────────────────────────────────────────────────

class TestCallClaude:
    def setup_method(self):
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = "sk-test"
        self.parser = _build_parser(mock_settings)

    async def test_clean_json_response(self):
        payload = {
            "content": [{
                "text": '{"source":"tense","target":"peaceful","interpretation":"Moving from tension to calm"}'
            }]
        }
        mock_resp = _make_httpx_response(payload)
        with _patch_httpx(mock_resp):
            result = await self.parser._call_claude("I'm stressed")
        assert result["source"] == "tense"
        assert result["target"] == "peaceful"
        assert "interpretation" in result

    async def test_markdown_fence_stripped(self):
        payload = {
            "content": [{
                "text": '```json\n{"source":"happy","target":"energetic","interpretation":"test"}\n```'
            }]
        }
        mock_resp = _make_httpx_response(payload)
        with _patch_httpx(mock_resp):
            result = await self.parser._call_claude("I feel great")
        assert result["source"] == "happy"
        assert result["target"] == "energetic"

    async def test_case_insensitive_emotion_labels(self):
        payload = {
            "content": [{
                "text": '{"source":"Tense","target":"Peaceful","interpretation":"test"}'
            }]
        }
        mock_resp = _make_httpx_response(payload)
        with _patch_httpx(mock_resp):
            result = await self.parser._call_claude("feeling tense")
        assert result["source"] == "tense"
        assert result["target"] == "peaceful"

    async def test_invalid_json_raises(self):
        payload = {"content": [{"text": "this is not json"}]}
        mock_resp = _make_httpx_response(payload)
        with _patch_httpx(mock_resp):
            with pytest.raises(json.JSONDecodeError):
                await self.parser._call_claude("test")

    async def test_missing_content_key_raises(self):
        payload = {}  # no "content" key
        mock_resp = _make_httpx_response(payload)
        with _patch_httpx(mock_resp):
            with pytest.raises(KeyError):
                await self.parser._call_claude("test")

    async def test_http_401_raises(self):
        mock_resp = _make_httpx_response({}, status_code=401)
        with _patch_httpx(mock_resp):
            with pytest.raises(httpx.HTTPStatusError):
                await self.parser._call_claude("test")

    async def test_http_500_raises(self):
        mock_resp = _make_httpx_response({}, status_code=500)
        with _patch_httpx(mock_resp):
            with pytest.raises(httpx.HTTPStatusError):
                await self.parser._call_claude("test")

    async def test_invalid_source_emotion_raises_value_error(self):
        payload = {
            "content": [{"text": '{"source":"notanemtion","target":"peaceful","interpretation":"x"}'}]
        }
        mock_resp = _make_httpx_response(payload)
        with _patch_httpx(mock_resp):
            with pytest.raises(ValueError, match="Invalid source emotion"):
                await self.parser._call_claude("test")

    async def test_invalid_target_emotion_raises_value_error(self):
        payload = {
            "content": [{"text": '{"source":"tense","target":"notanemtion","interpretation":"x"}'}]
        }
        mock_resp = _make_httpx_response(payload)
        with _patch_httpx(mock_resp):
            with pytest.raises(ValueError, match="Invalid target emotion"):
                await self.parser._call_claude("test")

    async def test_same_source_target_replaced(self):
        payload = {
            "content": [{"text": '{"source":"peaceful","target":"peaceful","interpretation":"x"}'}]
        }
        mock_resp = _make_httpx_response(payload)
        with _patch_httpx(mock_resp):
            result = await self.parser._call_claude("feeling peaceful")
        assert result["source"] != result["target"]

    async def test_interpretation_fallback_when_missing(self):
        payload = {
            "content": [{"text": '{"source":"tense","target":"peaceful"}'}]
        }
        mock_resp = _make_httpx_response(payload)
        with _patch_httpx(mock_resp):
            result = await self.parser._call_claude("feeling tense")
        # Should default to "From tense to peaceful"
        assert "interpretation" in result
        assert "tense" in result["interpretation"] or "peaceful" in result["interpretation"]


# ─── _adjacent_emotion() ──────────────────────────────────────────────────────

class TestAdjacentEmotion:
    def setup_method(self):
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = ""
        self.parser = _build_parser(mock_settings)

    def test_all_12_emotions_return_different_emotion(self):
        for emotion in VALID_EMOTIONS:
            adj = self.parser._adjacent_emotion(emotion)
            assert adj != emotion, f"_adjacent_emotion({emotion!r}) returned self"

    def test_all_12_emotions_return_valid_emotion(self):
        for emotion in VALID_EMOTIONS:
            adj = self.parser._adjacent_emotion(emotion)
            assert adj in VALID_EMOTIONS, f"_adjacent_emotion({emotion!r}) = {adj!r} not valid"

    def test_unknown_emotion_returns_neutral(self):
        adj = self.parser._adjacent_emotion("unknownthing")
        assert adj == "neutral"

    def test_tense_maps_to_peaceful(self):
        assert self.parser._adjacent_emotion("tense") == "peaceful"

    def test_sad_maps_to_neutral(self):
        assert self.parser._adjacent_emotion("sad") == "neutral"

    def test_angry_maps_to_neutral(self):
        assert self.parser._adjacent_emotion("angry") == "neutral"

    def test_neutral_maps_to_happy(self):
        assert self.parser._adjacent_emotion("neutral") == "happy"


# ─── _fallback_from_keywords() ────────────────────────────────────────────────

class TestFallbackFromKeywords:
    def setup_method(self):
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = ""
        self.parser = _build_parser(mock_settings)

    def test_stress_keyword_maps_to_tense(self):
        result = self.parser._fallback_from_keywords("I feel stressed")
        assert result["source"] == "tense"
        assert result["method"] == "fallback"

    def test_sad_keyword_maps_to_sad(self):
        result = self.parser._fallback_from_keywords("I feel really sad today")
        assert result["source"] == "sad"

    def test_negative_single_emotion_targets_peaceful(self):
        for negative_kw in ["stressed", "sad today", "so angry", "feeling lonely"]:
            result = self.parser._fallback_from_keywords(negative_kw)
            assert result["target"] == "peaceful", (
                f"Expected target=peaceful for {negative_kw!r}, got {result['target']!r}"
            )

    def test_positive_single_emotion_targets_energetic(self):
        result = self.parser._fallback_from_keywords("I feel so happy")
        assert result["source"] == "happy"
        assert result["target"] == "energetic"

    def test_two_keywords_detected(self):
        # "stressed" → tense (first in map), "calm" → peaceful (later in map)
        result = self.parser._fallback_from_keywords("I feel stressed but want to stay calm")
        assert result["source"] == "tense"
        assert result["target"] == "peaceful"
        assert result["method"] == "fallback"

    def test_no_keyword_defaults_to_neutral_peaceful(self):
        result = self.parser._fallback_from_keywords("something something xyz")
        assert result["source"] == "neutral"
        assert result["target"] == "peaceful"

    def test_case_insensitive(self):
        result = self.parser._fallback_from_keywords("STRESSED AND ANXIOUS")
        assert result["source"] == "tense"

    def test_substring_match(self):
        # "stressing" contains "stress" → tense
        result = self.parser._fallback_from_keywords("I keep stressing over deadlines")
        assert result["source"] == "tense"

    def test_workout_maps_to_energetic(self):
        result = self.parser._fallback_from_keywords("heading to the gym for a workout")
        assert result["source"] == "energetic"

    def test_deep_work_maps_to_focused(self):
        result = self.parser._fallback_from_keywords("need to focus on deep work")
        assert result["source"] == "focused"

    def test_heartbreak_maps_to_sad(self):
        result = self.parser._fallback_from_keywords("going through heartbreak")
        assert result["source"] == "sad"

    def test_party_maps_to_euphoric(self):
        result = self.parser._fallback_from_keywords("party time let's celebrate")
        assert result["source"] == "euphoric"

    def test_result_emotions_always_differ(self):
        inputs = [
            "stressed", "sad", "happy", "focused", "whatever",
            "stressed and want to celebrate", "lonely and want to relax",
        ]
        for text in inputs:
            result = self.parser._fallback_from_keywords(text)
            assert result["source"] != result["target"], (
                f"source == target for input: {text!r}"
            )

    def test_returns_all_required_keys(self):
        result = self.parser._fallback_from_keywords("feeling okay")
        for key in ("source", "target", "interpretation", "method"):
            assert key in result


# ─── _fallback() ──────────────────────────────────────────────────────────────

class TestFallbackMethod:
    def setup_method(self):
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = ""
        self.parser = _build_parser(mock_settings)

    def test_returns_correct_structure(self):
        result = self.parser._fallback("tense", "peaceful", "some description")
        assert result == {
            "source": "tense",
            "target": "peaceful",
            "interpretation": "some description",
            "method": "fallback",
        }

    def test_method_always_fallback(self):
        result = self.parser._fallback("a", "b", "c")
        assert result["method"] == "fallback"
