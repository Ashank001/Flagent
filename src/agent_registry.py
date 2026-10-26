"""
agent_registry.py — Agent Registry CRUD

Manages agent registration, lookup, and metadata in the AgentRegistry
DynamoDB table. The raw API key is returned once on registration; only
the SHA-256 hash is persisted.

Table schema:
    PK:  agent_id (S)
    Attributes: name, tool_categories, api_key_hash, status, mode_default,
                scoring_config, created_at
"""

import os
import json
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

from auth import generate_api_key, hash_api_key


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


def _get_table():
    """Get the AgentRegistry DynamoDB table resource."""
    region = os.environ.get("AWS_REGION", "ap-south-1")
    table_name = os.environ.get("AGENT_REGISTRY_TABLE", "AgentRegistry")
    dynamodb = boto3.resource("dynamodb", region_name=region)
    return dynamodb.Table(table_name)


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
    table = _get_table()

    # Generate API key
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)

    now = datetime.now(timezone.utc).isoformat()

    config = scoring_config if scoring_config else DEFAULT_SCORING_CONFIG

    item = json.loads(
        json.dumps({
            "agent_id": agent_id,
            "name": name,
            "tool_categories": tool_categories,
            "api_key_hash": key_hash,
            "status": "active",
            "mode_default": "shadow",
            "scoring_config": config,
            "created_at": now,
        }),
        parse_float=Decimal,
    )

    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(agent_id)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ValueError(f"Agent '{agent_id}' already exists")
        raise

    return {
        "agent_id": agent_id,
        "api_key": raw_key,   # Returned ONCE — never stored
        "created_at": now,
    }


def get_agent(agent_id: str) -> dict | None:
    """Fetch agent record by ID.  Returns None if not found."""
    table = _get_table()
    response = table.get_item(Key={"agent_id": agent_id})
    return response.get("Item")
