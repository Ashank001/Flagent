"""
test_fail_open.py — Tests for fail-open (and fail-closed) behavior.

Verifies that when the governance API is unreachable:
  - Default (fail-open):  agent keeps working, result is ScoreResult.fail_open()
  - fail_closed=True:     FlagentBlocked is raised
  - Shadow mode:          errors are swallowed silently
"""

from unittest.mock import patch, MagicMock
import pytest

from flagent import Flagent, FlagentBlocked
from flagent.models import ScoreResult


class TestFailOpen:

    @patch("flagent.session.requests.post", side_effect=ConnectionError("API down"))
    def test_enforce_fail_open_default(self, mock_post):
        """By default, enforce mode should fail-open when API is down."""
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        # Should NOT raise
        with fg.session() as s:
            s.record_tool_call("lookup_order")

        assert s.result is not None
        assert s.result.classification == "unknown"
        assert "API unreachable" in s.result.raw_response.get("error", "")

    @patch("flagent.session.requests.post", side_effect=ConnectionError("API down"))
    def test_enforce_fail_closed(self, mock_post):
        """With fail_closed=True, enforce mode should raise."""
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        with pytest.raises(FlagentBlocked) as exc_info:
            with fg.session(fail_closed=True) as s:
                s.record_tool_call("lookup_order")

        assert "fail_closed=True" in str(exc_info.value)

    @patch("flagent.session.requests.post", side_effect=TimeoutError("Timeout"))
    def test_enforce_timeout_fail_open(self, mock_post):
        """Timeout should also trigger fail-open."""
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        with fg.session() as s:
            s.record_tool_call("lookup_order")

        assert s.result.classification == "unknown"
