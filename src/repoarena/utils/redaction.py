from __future__ import annotations

import re
from collections.abc import Iterable

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|authorization|password)(\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{16,})\b"),
    re.compile(r"\b(gh[oprsu]_[A-Za-z0-9]{20,})\b"),
)


def redact(text: str, extra_values: Iterable[str] = ()) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(
            lambda match: match.group(0).replace(match.group(match.lastindex or 0), "[REDACTED]"),
            redacted,
        )
    for value in extra_values:
        if value and len(value) >= 8:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted
