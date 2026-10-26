"""
client.py — Main Flagent SDK client

The Flagent class is the primary entry point.  It provides:
  - @fg.governed()     decorator for automatic trace capture
  - fg.session()       context manager for manual trace capture
  - fg.wrap_tools()    auto-wraps tool functions to record calls
  - fg.register_agent()   wraps POST /agents/register
  - fg.record_baseline()  wraps POST /agents/{agent_id}/baseline
"""

import contextvars
import functools
import logging
import threading
import queue
from typing import Any, Callable

from flagent.session import Session
from flagent.models import ScoreResult

logger = logging.getLogger("flagent")

# Thread-safe context variable tracking the current active session.
# Used by wrap_tools() so wrapped functions know which session to record to.
_current_session: contextvars.ContextVar[Session | None] = contextvars.ContextVar(
    "_flagent_current_session", default=None
)


class _ShadowSender:
    """Background worker thread that sends traces without blocking the caller."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="flagent-shadow"
        )
        self._thread.start()

    def _worker(self):
        while True:
            try:
                fn, trace = self._queue.get()
                try:
                    fn(trace)
                except Exception as e:
                    logger.debug("flagent shadow send failed: %s", e)
                finally:
                    self._queue.task_done()
            except Exception:
                pass  # never crash the worker

    def enqueue(self, fn, trace):
        self._queue.put((fn, trace))


class Flagent:
    """
    Behavioral governance client for AI agents.

    Args:
        api_url:  Base URL of the Flagent governance API
                  (e.g. "https://xyz.execute-api.region.amazonaws.com/dev")
        api_key:  API key returned by /agents/register
        agent_id: The registered agent ID
        mode:     "shadow" (default, async non-blocking) or
                  "enforce" (sync, with callbacks)

    Example:
        fg = Flagent(
            api_url="https://...",
            api_key="fgnt_...",
            agent_id="my-bot",
        )

        @fg.governed()
        def handle(msg):
            tools["lookup_order"]("ORD-123")
            return "Order found"
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        agent_id: str,
        mode: str = "shadow",
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.agent_id = agent_id
        self.mode = mode
        self._shadow_sender = _ShadowSender() if mode == "shadow" else None

    # ------------------------------------------------------------------
    # Session factory
    # ------------------------------------------------------------------

    def session(
        self,
        *,
        mode: str | None = None,
        on_alert: Callable[[ScoreResult], None] | None = None,
        on_warning: Callable[[ScoreResult], None] | None = None,
        raise_on_alert: bool = False,
        fail_closed: bool = False,
    ) -> Session:
        """
        Create a new governance session (use as a context manager).

        Args:
            mode:           Override the client-level mode for this session.
            on_alert:       Callback invoked when classification == "alert".
            on_warning:     Callback invoked when classification == "warning".
            raise_on_alert: If True, raise FlagentBlocked on alert (enforce only).
            fail_closed:    If True, raise if the API is unreachable (enforce only).
        """
        return Session(
            api_url=self.api_url,
            api_key=self.api_key,
            agent_id=self.agent_id,
            mode=mode or self.mode,
            on_alert=on_alert,
            on_warning=on_warning,
            raise_on_alert=raise_on_alert,
            fail_closed=fail_closed,
            _shadow_sender=self._shadow_sender,
        )

    # ------------------------------------------------------------------
    # Decorator
    # ------------------------------------------------------------------

    def governed(
        self,
        *,
        mode: str | None = None,
        on_alert: Callable[[ScoreResult], None] | None = None,
        on_warning: Callable[[ScoreResult], None] | None = None,
        raise_on_alert: bool = False,
        fail_closed: bool = False,
    ):
        """
        Decorator that wraps an agent function with governance.

        Creates a Session before calling the function, sets it as the active
        context (so wrap_tools() auto-records to it), and finalizes it when
        the function returns.

        Example:
            @fg.governed(on_alert=lambda r: print(f"ALERT: {r.score}"))
            def handle_request(user_msg):
                result = tools["lookup_order"]("ORD-123")
                return f"Order status: {result}"
        """

        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                s = self.session(
                    mode=mode,
                    on_alert=on_alert,
                    on_warning=on_warning,
                    raise_on_alert=raise_on_alert,
                    fail_closed=fail_closed,
                )
                with s:
                    token = _current_session.set(s)
                    try:
                        result = fn(*args, **kwargs)
                    finally:
                        _current_session.reset(token)
                # Attach the score result to the wrapper for inspection
                wrapper.last_result = s.result
                return result

            wrapper.last_result = None
            return wrapper

        return decorator

    # ------------------------------------------------------------------
    # Tool wrapping
    # ------------------------------------------------------------------

    def wrap_tools(
        self, tool_functions: dict[str, Callable]
    ) -> dict[str, Callable]:
        """
        Wrap a dict of tool functions to auto-record each call.

        Args:
            tool_functions: {"tool_name": callable, ...}

        Returns:
            A new dict with the same keys but wrapped callables that
            auto-record to the current active session.

        Example:
            tools = fg.wrap_tools({
                "lookup_order": lookup_order_fn,
                "issue_refund": issue_refund_fn,
            })
            # Now tools["lookup_order"]("ORD-123") auto-records the call
        """
        wrapped: dict[str, Callable] = {}

        for name, fn in tool_functions.items():

            def _make_wrapper(tool_name: str, tool_fn: Callable):
                @functools.wraps(tool_fn)
                def wrapper(*args, **kwargs):
                    result = tool_fn(*args, **kwargs)
                    session = _current_session.get()
                    if session is not None:
                        session.record_tool_call(
                            tool_name,
                            args={"args": args, "kwargs": kwargs},
                            result=result,
                        )
                    return result

                return wrapper

            wrapped[name] = _make_wrapper(name, fn)

        return wrapped

    # ------------------------------------------------------------------
    # Onboarding convenience methods
    # ------------------------------------------------------------------

    def register_agent(
        self,
        name: str,
        tool_categories: dict[str, str],
    ) -> dict:
        """
        Register the agent with the governance API.

        Wraps POST /agents/register.  Returns the full API response dict
        including the one-time api_key.

        Note: This uses the agent_id already set on the Flagent client.
        """
        import requests

        resp = requests.post(
            f"{self.api_url}/agents/register",
            json={
                "agent_id": self.agent_id,
                "name": name,
                "tool_categories": tool_categories,
            },
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def record_baseline(
        self,
        *,
        scenarios: list[dict] | None = None,
        system_prompt: str | None = None,
        tool_list: list[str] | None = None,
    ) -> dict:
        """
        Record a behavioral baseline for the agent.

        Wraps POST /agents/{agent_id}/baseline.

        Either pass `scenarios` (list of trace dicts — no LLM needed) or
        `system_prompt` + `tool_list` (LLM generates scenarios).

        Returns the full API response dict including the fingerprint.
        """
        import requests

        if scenarios is not None:
            body = {"scenarios": scenarios}
        elif system_prompt and tool_list:
            body = {"system_prompt": system_prompt, "tool_list": tool_list}
        else:
            raise ValueError(
                "Provide either 'scenarios' or 'system_prompt' + 'tool_list'"
            )

        resp = requests.post(
            f"{self.api_url}/agents/{self.agent_id}/baseline",
            json=body,
            headers={
                "Content-Type": "application/json",
                "x-flagent-key": self.api_key,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
