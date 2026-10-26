"""
auth.py — API Key Authentication Utilities

Handles API key generation, hashing (SHA-256), and validation for the
Flagent governance API. Keys are never stored raw — only the hash is persisted.

Uses secrets.compare_digest for timing-safe comparison to prevent timing attacks.
"""

import hashlib
import secrets
import os

import boto3


def generate_api_key(prefix: str = "fgnt") -> str:
    """Generate a secure random API key with a recognizable prefix.

    Example output: fgnt_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8
    """
    random_part = secrets.token_urlsafe(32)
    return f"{prefix}_{random_part}"


def hash_api_key(api_key: str) -> str:
    """SHA-256 hash of the API key for storage. Never store raw keys."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def validate_api_key_from_event(event: dict, agent_id: str) -> dict:
    """
    Validate the x-flagent-key header against the stored hash for agent_id.

    Reads the AgentRegistry table from env vars (AGENT_REGISTRY_TABLE, AWS_REGION).

    Returns:
        {"valid": True, "agent": <agent_record_dict>}  on success
        {"valid": False, "error": "..."}                on failure
    """
    headers = event.get("headers", {}) or {}

    # API Gateway lowercases header names in HTTP API; REST API preserves case.
    # Check both forms for safety.
    api_key = headers.get("x-flagent-key") or headers.get("X-Flagent-Key")

    if not api_key:
        return {"valid": False, "error": "Missing x-flagent-key header"}

    region = os.environ.get("AWS_REGION", "ap-south-1")
    registry_table = os.environ.get("AGENT_REGISTRY_TABLE", "AgentRegistry")

    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(registry_table)

    try:
        response = table.get_item(Key={"agent_id": agent_id})
    except Exception as e:
        return {"valid": False, "error": f"Registry lookup failed: {str(e)}"}

    agent = response.get("Item")
    if not agent:
        return {"valid": False, "error": f"Agent '{agent_id}' not found in registry"}

    if agent.get("status") != "active":
        return {"valid": False, "error": f"Agent '{agent_id}' is not active"}

    stored_hash = agent.get("api_key_hash", "")
    provided_hash = hash_api_key(api_key)

    if not secrets.compare_digest(stored_hash, provided_hash):
        return {"valid": False, "error": "Invalid API key"}

    return {"valid": True, "agent": agent}


def is_legacy_request(event: dict) -> bool:
    """Check if this is a legacy request (no x-flagent-key header).

    Legacy requests bypass auth and use the default agent / local baseline.
    """
    headers = event.get("headers", {}) or {}
    return not (headers.get("x-flagent-key") or headers.get("X-Flagent-Key"))
