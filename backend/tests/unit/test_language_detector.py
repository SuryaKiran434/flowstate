"""
Unit tests — LanguageDetector  (Phase 6.2)
==========================================
Covers:
  - detect(): English fallback, all supported scripts
  - Artist name detection (when title is Latin)
  - Mixed text detection (script wins over Latin)
  - detect_batch(): list detection, preserves order
  - LANGUAGE_NAMES / LANGUAGE_FLAGS completeness
  - arc_planner.plan_from_db language_filter param
  - GET /tracks/language-stats endpoint
"""

import pytest
from unittest.mock import MagicMock, patch

from app.services.language_detector import (
    detect,
    detect_batch,
    LANGUAGE_NAMES,
    LANGUAGE_FLAGS,
)


# ─── detect() — script detection ─────────────────────────────────────────────

def test_english_ascii_returns_en():
    assert detect("Shape of You", "Ed Sheeran") == "en"


def test_empty_strings_return_en():
    assert detect("", "") == "en"


def test_empty_title_latin_artist_returns_en():
    assert detect("", "Adele") == "en"


def test_hindi_devanagari_in_title():
    # "Tum Hi Ho" written in Devanagari
    assert detect("तुम ही हो", "Arijit Singh") == "hi"


def test_hindi_devanagari_in_artist():
    assert detect("Song Name", "आशा भोसले") == "hi"


def test_telugu_script_detected():
    # Telugu characters U+0C00-U+0C7F
    assert detect("పాట పేరు", "గాయకుడు") == "te"


def test_tamil_script_detected():
    # Tamil characters U+0B80-U+0BFF
    assert detect("பாடல் தலைப்பு", "ஏ.ஆர். ரகுமான்") == "ta"


def test_kannada_script_detected():
    # Kannada characters U+0C80-U+0CFF
    assert detect("ಹಾಡಿನ ಹೆಸರು", "ಕಲಾವಿದ") == "kn"


def test_malayalam_script_detected():
    # Malayalam characters U+0D00-U+0D7F
    assert detect("ഗാനം", "ഗായകൻ") == "ml"


def test_bengali_script_detected():
    # Bengali characters U+0980-U+09FF
    assert detect("গানের নাম", "শিল্পী") == "bn"


def test_korean_hangul_detected():
    assert detect("봄날", "방탄소년단") == "ko"


def test_japanese_hiragana_detected():
    assert detect("はるの うた", "artist") == "ja"


def test_japanese_katakana_detected():
    assert detect("ソング タイトル", "artist") == "ja"


def test_chinese_cjk_detected():
    assert detect("歌曲名字", "艺术家") == "zh"


def test_arabic_script_detected():
    assert detect("أغنية", "مطرب") == "ar"


def test_mixed_latin_and_devanagari_returns_script():
    # Title starts with Latin, artist has Devanagari — artist scanned after title
    assert detect("Jai Ho", "ए.आर. रहमान") == "hi"


def test_mixed_latin_title_with_telugu_artist():
    assert detect("Naatu Naatu", "రాహుల్ సిప్లిగంజ్") == "te"


def test_pure_punctuation_returns_en():
    assert detect("---", "???") == "en"


def test_numeric_title_returns_en():
    assert detect("1234", "5678") == "en"


# ─── detect_batch() ───────────────────────────────────────────────────────────

def test_detect_batch_preserves_order():
    tracks = [
        {"title": "Shape of You", "artist": "Ed Sheeran"},
        {"title": "봄날",           "artist": "BTS"},
        {"title": "तुम ही हो",     "artist": "Arijit"},
    ]
    result = detect_batch(tracks)
    assert result == ["en", "ko", "hi"]


def test_detect_batch_empty_list():
    assert detect_batch([]) == []


def test_detect_batch_missing_keys():
    tracks = [{"title": "Hello"}, {"artist": "방탄소년단"}]
    result = detect_batch(tracks)
    assert result[0] == "en"
    assert result[1] == "ko"


def test_detect_batch_all_english():
    tracks = [{"title": f"Track {i}", "artist": "Artist"} for i in range(5)]
    assert all(lang == "en" for lang in detect_batch(tracks))


# ─── LANGUAGE_NAMES and LANGUAGE_FLAGS ───────────────────────────────────────

def test_language_names_covers_all_detected_langs():
    detected = {"en", "hi", "te", "ta", "kn", "ml", "bn", "ko", "ja", "zh", "ar"}
    for lang in detected:
        assert lang in LANGUAGE_NAMES, f"Missing name for {lang}"


def test_language_flags_covers_all_detected_langs():
    detected = {"en", "hi", "te", "ta", "kn", "ml", "bn", "ko", "ja", "zh", "ar"}
    for lang in detected:
        assert lang in LANGUAGE_FLAGS, f"Missing flag for {lang}"


def test_language_names_are_strings():
    for code, name in LANGUAGE_NAMES.items():
        assert isinstance(name, str) and len(name) > 0


# ─── ArcPlanner language_filter integration ──────────────────────────────────

