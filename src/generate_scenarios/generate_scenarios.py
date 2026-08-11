"""
generate_scenarios — Lambda handler (placeholder)

Given an agent's system prompt and tool list, generates 50 diverse synthetic
test scenarios that exercise the agent's expected behaviour space.
Uses Google Gemini (free tier) via the google-genai SDK.

POST /generate-scenarios
Body: { "agent_id": str, "system_prompt": str, "tools": list[str] }
"""

import json
import os


def handler(event, context):
    """Generate synthetic test scenarios for an agent."""
    try:
        body = json.loads(event.get("body", "{}"))
        agent_id = body.get("agent_id")
        system_prompt = body.get("system_prompt")
        tools = body.get("tools", [])

        if not agent_id or not system_prompt:
            return _response(400, {
                "error": "agent_id and system_prompt are required"
            })

        # TODO: Sprint 2 — call Google Gemini to generate 50 synthetic scenarios
        # based on the agent's system prompt and tool list.

        return _response(200, {
            "message": "placeholder — scenario generation not yet implemented",
            "agent_id": agent_id,
            "system_prompt_length": len(system_prompt),
            "tool_count": len(tools),
        })

    except Exception as e:
        return _response(500, {"error": str(e)})


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
