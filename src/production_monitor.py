"""
production_monitor.py — Production Monitor / Session Scorer

Accepts a new session, runs it through the target agent, scores it using the
baseline fingerprint, and saves the result via the storage interface.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from mock_agent import run_session
from deviation_scorer import score_session
from storage.factory import get_storage


def process_session(user_message: str, agent_id: str = "mock-customer-support", system_prompt: str | None = None) -> dict:
    """Run session, score it, save to storage, and return results."""
    # 1. Load Fingerprint from canonical data file (relative to module package root)
    package_root = os.path.dirname(os.path.abspath(__file__))
    baseline_path = os.path.join(package_root, "data", "baseline_output.json")
    if not os.path.exists(baseline_path):
        candidates = [
            os.path.join(os.path.dirname(package_root), "src", "data", "baseline_output.json"),
            os.path.join(os.path.dirname(package_root), "data", "baseline_output.json"),
            os.path.join(package_root, "baseline_output.json"),
        ]
        for c in candidates:
            if os.path.exists(c):
                baseline_path = c
                break
    if not os.path.exists(baseline_path):
        raise RuntimeError(f"baseline_output.json not found at {baseline_path}. Run baseline_recorder.py first.")

    with open(baseline_path, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    fingerprint = baseline["fingerprint"]

    # 2. Run target agent
    result = run_session(user_message, system_prompt=system_prompt)

    trace = {
        "tools_called": result["tool_sequence"],
        "tool_counts": result["tool_counts"] if "tool_counts" in result else __import__('collections').Counter(result["tool_sequence"]),
        "response_length_words": len(result["response_text"].split()),
    }

    # 3. Score session
    score_result = score_session(trace, fingerprint)

    # 4. Save to storage
    storage = get_storage()
    session_id = str(uuid.uuid4())

    storage.put_session(agent_id, session_id, {
        "score": score_result["score"],
        "classification": score_result["classification"],
        "components": score_result["components"],
        "trace": trace,
        "scenario": user_message[:500],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "session_id": session_id,
        "score_result": score_result,
        "trace": trace
    }
