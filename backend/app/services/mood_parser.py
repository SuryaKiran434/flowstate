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

ADJUST_SYSTEM_PROMPT = f"""You are a mid-session music arc adjuster for Flowstate.

The user is currently listening and wants to change where their session is heading.
You will be told their current emotional position and their original destination,
then given their natural language command.

Your job: parse the command into a new target emotion from this list:
{json.dumps({k: v for k, v in EMOTION_DESCRIPTIONS.items()}, indent=2)}

Examples of commands and expected new_target:
- "slow this down" → peaceful, melancholic, or nostalgic (calmer)
- "more energy" → energetic or happy (higher energy)
- "I'm feeling sadder now" → sad or melancholic
- "skip to the peaceful part" → peaceful
- "make it more intense" → tense or energetic
- "something romantic" → romantic
- "I want to cry a little" → sad
- "more nostalgic vibes" → nostalgic
- "I feel better now" → happy or euphoric

Rules:
- new_target must be a valid emotion from the list above
- new_target SHOULD differ from current_emotion (but can be the same if that's genuinely what's requested)
- Keep the emotional journey coherent — don't jump to something jarring without reason
- "action" must always be "change_target"

Respond with ONLY valid JSON, no other text:
{{
  "new_target": "<emotion_label>",
  "interpretation": "<one sentence in plain English describing the adjustment, e.g. 'Shifting the arc toward quiet nostalgia'>",
  "action": "change_target"
}}"""

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

    async def parse_adjustment(
        self,
        current_emotion: str,
        current_target: str,
        command: str,
    ) -> dict:
        """
        Parse a mid-session natural language command into a new target emotion.

        Returns:
            {"new_target": str, "interpretation": str, "action": "change_target", "method": str}
        """
        command = command.strip()
        if not command:
            return {
                "new_target":     current_target,
                "interpretation": "Continuing toward the original destination",
                "action":         "change_target",
                "method":         "passthrough",
            }

        context = (
            f"Current emotional position: {current_emotion} "
            f"({EMOTION_DESCRIPTIONS.get(current_emotion, '')})\n"
            f"Original destination: {current_target} "
            f"({EMOTION_DESCRIPTIONS.get(current_target, '')})\n"
            f"User command: {command}"
        )

        if self.settings.anthropic_api_key:
            try:
                result = await self._call_claude_adjust(context)
                result["method"] = "claude"
                return result
            except Exception as e:
                print(f"Claude adjustment parsing failed: {e} — using keyword fallback")

        return self._fallback_adjustment(command, current_target)

    async def _call_claude_adjust(self, context: str) -> dict:
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
                    "max_tokens": 150,
                    "system":     ADJUST_SYSTEM_PROMPT,
                    "messages":   [{"role": "user", "content": context}],
                }
            )
            response.raise_for_status()
            data = response.json()

            raw = data["content"][0]["text"].strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            parsed      = json.loads(raw)
            new_target  = parsed.get("new_target", "").lower()

            if new_target not in VALID_EMOTIONS:
                raise ValueError(f"Invalid new_target from Claude: {new_target}")

            return {
                "new_target":     new_target,
                "interpretation": parsed.get("interpretation", f"Adjusting arc toward {new_target}"),
                "action":         parsed.get("action", "change_target"),
            }

    def _fallback_adjustment(self, command: str, current_target: str) -> dict:
        """Keyword-based fallback for when Claude is unavailable."""
        text = command.lower()

        # Energy shift signals
        calm_words   = ["slow", "calm", "quiet", "relax", "chill", "peaceful", "softer", "gentle", "wind down"]
        energy_words = ["energy", "faster", "pump", "hype", "intense", "louder", "powerful", "workout", "speed"]
        sad_words    = ["sad", "cry", "depress", "heavy", "dark", "melanchol", "lonely", "heartbreak"]
        happy_words  = ["happy", "upbeat", "cheerful", "better", "positive", "joy", "bright"]
        nostalgic    = ["nostalgic", "memories", "throwback", "remember", "past"]
        romantic     = ["romantic", "love", "tender", "intimate", "warm"]
        focused      = ["focus", "study", "work", "concentrate", "productive"]

        if any(w in text for w in sad_words):
            new_target, interp = "sad", "Shifting toward a heavier, more emotional space"
        elif any(w in text for w in calm_words):
            new_target, interp = "peaceful", "Bringing the arc to a calmer, more serene place"
        elif any(w in text for w in energy_words):
            new_target, interp = "energetic", "Pushing toward higher energy"
        elif any(w in text for w in happy_words):
            new_target, interp = "happy", "Brightening the arc toward a more uplifting destination"
        elif any(w in text for w in nostalgic):
            new_target, interp = "nostalgic", "Steering toward bittersweet nostalgia"
        elif any(w in text for w in romantic):
            new_target, interp = "romantic", "Shifting toward warm, intimate sounds"
        elif any(w in text for w in focused):
            new_target, interp = "focused", "Moving toward a steady, purposeful space"
        else:
            new_target, interp = current_target, "Continuing toward the original destination"

        return {
            "new_target":     new_target,
            "interpretation": interp,
            "action":         "change_target",
            "method":         "fallback",
        }

    def _fallback(self, source: str, target: str, interpretation: str) -> dict:
        return {
            "source":         source,
            "target":         target,
            "interpretation": interpretation,
            "method":         "fallback",
        }
