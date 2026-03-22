"""
Language Detector — Flowstate
-------------------------------
Infers the primary language of a track from its title and artist name using
Unicode script ranges.  This is inherently language-agnostic at the *audio
feature level* — the librosa pipeline runs identically on all languages.
This module only adds metadata so users can filter arcs by language.

Supported language codes:
    en  — English (default / Latin script)
    hi  — Hindi (Devanagari)
    te  — Telugu
    ta  — Tamil
    kn  — Kannada
    ml  — Malayalam
    bn  — Bengali / Assamese
    ko  — Korean (Hangul)
    ja  — Japanese (Hiragana / Katakana)
    zh  — Chinese (CJK Unified Ideographs)
    ar  — Arabic / Persian
    other — any other detected non-Latin script

Detection strategy:
    1. Scan title + artist characters for Unicode block membership.
    2. Return the language code for the first recognised non-Latin script
       block found (title is scanned before artist).
    3. If no recognised script is found, return 'en'.

This heuristic is fast (O(n) character scan, no external dependencies) and
works well for South Asian and East Asian music where the script is the most
reliable discriminator.
"""

from __future__ import annotations

# ── Unicode ranges (inclusive, as (lo, hi) tuples) ──────────────────────────

_SCRIPT_RANGES: list[tuple[int, int, str]] = [
    # South Asian — check most specific first (overlapping Devanagari region)
    (0x0C00, 0x0C7F, "te"),   # Telugu
    (0x0B80, 0x0BFF, "ta"),   # Tamil
    (0x0C80, 0x0CFF, "kn"),   # Kannada
    (0x0D00, 0x0D7F, "ml"),   # Malayalam
    (0x0980, 0x09FF, "bn"),   # Bengali
    (0x0900, 0x097F, "hi"),   # Devanagari (Hindi, Marathi, Sanskrit)
    # East Asian
    (0xAC00, 0xD7AF, "ko"),   # Hangul syllables (Korean)
    (0x3040, 0x309F, "ja"),   # Hiragana (Japanese)
    (0x30A0, 0x30FF, "ja"),   # Katakana (Japanese)
    (0x4E00, 0x9FFF, "zh"),   # CJK Unified Ideographs (Chinese / Japanese Kanji)
    # Semitic
    (0x0600, 0x06FF, "ar"),   # Arabic / Persian / Urdu
    (0x0590, 0x05FF, "he"),   # Hebrew
]


def detect(title: str, artist: str = "") -> str:
    """
    Detect the primary language code for a track given its title and artist.

    Scans the combined text (title first, then artist) for the first
    character that falls within a known non-Latin Unicode block.

    Returns a two-letter BCP-47-style language code, defaulting to 'en'.
    """
    text = (title or "") + " " + (artist or "")
    for ch in text:
        cp = ord(ch)
        for lo, hi, lang in _SCRIPT_RANGES:
            if lo <= cp <= hi:
                return lang
    return "en"


def detect_batch(tracks: list[dict]) -> list[str]:
    """
    Detect language for a list of track dicts with 'title' and 'artist' keys.
    Returns a list of language codes in the same order.
    """
    return [detect(t.get("title", ""), t.get("artist", "")) for t in tracks]


# ── Language metadata ─────────────────────────────────────────────────────────

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "te": "Telugu",
    "ta": "Tamil",
    "kn": "Kannada",
    "ml": "Malayalam",
    "bn": "Bengali",
    "ko": "Korean",
    "ja": "Japanese",
    "zh": "Chinese",
    "ar": "Arabic",
    "he": "Hebrew",
    "other": "Other",
}

LANGUAGE_FLAGS: dict[str, str] = {
    "en": "🇬🇧",
    "hi": "🇮🇳",
    "te": "🇮🇳",
    "ta": "🇮🇳",
    "kn": "🇮🇳",
    "ml": "🇮🇳",
    "bn": "🇮🇳",
    "ko": "🇰🇷",
    "ja": "🇯🇵",
    "zh": "🇨🇳",
    "ar": "🇸🇦",
    "he": "🇮🇱",
    "other": "🌐",
}
