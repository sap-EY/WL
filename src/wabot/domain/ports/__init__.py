"""Domain ports — protocols for external collaborators.

Ports define the **interfaces** the domain layer needs (GenAI, future
master-data lookups, etc.) without binding to a concrete adapter. The
adapters package implements them; the orchestrator wires the chosen
implementation at startup.
"""

from wabot.domain.ports.genai import (
    GenAIPort,
    GenAIRequest,
    GenAIResponse,
    GenAIServiceError,
    StubGenAIPort,
)

__all__ = [
    "GenAIPort",
    "GenAIRequest",
    "GenAIResponse",
    "GenAIServiceError",
    "StubGenAIPort",
]
