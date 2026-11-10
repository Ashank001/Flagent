"""
scripts/seed_baseline.py — Seed baseline data into configured storage.

Loads canonical baseline fingerprint from src/data/baseline_output.json and
writes it to the active storage backend (Firestore, DynamoDB, or Memory).

Idempotent: can be run repeatedly without duplicating agents or failing.
No LLM calls: strictly precomputed statistics.

Usage:
    python scripts/seed_baseline.py
    # or with env vars:
    STORAGE=firestore python scripts/seed_baseline.py
"""

import json
import os
import sys
from datetime import datetime, timezone

# Ensure src/ is on sys.path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from storage.factory import get_storage
from agent_registry import register_agent


def seed_baseline(agent_id: str | None = None, baseline_path: str | None = None) -> dict:
    """
    Seed baseline data into the configured storage backend.

    Returns summary of seeded records.
    """
    if baseline_path is None:
        baseline_path = os.path.join(_SRC, "data", "baseline_output.json")

    if not os.path.exists(baseline_path):
        raise FileNotFoundError(f"Baseline file not found at {baseline_path}")

    with open(baseline_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    target_agent_id = agent_id or data.get("agent_id", "mock-customer-support")
    fingerprint = data.get("fingerprint", {})
    scenario_count = data.get("scenario_count", len(data.get("session_results", [])))

    storage = get_storage()
    print(f"[Seed] Storage backend: {storage.__class__.__name__}")
    print(f"[Seed] Target agent ID: {target_agent_id}")

    # 1. Ensure agent is registered in the registry
    existing_agent = storage.get_agent(target_agent_id)
    api_key = None
    if existing_agent is None:
        print(f"[Seed] Registering agent '{target_agent_id}'...")
        tool_categories = {
            "lookup_order": "retrieval",
            "issue_refund": "modification",
            "send_email": "communication",
            "update_address": "modification",
        }
        reg_result = register_agent(
            agent_id=target_agent_id,
            name="Mock Customer Support Agent",
            tool_categories=tool_categories,
        )
        api_key = reg_result.get("api_key")
        print(f"[Seed] Agent registered. (API key generated: {api_key[:10]}...)")
    else:
        print(f"[Seed] Agent '{target_agent_id}' already exists in registry.")

    # 2. Put blended baseline fingerprint (idempotent overwrite)
    baseline_payload = {
        "fingerprint": fingerprint,
        "scenario_count": scenario_count,
        "source": "seed_baseline_script",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    storage.put_baseline(target_agent_id, "blended", baseline_payload)
    print(f"[Seed] Put blended baseline for '{target_agent_id}' ({scenario_count} scenarios).")

    # 3. Verify write was successful
    loaded_blended = storage.get_baseline(target_agent_id, "blended")
    assert loaded_blended is not None, "Verification failed: baseline was not saved."
    assert "fingerprint" in loaded_blended, "Verification failed: missing fingerprint key."

    print("[Seed] Successfully verified baseline in storage.")
    return {
        "agent_id": target_agent_id,
        "status": "seeded",
        "scenario_count": scenario_count,
        "api_key": api_key,
    }


if __name__ == "__main__":
    result = seed_baseline()
    print(f"\nResult: {json.dumps(result, indent=2)}")
