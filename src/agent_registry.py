"""
agent_registry.py — Agent Registry CRUD

Manages agent registration, lookup, and metadata via the storage interface.
The raw API key is returned once on registration; only the SHA-256 hash
is persisted.
"""

import os
from datetime import datetime, timezone

from auth import generate_api_key, hash_api_key
from storage.factory import get_storage


# ---------------------------------------------------------------------------
# Default scoring configuration (per-agent, overridable)
# ---------------------------------------------------------------------------
DEFAULT_SCORING_CONFIG = {
    "weights": {
        "volume": 0.45,
        "cosine": 0.20,
        "bigram": 0.20,
        "zscore": 0.15,
    },
    "thresholds": {
        "normal_max": 30,
        "warning_max": 60,
        # > warning_max is alert
    },
    "min_cluster_samples": 5,
}


def register_agent(agent_id: str, name: str, tool_categories: dict,
                    scoring_config: dict | None = None) -> dict:
    """
    Register a new agent in the registry.

    Args:
        agent_id:        Unique identifier for the agent (e.g. "travel-bot-v1")
        name:            Human-readable display name
        tool_categories: Map of tool_name -> category
                         e.g. {"lookup_order": "retrieval",
                               "issue_refund": "modification",
                               "send_email": "communication"}
        scoring_config:  Optional per-agent scoring weights/thresholds.
                         Falls back to DEFAULT_SCORING_CONFIG.

    Returns:
        {"agent_id": str, "api_key": str, "created_at": str}
        The api_key is returned ONCE — only the hash is stored.

    Raises:
        ValueError if agent_id already exists.
    """
    storage = get_storage()

    # Generate API key
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)

    now = datetime.now(timezone.utc).isoformat()

    config = scoring_config if scoring_config else DEFAULT_SCORING_CONFIG

    data = {
        "agent_id": agent_id,
        "name": name,
        "tool_categories": tool_categories,
        "api_key_hash": key_hash,
        "status": "active",
        "mode_default": "shadow",
        "scoring_config": config,
        "created_at": now,
    }

    storage.create_agent(agent_id, data)

    return {
        "agent_id": agent_id,
        "api_key": raw_key,   # Returned ONCE — never stored
        "created_at": now,
    }


def get_agent(agent_id: str) -> dict | None:
    """Fetch agent record by ID.  Returns None if not found."""
    storage = get_storage()
    return storage.get_agent(agent_id)