def test_arc_planner_language_filter_applies():
    from app.services.arc_planner import ArcPlanner, TrackCandidate

    def _t(title, lang, emotion="happy"):
        t = TrackCandidate(
            track_id="x", spotify_id="s", title=title, artist="",
            duration_ms=200_000, emotion_label=emotion,
            emotion_confidence=0.9, energy=0.6, valence=0.7, tempo=120.0,
        )
        t.language = lang
        return t

    english_pool = [_t("Track EN", "en") for _ in range(8)]
    hindi_pool   = [_t("Track HI", "hi") for _ in range(8)]
    all_pool     = english_pool + hindi_pool

    planner = ArcPlanner()
    arc = planner.plan("happy", "peaceful", 20, all_pool)
    assert arc["total_tracks"] > 0  # no filter — uses all

    # Now simulate filter at plan_from_db level (mock DB)
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = []

    # plan_from_db with language_filter and empty pool after filter → library_not_ready
    with patch.object(planner, 'load_track_pool_from_db', return_value=hindi_pool):
        arc_hi = planner.plan_from_db("happy", "peaceful", 20, db, "uid",
                                      language_filter=["en"])
        # hindi_pool filtered to en → empty → library_not_ready
        assert arc_hi["error"] == "library_not_ready"

    with patch.object(planner, 'load_track_pool_from_db', return_value=hindi_pool):
        arc_hi2 = planner.plan_from_db("happy", "peaceful", 20, db, "uid",
                                       language_filter=["hi"])
        # hindi_pool with hi filter → passes through
        assert arc_hi2.get("total_tracks", 0) > 0


def test_arc_planner_no_language_filter_uses_all():
    from app.services.arc_planner import ArcPlanner, TrackCandidate

    pool = [
        TrackCandidate(
            track_id=str(i), spotify_id=str(i), title=f"T{i}", artist="",
            duration_ms=200_000, emotion_label="happy",
            emotion_confidence=0.9, energy=0.6, valence=0.7, tempo=120.0,
        )
        for i in range(10)
    ]
    for t in pool[:5]:  t.language = "en"
    for t in pool[5:]:  t.language = "hi"

    db = MagicMock()
    planner = ArcPlanner()
    with patch.object(planner, 'load_track_pool_from_db', return_value=pool):
        arc = planner.plan_from_db("happy", "peaceful", 20, db, "uid",
                                   language_filter=None)
    assert arc.get("total_tracks", 0) > 0


# ─── GET /tracks/language-stats endpoint ─────────────────────────────────────

from fastapi import HTTPException
from app.api.v1.endpoints.tracks import get_language_stats


def test_language_stats_empty_library():
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = []
    result = get_language_stats(user_id="uid", db=db)
    assert result["total_classified"] == 0
    assert result["distribution"] == []
    assert result["multilingual"] is False


def test_language_stats_single_language():
    db = MagicMock()
    row = MagicMock()
    row.name = "Shape of You"
    row.artist_names = "Ed Sheeran"
    db.execute.return_value.fetchall.return_value = [row] * 5
    result = get_language_stats(user_id="uid", db=db)
    assert result["total_classified"] == 5
    assert result["distribution"][0]["language"] == "en"
    assert result["distribution"][0]["count"] == 5
    assert result["multilingual"] is False


def test_language_stats_multilingual_library():
    db = MagicMock()
    en_row = MagicMock(); en_row.name = "Hello"; en_row.artist_names = "Adele"
    hi_row = MagicMock(); hi_row.name = "तुम ही हो"; hi_row.artist_names = "Arijit"
    ko_row = MagicMock(); ko_row.name = "봄날"; ko_row.artist_names = "BTS"
    db.execute.return_value.fetchall.return_value = [en_row, en_row, hi_row, ko_row]
    result = get_language_stats(user_id="uid", db=db)
    assert result["total_classified"] == 4
    assert result["multilingual"] is True
    assert result["language_count"] == 3
    langs = [d["language"] for d in result["distribution"]]
    assert "en" in langs and "hi" in langs and "ko" in langs


def test_language_stats_percentage_sums_to_100():
    db = MagicMock()
    rows = []
    for name, artist in [("Hello", "Adele"), ("봄날", "BTS"), ("तुम ही हो", "Arijit"),
                          ("Shape of You", "Ed")]:
        r = MagicMock(); r.name = name; r.artist_names = artist
        rows.append(r)
    db.execute.return_value.fetchall.return_value = rows
    result = get_language_stats(user_id="uid", db=db)
    total_pct = sum(d["percentage"] for d in result["distribution"])
    assert abs(total_pct - 100.0) < 1.0  # rounding tolerance


def test_language_stats_distribution_sorted_by_count():
    db = MagicMock()
    rows = []
    # 3 Korean, 1 English
    for _ in range(3):
        r = MagicMock(); r.name = "봄날"; r.artist_names = "BTS"; rows.append(r)
    r = MagicMock(); r.name = "Hello"; r.artist_names = "Adele"; rows.append(r)
    db.execute.return_value.fetchall.return_value = rows
    result = get_language_stats(user_id="uid", db=db)
    assert result["distribution"][0]["language"] == "ko"   # most common first
    assert result["distribution"][0]["count"] == 3
