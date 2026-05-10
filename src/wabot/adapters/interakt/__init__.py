"""Interakt adapter package.

Splits into:

* `normalizer.py` — pure, deterministic translation from Interakt's
  webhook envelope to the canonical inbound event consumed by the
  orchestrator. Has zero side effects; no DB, no HTTP.
* (Phase 6) `client.py` — outbound HTTP client.
"""

from wabot.adapters.interakt.normalizer import (
    NormalizationError,
    UnsupportedEventTypeError,
    normalize,
)

__all__ = [
    "NormalizationError",
    "UnsupportedEventTypeError",
    "normalize",
]
