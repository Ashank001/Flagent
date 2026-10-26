"""
test_enforce_mode.py — Tests for enforce (synchronous) mode.

Verifies:
  - Score result is available after session
  - on_alert / on_warning callbacks fire
  - raise_on_alert raises FlagentBlocked
"""

from unittest.mock import patch, MagicMock
import pytest

from flagent import Flagent, FlagentBlocked
from flagent.models import ScoreResult


def _mock_response(score, classification):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "session_id": "enforce-001",
        "agent_id": "test-agent",
        "score": score,
        "classification": classification,
        "components": {
            "cosine_distance": score * 0.3,
            "bigram_novelty": score * 0.4,
            "volume_anomaly": score * 0.2,
            "length_zscore": score * 0.1,
        },
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestEnforceMode:

    @patch("flagent.session.requests.post", return_value=_mock_response(15.0, "normal"))
    def test_normal_score_no_callback(self, mock_post):
        callback = MagicMock()
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        with fg.session(on_alert=callback) as s:
            s.record_tool_call("lookup_order")

        callback.assert_not_called()
        assert s.result.classification == "normal"

    @patch("flagent.session.requests.post", return_value=_mock_response(75.0, "alert"))
    def test_alert_fires_callback(self, mock_post):
        callback = MagicMock()
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        with fg.session(on_alert=callback) as s:
            s.record_tool_call("issue_refund")
            s.record_tool_call("issue_refund")
            s.record_tool_call("issue_refund")

        callback.assert_called_once()
        result = callback.call_args[0][0]
        assert isinstance(result, ScoreResult)
        assert result.score == 75.0

    @patch("flagent.session.requests.post", return_value=_mock_response(45.0, "warning"))
    def test_warning_fires_callback(self, mock_post):
        alert_cb = MagicMock()
        warning_cb = MagicMock()
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        with fg.session(on_alert=alert_cb, on_warning=warning_cb) as s:
            s.record_tool_call("issue_refund")

        alert_cb.assert_not_called()
        warning_cb.assert_called_once()

    @patch("flagent.session.requests.post", return_value=_mock_response(80.0, "alert"))
    def test_raise_on_alert(self, mock_post):
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        with pytest.raises(FlagentBlocked) as exc_info:
            with fg.session(raise_on_alert=True) as s:
                s.record_tool_call("issue_refund")
                s.record_tool_call("issue_refund")

        assert exc_info.value.score_result is not None
        assert exc_info.value.score_result.score == 80.0

    @patch("flagent.session.requests.post", return_value=_mock_response(15.0, "normal"))
    def test_raise_on_alert_does_not_raise_for_normal(self, mock_post):
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        # Should NOT raise
        with fg.session(raise_on_alert=True) as s:
            s.record_tool_call("lookup_order")

        assert s.result.classification == "normal"
