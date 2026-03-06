"""
Mood Parser — Flowstate
------------------------
Converts free-text mood descriptions into structured emotion pairs
using the Claude API. The source and target emotions are constrained
to the 12 labels understood by the ArcPlanner emotion graph.

Example:
    parser = MoodParser()
    result = await parser.parse("I'm stressed from work, want to wind down")
    # → {"source": "tense", "target": "peaceful", "interpretation": "..."}
"""

import json
import httpx
from app.core.config import get_settings

VALID_EMOTIONS = [
    "energetic", "happy", "euphoric", "peaceful", "focused",
    "romantic", "nostalgic", "neutral", "melancholic", "sad", "tense", "angry"
]

EMOTION_DESCRIPTIONS = {
    "energetic":   "high energy, driving, powerful — workout or pump-up music",
    "happy":       "upbeat, cheerful, light — feel-good vibes",
    "euphoric":    "peak joy, exhilarating, triumphant — festival or celebration",
    "peaceful":    "calm, serene, gentle — relaxation or winding down",
    "focused":     "steady, purposeful, minimal distraction — study or deep work",
    "romantic":    "warm, tender, intimate — love or longing",
    "nostalgic":   "wistful, bittersweet, reflective — memories and the past",
    "neutral":     "balanced, neither high nor low — background or transitional",
    "melancholic": "quietly sad, introspective, aching — not quite crying but close",
    "sad":         "heavy, sorrowful, low energy — grief or heartbreak",
    "tense":       "anxious, unsettled, high-strung — stress or agitation",
    "angry":       "frustrated, intense, raw — anger or aggression",
}

SYSTEM_PROMPT = f"""You are an emotion classifier for a music app called Flowstate.
Your job is to read a user's mood description and identify:
1. Their CURRENT emotional state (source)
2. The emotional state they WANT to reach (target)

You must map both to exactly one label each from this list:
{json.dumps({k: v for k, v in EMOTION_DESCRIPTIONS.items()}, indent=2)}

Rules:
- If the user only describes their current state with no target, infer a natural positive destination
- If the user only describes where they want to be, infer a neutral/realistic source
- Source and target must be DIFFERENT emotions
- Pick the labels that best match the musical/emotional intent, not just literal words
  (e.g. "stressed" → tense, "pumped up" → energetic, "heartbroken" → sad)

Respond with ONLY valid JSON in exactly this format, no other text:
{{
  "source": "<emotion_label>",
  "target": "<emotion_label>",
  "interpretation": "<one sentence in plain English describing the arc, e.g. 'Moving from anxious tension to calm serenity'>"
}}"""


class MoodParser:
    """
    Parses natural language mood descriptions into structured emotion pairs.
    Uses Claude claude-haiku-4-5 via the Anthropic API.
    Falls back to keyword-based parsing if the API call fails.
    """

    def __init__(self):
        self.settings = get_settings()
        self.api_url  = "https://api.anthropic.com/v1/messages"

    async def parse(self, mood_text: str) -> dict:
        mood_text = mood_text.strip()
        if not mood_text:
            return self._fallback("neutral", "peaceful", "No mood provided — defaulting to a calming arc")

        # Use Claude if API key is configured
        if self.settings.anthropic_api_key:
            try:
                result = await self._call_claude(mood_text)
                result["method"] = "claude"
                return result
            except Exception as e:
                print(f"Claude mood parsing failed: {e} — using keyword fallback")

        return self._fallback_from_keywords(mood_text)

    async def _call_claude(self, mood_text: str) -> dict:
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
                    "system":     SYSTEM_PROMPT,
                    "messages":   [{"role": "user", "content": mood_text}],
                }
            )
            response.raise_for_status()
            data = response.json()

            raw = data["content"][0]["text"].strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            parsed = json.loads(raw)

            source = parsed.get("source", "").lower()
            target = parsed.get("target", "").lower()

            if source not in VALID_EMOTIONS:
                raise ValueError(f"Invalid source emotion from Claude: {source}")
            if target not in VALID_EMOTIONS:
                raise ValueError(f"Invalid target emotion from Claude: {target}")
            if source == target:
                target = self._adjacent_emotion(source)

            return {
                "source":         source,
                "target":         target,
                "interpretation": parsed.get("interpretation", f"From {source} to {target}"),
            }

    def _adjacent_emotion(self, emotion: str) -> str:
        defaults = {
            "energetic": "peaceful", "happy": "peaceful",    "euphoric":    "peaceful",
            "peaceful":  "happy",    "focused": "peaceful",  "romantic":    "peaceful",
            "nostalgic": "peaceful", "neutral": "happy",     "melancholic": "neutral",
            "sad":       "neutral",  "tense":   "peaceful",  "angry":       "neutral",
        }
        return defaults.get(emotion, "neutral")

    def _fallback_from_keywords(self, text: str) -> dict:
        text_lower = text.lower()

        keyword_map = {
            "tense":       ["stress", "anxious", "anxiety", "worried", "nervous", "overwhelm", "tense", "pressure"],
            "sad":         ["sad", "depress", "heartbreak", "heartbroken", "grief", "crying", "cry", "devastat"],
            "angry":       ["angry", "anger", "frustrat", "furious", "rage", "annoyed", "irritat"],
            "melancholic": ["melanchol", "lonely", "alone", "missing", "empty", "numb"],
            "energetic":   ["energetic", "pumped", "hype", "workout", "gym", "run", "exercise", "motivated"],
            "happy":       ["happy", "joy", "excited", "great", "wonderful", "amazing", "cheerful"],
            "euphoric":    ["euphoric", "celebrat", "party", "ecstat", "thrilled", "elated"],
            "peaceful":    ["peaceful", "calm", "relax", "unwind", "chill", "serene", "quiet", "sleep"],
            "focused":     ["focus", "concentrate", "study", "work", "productive", "deep work"],
            "romantic":    ["romantic", "love", "date", "intimate", "tender", "longing"],
            "nostalgic":   ["nostalgic", "memories", "remember", "past", "childhood", "throwback"],
            "neutral":     ["neutral", "okay", "fine", "normal", "whatever", "meh"],
        }

        detected = []
        for emotion, keywords in keyword_map.items():
            if any(kw in text_lower for kw in keywords):
                detected.append(emotion)

        negative = {"tense", "sad", "angry", "melancholic"}

        if len(detected) >= 2:
            source = detected[0]
            target = detected[1] if detected[1] != detected[0] else self._adjacent_emotion(detected[0])
        elif len(detected) == 1:
            source = detected[0]
            target = "peaceful" if source in negative else "energetic"
        else:
            source, target = "neutral", "peaceful"

        return self._fallback(source, target, f"Moving from {source} to {target}")

    def _fallback(self, source: str, target: str, interpretation: str) -> dict:
        return {
            "source":         source,
            "target":         target,
            "interpretation": interpretation,
            "method":         "fallback",
        }
