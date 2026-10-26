"""
session.py — Trace-capture session for the Flagent SDK

A Session collects tool calls during an agent's execution, builds the trace,
and sends it to the governance API for scoring.  Sessions are created via
`Flagent.session()` or implicitly by `@fg.governed()`.
"""

import logging
import time
import threading
from collections import Counter
from typing import Any, Callable

import requests

from flagent.models import ToolCall, ScoreResult
from flagent.exceptions import FlagentBlocked

logger = logging.getLogger("flagent")


class Session:
    """
    Captures tool calls and scores the resulting trace.

    Usage (context manager):
        with fg.session() as s:
            s.record_tool_call("lookup_order", args={"id": "123"})
            s.record_tool_call("issue_refund", args={"id": "123", "amount": 50})

    Usage (decorator — automatic via @fg.governed):
        The decorator creates a Session, sets it as the active context,
        and finalizes it when the decorated function returns.
    """

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        agent_id: str,
        mode: str = "shadow",
        on_alert: Callable[[ScoreResult], None] | None = None,
        on_warning: Callable[[ScoreResult], None] | None = None,
        raise_on_alert: bool = False,
        fail_closed: bool = False,
        _shadow_sender=None,
    ):
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._agent_id = agent_id
        self._mode = mode
        self._on_alert = on_alert
        self._on_warning = on_warning
        self._raise_on_alert = raise_on_alert
        self._fail_closed = fail_closed
        self._shadow_sender = _shadow_sender

        self._tool_calls: list[ToolCall] = []
        self._response_length_words: int = 0
        self._result: ScoreResult | None = None
        self._started_at: float = time.time()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_tool_call(
        self,
        name: str,
        args: dict | None = None,
        result: Any = None,
    ) -> None:
        """Record a tool invocation.  Call this for each tool your agent uses."""
        self._tool_calls.append(
            ToolCall(
                name=name,
                args=args or {},
                result=result,
                timestamp=time.time(),
            )
        )

    def set_response_length(self, word_count: int) -> None:
        """Optionally set the agent's response length in words."""
        self._response_length_words = word_count

    @property
    def result(self) -> ScoreResult | None:
        """The scoring result, available after the session ends."""
        return self._result

    @property
    def tool_calls(self) -> list[ToolCall]:
        """List of recorded tool calls."""
        return list(self._tool_calls)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Don't send trace if the function raised an exception
        if exc_type is not None:
            return False

        trace = self._build_trace()

        if self._mode == "shadow":
            self._send_shadow(trace)
        elif self._mode == "enforce":
            self._send_enforce(trace)

        return False  # don't suppress exceptions

    # ------------------------------------------------------------------
    # Trace building
    # ------------------------------------------------------------------

    def _build_trace(self) -> dict:
        """Build the trace dict from recorded tool calls."""
        tools_called = [tc.name for tc in self._tool_calls]
        tool_counts = dict(Counter(tools_called))

        return {
            "tools_called": tools_called,
            "tool_counts": tool_counts,
            "response_length_words": self._response_length_words,
        }

    # ------------------------------------------------------------------
    # Shadow mode (async, non-blocking, failures swallowed)
    # ------------------------------------------------------------------

    def _send_shadow(self, trace: dict) -> None:
        """Send trace asynchronously.  Never blocks, never raises."""
        if self._shadow_sender:
            self._shadow_sender.enqueue(self._do_score, trace)
        else:
            # Fallback: fire-and-forget thread
            t = threading.Thread(
                target=self._shadow_worker, args=(trace,), daemon=True
            )
            t.start()

    def _shadow_worker(self, trace: dict) -> None:
        """Worker for shadow mode — swallows all errors."""
        try:
            self._result = self._do_score(trace)
        except Exception as e:
            logger.debug("flagent shadow send failed: %s", e)

    # ------------------------------------------------------------------
    # Enforce mode (sync, callbacks, optional blocking)
    # ------------------------------------------------------------------

    def _send_enforce(self, trace: dict) -> None:
        """Send trace synchronously.  Invokes callbacks and may raise."""
        try:
            self._result = self._do_score(trace)
        except Exception as e:
            if self._fail_closed:
                raise FlagentBlocked(
                    f"Governance API unreachable and fail_closed=True: {e}"
                )
            # Fail-open: log and continue
            logger.warning("flagent enforce send failed (fail-open): %s", e)
            self._result = ScoreResult.fail_open()
            return

        if self._result.classification == "alert":
            if self._on_alert:
                self._on_alert(self._result)
            if self._raise_on_alert:
                raise FlagentBlocked(
                    f"Session blocked: anomaly score {self._result.score} "
                    f"(classification: alert)",
                    score_result=self._result,
                )
        elif self._result.classification == "warning":
            if self._on_warning:
                self._on_warning(self._result)

    # ------------------------------------------------------------------
    # HTTP scoring call
    # ------------------------------------------------------------------

    def _do_score(self, trace: dict) -> ScoreResult:
        """POST the trace to /score-session and return a ScoreResult."""

        resp = requests.post(
            f"{self._api_url}/score-session",
            json={
                "trace": trace,
                "agent_id": self._agent_id,
            },
            headers={
                "Content-Type": "application/json",
                "x-flagent-key": self._api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return ScoreResult.from_api_response(resp.json())
