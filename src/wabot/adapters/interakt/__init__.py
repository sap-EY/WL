"""Interakt adapter package.

Splits into:

* `normalizer.py` — pure, deterministic translation from Interakt's
  webhook envelope to the canonical inbound event consumed by the
  orchestrator. Has zero side effects; no DB, no HTTP.
* `client.py` — async HTTP client for the outbound message API.
"""

from wabot.adapters.interakt.client import (
    InteraktClient,
    InteraktError,
    InteraktPermanentError,
    InteraktSendResult,
    InteraktTransientError,
    build_request_body,
)
from wabot.adapters.interakt.normalizer import (
    NormalizationError,
    UnsupportedEventTypeError,
    normalize,
)

__all__ = [
    "InteraktClient",
    "InteraktError",
    "InteraktPermanentError",
    "InteraktSendResult",
    "InteraktTransientError",
    "NormalizationError",
    "UnsupportedEventTypeError",
    "build_request_body",
    "normalize",
]
