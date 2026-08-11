"""
run_baseline — Lambda handler (placeholder)

Runs the agent against all synthetic scenarios and records the behavioural
fingerprint: tool call frequency distribution, average response length,
typical tool call sequences, and data access patterns.
Uses Google Gemini (free tier) via the google-genai SDK.

POST /run-baseline
Body: { "agent_id": str }
"""

import json
import os


def handler(event, context):
    """Run baseline fingerprinting against synthetic scenarios."""
    try:
        body = json.loads(event.get("body", "{}"))
        agent_id = body.get("agent_id")

        if not agent_id:
            return _response(400, {"error": "agent_id is required"})

        # TODO: Sprint 3 — fetch stored scenarios for agent_id,
        # execute the agent against each via Gemini, record behavioural
        # fingerprint (tool call frequency, response length stats,
        # call sequences, data access patterns) into AgentBaselines table.

        return _response(200, {
            "message": "placeholder — baseline recording not yet implemented",
            "agent_id": agent_id,
        })

    except Exception as e:
        return _response(500, {"error": str(e)})


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
