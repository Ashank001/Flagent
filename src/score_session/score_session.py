"""
score_session — Lambda handler (placeholder)

Scores a production session against the stored baseline. Computes running
statistics and flags sessions where behaviour deviates beyond a configurable
threshold (normal / warning / alert).

POST /score-session
Body: { "agent_id": str, "session_id": str, "session_data": dict }
"""

import json
import os


def handler(event, context):
    """Score a production session against the baseline."""
    try:
        body = json.loads(event.get("body", "{}"))
        agent_id = body.get("agent_id")
        session_id = body.get("session_id")
        session_data = body.get("session_data", {})

        if not agent_id or not session_id:
            return _response(400, {
                "error": "agent_id and session_id are required"
            })

        # TODO: Sprint 4 — fetch baseline for agent_id from AgentBaselines,
        # compare session_data metrics against it, compute deviation scores,
        # classify as normal/warning/alert, write result to SessionScores.

        return _response(200, {
            "message": "placeholder — session scoring not yet implemented",
            "agent_id": agent_id,
            "session_id": session_id,
        })

    except Exception as e:
        return _response(500, {"error": str(e)})


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
