"""
SignalOutput v1 protocol for Crucible plugins.

All skills output this schema to stdout as JSON.
Human-readable summaries go to stderr.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SignalOutput:
    """Standard signal output for all Crucible skills."""

    signal: str  # "bullish" | "bearish" | "neutral"
    confidence: int  # 0-100
    reasoning: str
    data: dict[str, Any] = field(default_factory=dict)
    analytics: dict[str, Any] = field(default_factory=dict)
    schema: str = "signal/v1"

    def emit(self) -> None:
        """Print JSON to stdout."""
        print(json.dumps(asdict(self), ensure_ascii=False))

    def summary(self, text: str) -> None:
        """Print human-readable summary to stderr."""
        print(text, file=sys.stderr)


@dataclass
class ErrorOutput:
    """Standard error output for all Crucible skills."""

    error: str
    details: str = ""
    schema: str = "error/v1"

    def emit(self) -> None:
        """Print error JSON to stdout and exit."""
        print(json.dumps(asdict(self), ensure_ascii=False))
        sys.exit(1)
