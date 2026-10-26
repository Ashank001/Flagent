"""
register_agent.py — Lambda handler for POST /agents/register

Registers a new agent in the AgentRegistry DynamoDB table and returns the
API key ONCE.  The key is never stored — only its SHA-256 hash is persisted.

Request body:
    {
        "agent_id":         "my-agent-v1",            # required, unique
        "name":             "My Agent",                # optional, defaults to agent_id
        "tool_categories":  {                          # required
            "lookup_order":  "retrieval",
            "issue_refund":  "modification",
            "send_email":    "communication"
        }
    }

Response (201):
    {
        "agent_id":    "my-agent-v1",
        "api_key":     "fgnt_...",         # ⚠️ ONLY returned here
        "created_at":  "2026-10-26T...",
        "message":     "Agent registered. ..."
    }
"""

import json
import traceback
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_registry import register_agent

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,x-flagent-key",
    "Access-Control-Allow-Methods": "OPTIONS,POST",
}


def handler(event, context):
    """Lambda entry-point for POST /agents/register."""
    try:
        body = json.loads(event.get("body", "{}"))

        agent_id = body.get("agent_id")
        name = body.get("name", agent_id)
        tool_categories = body.get("tool_categories", {})

        # --- Validation ---
        if not agent_id:
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({
                    "error": "Missing required field: agent_id"
                }),
            }

        if not isinstance(tool_categories, dict):
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({
                    "error": "tool_categories must be a map of tool_name -> category"
                }),
            }

        # --- Register ---
        result = register_agent(agent_id, name, tool_categories)

        return {
            "statusCode": 201,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "agent_id": result["agent_id"],
                "api_key": result["api_key"],
                "created_at": result["created_at"],
                "message": (
                    "Agent registered successfully.  "
                    "Store the api_key securely — it will NOT be shown again."
                ),
            }),
        }

    except ValueError as e:
        # Duplicate agent_id
        return {
            "statusCode": 409,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)}),
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)}),
        }
