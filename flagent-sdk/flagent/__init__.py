"""
flagent — Behavioral Governance SDK for AI Agents

Usage:
    from flagent import Flagent

    fg = Flagent(api_url="https://...", api_key="fgnt_...", agent_id="my-bot")

    @fg.governed()
    def handle_request(user_msg):
        tools["lookup_order"]("ORD-123")
        return "Done"
"""

from flagent.client import Flagent
from flagent.exceptions import FlagentBlocked, FlagentError
from flagent.models import ScoreResult, ToolCall

__version__ = "0.1.0"
__all__ = ["Flagent", "FlagentBlocked", "FlagentError", "ScoreResult", "ToolCall"]
