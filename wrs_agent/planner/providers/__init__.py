"""Model request/reply contract; vendor adapters live beside it."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ModelRequest:
    goal: str
    context: dict


@dataclass(frozen=True)
class ModelTiming:
    """Monotonic spans, in seconds. Observation only: never a timeout or authority source."""

    total: float
    wait: float  # Request sent -> first byte: the provider's own queue and generation.
    receive: float  # First byte -> body complete.
    parse: float  # Local decode and protocol checks.


@dataclass(frozen=True)
class ModelReply:
    text: str
    finish: str
    usage: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    timing: ModelTiming | None = None


class ModelClient(Protocol):
    async def complete(self, request: ModelRequest) -> ModelReply: ...
    async def aclose(self) -> None: ...
