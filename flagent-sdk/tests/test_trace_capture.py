"""
test_trace_capture.py — Tests for tool-call recording and trace building.

All tests use mocked HTTP — no network calls, no LLM.
"""

import json
from unittest.mock import patch, MagicMock

from flagent import Flagent


def _mock_score_response(score=15.0, classification="normal"):
    """Return a mock requests.Response for /score-session."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "session_id": "test-session-001",
        "agent_id": "test-agent",
        "score": score,
        "classification": classification,
        "components": {
            "cosine_distance": 5.0,
            "bigram_novelty": 10.0,
            "volume_anomaly": 8.0,
            "length_zscore": 3.0,
        },
        "intent_cluster": "retrieval",
        "baseline_used": "retrieval",
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestManualSession:
    """Tests for the context-manager (manual) session interface."""

    @patch("flagent.session.requests.post", return_value=_mock_score_response())
    def test_records_tool_calls(self, mock_post):
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        with fg.session() as s:
            s.record_tool_call("lookup_order", args={"id": "123"})
            s.record_tool_call("send_email", args={"to": "user@test.com"})

        # Verify the trace sent to the API
        call_args = mock_post.call_args
        body = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        trace = body["trace"]

        assert trace["tools_called"] == ["lookup_order", "send_email"]
        assert trace["tool_counts"] == {"lookup_order": 1, "send_email": 1}
        assert len(s.tool_calls) == 2

    @patch("flagent.session.requests.post", return_value=_mock_score_response())
    def test_result_available_after_session(self, mock_post):
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        with fg.session() as s:
            s.record_tool_call("lookup_order")

        assert s.result is not None
        assert s.result.score == 15.0
        assert s.result.classification == "normal"
        assert s.result.intent_cluster == "retrieval"

    @patch("flagent.session.requests.post", return_value=_mock_score_response())
    def test_duplicate_tool_counts(self, mock_post):
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        with fg.session() as s:
            s.record_tool_call("issue_refund")
            s.record_tool_call("issue_refund")
            s.record_tool_call("issue_refund")

        trace = mock_post.call_args[1]["json"]["trace"]
        assert trace["tools_called"] == ["issue_refund"] * 3
        assert trace["tool_counts"] == {"issue_refund": 3}

    @patch("flagent.session.requests.post", return_value=_mock_score_response())
    def test_response_length_set(self, mock_post):
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        with fg.session() as s:
            s.record_tool_call("lookup_order")
            s.set_response_length(42)

        trace = mock_post.call_args[1]["json"]["trace"]
        assert trace["response_length_words"] == 42


class TestDecoratorCapture:
    """Tests for the @governed() decorator trace capture."""

    @patch("flagent.session.requests.post", return_value=_mock_score_response())
    def test_decorator_captures_wrapped_tools(self, mock_post):
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        # Define and wrap tools
        def lookup_order(order_id):
            return {"status": "shipped"}

        def issue_refund(order_id, amount):
            return {"refunded": True}

        tools = fg.wrap_tools({
            "lookup_order": lookup_order,
            "issue_refund": issue_refund,
        })

        @fg.governed()
        def handle_request(msg):
            r1 = tools["lookup_order"]("ORD-123")
            r2 = tools["issue_refund"]("ORD-123", 50)
            return f"Done: {r1}, {r2}"

        result = handle_request("help me")

        # Verify the function ran
        assert "Done" in result

        # Verify trace was sent
        trace = mock_post.call_args[1]["json"]["trace"]
        assert trace["tools_called"] == ["lookup_order", "issue_refund"]
        assert trace["tool_counts"] == {"lookup_order": 1, "issue_refund": 1}

    @patch("flagent.session.requests.post", return_value=_mock_score_response())
    def test_last_result_attached_to_wrapper(self, mock_post):
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        @fg.governed()
        def handle(msg):
            pass

        handle("test")

        assert handle.last_result is not None
        assert handle.last_result.score == 15.0


class TestWrapTools:
    """Tests for fg.wrap_tools()."""

    def test_wrapped_function_returns_original_result(self):
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
        )

        def lookup_order(order_id):
            return {"status": "shipped", "id": order_id}

        tools = fg.wrap_tools({"lookup_order": lookup_order})

        # Outside a session, still works (no recording happens)
        result = tools["lookup_order"]("ORD-123")
        assert result == {"status": "shipped", "id": "ORD-123"}

    @patch("flagent.session.requests.post", return_value=_mock_score_response())
    def test_wrapped_tools_record_inside_session(self, mock_post):
        fg = Flagent(
            api_url="https://test.api/dev",
            api_key="fgnt_test",
            agent_id="test-agent",
            mode="enforce",
        )

        def my_tool(x):
            return x * 2

        tools = fg.wrap_tools({"my_tool": my_tool})

        with fg.session() as s:
            from flagent.client import _current_session
            _current_session.set(s)
            result = tools["my_tool"](21)

        assert result == 42
        assert len(s.tool_calls) == 1
        assert s.tool_calls[0].name == "my_tool"
