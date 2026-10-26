"""
test_shadow_mode.py — Tests for shadow (async, non-blocking) mode.

Verifies that shadow mode:
  - Sends traces in the background
  - Never blocks the caller
  - Swallows all errors silently
"""

import time
from unittest.mock import patch, MagicMock

from flagent import Flagent


def _mock_score_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "session_id": "shadow-001",
        "agent_id": "test-agent",
        "score": 10.0,
        "classification": "normal",
        "components": {},
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestShadowMode:

    @patch("flagent.session.requests.post", return_value=_mock_score_response())
    def test_shadow_sends_trace(self, mock_post):
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="shadow",
        )

        with fg.session() as s:
            s.record_tool_call("lookup_order")

        # Give the background thread a moment
        time.sleep(0.5)

        assert mock_post.called
        body = mock_post.call_args[1]["json"]
        assert body["trace"]["tools_called"] == ["lookup_order"]

    @patch("flagent.session.requests.post", side_effect=Exception("Network error"))
    def test_shadow_swallows_errors(self, mock_post):
        """Shadow mode must never raise into the host application."""
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="shadow",
        )

        # This should NOT raise
        with fg.session() as s:
            s.record_tool_call("lookup_order")

        # Give the background thread time to process (and fail silently)
        time.sleep(0.5)

        # If we got here, the error was swallowed — test passes
        assert mock_post.called

    @patch("flagent.session.requests.post", return_value=_mock_score_response())
    def test_shadow_does_not_block(self, mock_post):
        """Shadow mode should return control immediately."""

        def slow_post(*args, **kwargs):
            time.sleep(2)
            return _mock_score_response()

        mock_post.side_effect = slow_post

        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="shadow",
        )

        start = time.time()
        with fg.session() as s:
            s.record_tool_call("lookup_order")
        elapsed = time.time() - start

        # The session __exit__ should return nearly instantly
        assert elapsed < 1.0, f"Shadow mode blocked for {elapsed:.2f}s"
