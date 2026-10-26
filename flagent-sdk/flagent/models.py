"""
models.py — Data classes for the Flagent SDK
"""

from dataclasses import dataclass, field
from typing import Any
import time


@dataclass
class ToolCall:
    """A single recorded tool invocation."""
    name: str
    args: dict = field(default_factory=dict)
    result: Any = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ScoreResult:
    """The result of scoring a session trace against a baseline."""
    session_id: str = ""
    agent_id: str = ""
    score: float = 0.0
    classification: str = "unknown"
    components: dict = field(default_factory=dict)
    intent_cluster: str | None = None
    baseline_used: str | None = None
    raw_response: dict = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: dict) -> "ScoreResult":
        """Construct from the /score-session API response JSON."""
        return cls(
            session_id=data.get("session_id", ""),
            agent_id=data.get("agent_id", ""),
            score=data.get("score", 0.0),
            classification=data.get("classification", "unknown"),
            components=data.get("components", {}),
            intent_cluster=data.get("intent_cluster"),
            baseline_used=data.get("baseline_used"),
            raw_response=data,
        )

    @classmethod
    def fail_open(cls) -> "ScoreResult":
        """Return a safe default when the API is unreachable (fail-open)."""
        return cls(
            classification="unknown",
            raw_response={"error": "API unreachable, fail-open applied"},
        )
