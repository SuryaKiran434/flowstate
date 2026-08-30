"""
Helpers for putting untrusted values into log records safely.

A log line is a single record only by convention: it is really just text in a
stream, and a value carrying a newline splits it into two.  When that value came
from a request -- a user id lifted out of a JWT, a search term, a filename --
the caller gets to write whatever they like into the log, which means forging
entries that never happened, hiding a real one by burying it, or breaking the
parser that ships the logs onward.  Control characters cause the same trouble in
a terminal, and an unbounded value can flood the log outright.

`scrub_for_log` is the single choke point for that: it strips the characters
that break record framing and caps the length.
"""

from typing import Any

__all__ = ["scrub_for_log"]

# Everything below 0x20 plus DEL. Covers CR, LF, NUL, ESC and the rest of the
# C0 range -- the characters that end a record or steer a terminal.
_CONTROL_CHARS = {c: None for c in list(range(0x00, 0x20)) + [0x7F]}

_MAX_LENGTH = 256
_TRUNCATION_MARKER = "...[truncated]"


def scrub_for_log(value: Any, max_length: int = _MAX_LENGTH) -> str:
    """
    Render `value` as a single-line, length-capped string fit for a log record.

    Control characters (CR, LF, NUL, ESC, ...) are removed rather than escaped,
    so nothing downstream can turn them back into record separators.
    """
    text = str(value).translate(_CONTROL_CHARS)
    if len(text) > max_length:
        text = text[: max_length - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER
    return text
