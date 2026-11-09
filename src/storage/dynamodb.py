"""
dynamodb.py — DynamoDB storage backend for Flagent.

Wraps the existing DynamoDB logic (Decimal handling, table lookups)
behind the StorageBackend interface.  boto3 is imported at module level
but this module is only loaded when STORAGE=dynamodb (lazy import in factory).
"""

import json
import os
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

from storage.base import StorageBackend


def _decimal_to_native(obj):
    """Recursively convert Decimal values from DynamoDB to float/int."""
    if isinstance(obj, Decimal):
        if obj == int(obj):
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_native(i) for i in obj]
    return obj


def _native_to_decimal(obj):
    """Recursively convert a Python dict to DynamoDB-safe types (Decimal)."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


class DynamoDBStorage(StorageBackend):
    """DynamoDB-backed storage using three tables."""

    def __init__(self):
        region = os.environ.get("AWS_REGION", "ap-south-1")
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._registry_name = os.environ.get(
            "AGENT_REGISTRY_TABLE", "AgentRegistry"
        )
        self._baselines_name = os.environ.get(
            "BASELINES_TABLE", "AgentBaselines"
        )
        self._sessions_name = os.environ.get(
            "SESSIONS_TABLE", "SessionScores"
        )

    def _table(self, name: str):
        return self._dynamodb.Table(name)

    # ── Agents ────────────────────────────────────────────────────────

    def create_agent(self, agent_id: str, data: dict) -> None:
        table = self._table(self._registry_name)
        item = _native_to_decimal({**data, "agent_id": agent_id})
        try:
            table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(agent_id)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(f"Agent '{agent_id}' already exists")
            raise

    def get_agent(self, agent_id: str) -> dict | None:
        table = self._table(self._registry_name)
        response = table.get_item(Key={"agent_id": agent_id})
        item = response.get("Item")
        return _decimal_to_native(item) if item else None

    def update_agent_status(self, agent_id: str, status: str) -> None:
        table = self._table(self._registry_name)
        try:
            table.update_item(
                Key={"agent_id": agent_id},
                UpdateExpression="SET #s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": status},
                ConditionExpression="attribute_exists(agent_id)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise KeyError(f"Agent '{agent_id}' not found")
            raise

    # ── Baselines ─────────────────────────────────────────────────────
    #
    # DynamoDB schema: AgentBaselines table, PK = agent_id.
    # The existing v2 code stores everything in a single item:
    #   { agent_id, fingerprint (blended), intent_fingerprints: {cluster: {fingerprint, sample_count}},
    #     min_cluster_samples, scenario_count, source, created_at }
    #
    # The storage interface splits by cluster.  We map:
    #   put_baseline(agent_id, "blended", data)  →  updates the main item
    #   put_baseline(agent_id, "retrieval", data) → merges into intent_fingerprints
    #   get_baseline(agent_id, "blended")  →  returns the main item's fingerprint portion
    #   get_all_baselines(agent_id) → returns {cluster: data} for blended + each intent
    #

    def put_baseline(self, agent_id: str, cluster: str,
                     fingerprint_data: dict) -> None:
        table = self._table(self._baselines_name)

        # Read existing item (or empty)
        response = table.get_item(Key={"agent_id": agent_id})
        existing = response.get("Item", {"agent_id": agent_id})

        if cluster == "blended":
            # Store blended fingerprint at top level (backward compat)
            existing["fingerprint"] = fingerprint_data.get(
                "fingerprint", fingerprint_data
            )
            for key in ("min_cluster_samples", "scenario_count",
                        "source", "created_at"):
                if key in fingerprint_data:
                    existing[key] = fingerprint_data[key]
        else:
            # Store as intent_fingerprints.{cluster}
            if "intent_fingerprints" not in existing:
                existing["intent_fingerprints"] = {}
            existing["intent_fingerprints"][cluster] = {
                "fingerprint": fingerprint_data.get(
                    "fingerprint", fingerprint_data
                ),
                "sample_count": fingerprint_data.get("sample_count", 0),
            }

        item = _native_to_decimal(existing)
        table.put_item(Item=item)

    def get_baseline(self, agent_id: str, cluster: str) -> dict | None:
        table = self._table(self._baselines_name)
        response = table.get_item(Key={"agent_id": agent_id})
        item = response.get("Item")
        if not item:
            return None

        item = _decimal_to_native(item)

        if cluster == "blended":
            fp = item.get("fingerprint")
            if not fp:
                return None
            return {
                "fingerprint": fp,
                "min_cluster_samples": item.get("min_cluster_samples", 5),
                "scenario_count": item.get("scenario_count", 0),
                "source": item.get("source", ""),
                "created_at": item.get("created_at", ""),
            }
        else:
            intents = item.get("intent_fingerprints", {})
            return intents.get(cluster)

    def get_all_baselines(self, agent_id: str) -> dict[str, dict]:
        table = self._table(self._baselines_name)
        response = table.get_item(Key={"agent_id": agent_id})
        item = response.get("Item")
        if not item:
            return {}

        item = _decimal_to_native(item)
        result = {}

        fp = item.get("fingerprint")
        if fp:
            result["blended"] = {
                "fingerprint": fp,
                "min_cluster_samples": item.get("min_cluster_samples", 5),
                "scenario_count": item.get("scenario_count", 0),
                "source": item.get("source", ""),
                "created_at": item.get("created_at", ""),
            }

        for cluster, data in item.get("intent_fingerprints", {}).items():
            result[cluster] = data

        return result

    # ── Sessions ──────────────────────────────────────────────────────

    def put_session(self, agent_id: str, session_id: str,
                    data: dict) -> None:
        table = self._table(self._sessions_name)
        item = _native_to_decimal({
            **data,
            "agent_id": agent_id,
            "session_id": session_id,
        })
        table.put_item(Item=item)

    def get_session(self, agent_id: str,
                    session_id: str) -> dict | None:
        table = self._table(self._sessions_name)
        response = table.get_item(
            Key={"agent_id": agent_id, "session_id": session_id}
        )
        item = response.get("Item")
        return _decimal_to_native(item) if item else None

    def list_recent_sessions(self, agent_id: str,
                             limit: int = 20) -> list[dict]:
        table = self._table(self._sessions_name)
        # DynamoDB query on PK, sort by created_at in application layer
        # (SessionScores SK is session_id, not timestamp, so we scan the partition)
        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("agent_id").eq(agent_id),
        )
        items = [_decimal_to_native(i) for i in response.get("Items", [])]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return items[:limit]

