"""
verify_phase1.py — Phase 1 Verification Script

Tests the multi-agent foundation:
  1. Register two agents with different tool sets
  2. Record separate baselines for each
  3. Score the SAME trace against each agent → different results
  4. Show 401 on a bad API key
  5. Confirm legacy /score-session still works without auth

Usage:
    $env:PYTHONUTF8="1"
    python verify_phase1.py
"""

import requests
import json
import sys

# Will be set after reading from samconfig or env
API_URL = "https://t2xtoo4zpg.execute-api.ap-south-1.amazonaws.com/dev"


def section(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def test_result(label, passed, detail=""):
    icon = "✅" if passed else "❌"
    print(f"  {icon} {label}")
    if detail:
        print(f"     {detail}")
    return passed


def main():
    passed = 0
    failed = 0

    # ------------------------------------------------------------------
    # TEST 1: Register Agent A (retrieval-heavy)
    # ------------------------------------------------------------------
    section("TEST 1: Register Agent A (retrieval-heavy)")

    resp_a = requests.post(f"{API_URL}/agents/register", json={
        "agent_id": "test-agent-retrieval",
        "name": "Test Retrieval Agent",
        "tool_categories": {
            "search_products": "retrieval",
            "lookup_order": "retrieval",
            "get_faq": "retrieval",
        }
    }, timeout=15)
    print(f"  Status: {resp_a.status_code}")
    print(f"  Body:   {resp_a.text}")

    if resp_a.status_code == 201:
        agent_a = resp_a.json()
        key_a = agent_a["api_key"]
        if test_result("Agent A registered", True, f"api_key starts with: {key_a[:12]}..."):
            passed += 1
    elif resp_a.status_code == 409:
        # Already exists — that's fine for re-runs, but we need the key
        print("  Agent A already exists. Cannot retrieve key. Delete it first or use a new ID.")
        print("  Continuing with remaining tests...")
        key_a = None
        failed += 1
    else:
        test_result("Agent A registered", False, resp_a.text)
        key_a = None
        failed += 1

    # ------------------------------------------------------------------
    # TEST 2: Register Agent B (modification-heavy)
    # ------------------------------------------------------------------
    section("TEST 2: Register Agent B (modification-heavy)")

    resp_b = requests.post(f"{API_URL}/agents/register", json={
        "agent_id": "test-agent-modification",
        "name": "Test Modification Agent",
        "tool_categories": {
            "issue_refund": "modification",
            "cancel_order": "modification",
            "update_address": "modification",
            "send_email": "communication",
        }
    }, timeout=15)
    print(f"  Status: {resp_b.status_code}")
    print(f"  Body:   {resp_b.text}")

    if resp_b.status_code == 201:
        agent_b = resp_b.json()
        key_b = agent_b["api_key"]
        if test_result("Agent B registered", True, f"api_key starts with: {key_b[:12]}..."):
            passed += 1
    elif resp_b.status_code == 409:
        print("  Agent B already exists.")
        key_b = None
        failed += 1
    else:
        test_result("Agent B registered", False, resp_b.text)
        key_b = None
        failed += 1

    if not key_a or not key_b:
        print("\n⚠️  Cannot proceed without both API keys. Exiting.")
        print("  Delete test agents from DynamoDB AgentRegistry and re-run.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # TEST 3: Record baseline for Agent A (retrieval-heavy traces)
    # ------------------------------------------------------------------
    section("TEST 3: Record baseline for Agent A (retrieval-heavy)")

    retrieval_scenarios = [
        {"tools_called": ["search_products"], "tool_counts": {"search_products": 1}, "response_length_words": 35},
        {"tools_called": ["lookup_order"], "tool_counts": {"lookup_order": 1}, "response_length_words": 40},
        {"tools_called": ["search_products", "lookup_order"], "tool_counts": {"search_products": 1, "lookup_order": 1}, "response_length_words": 50},
        {"tools_called": ["get_faq"], "tool_counts": {"get_faq": 1}, "response_length_words": 30},
        {"tools_called": ["search_products", "get_faq"], "tool_counts": {"search_products": 1, "get_faq": 1}, "response_length_words": 45},
        {"tools_called": ["lookup_order"], "tool_counts": {"lookup_order": 1}, "response_length_words": 38},
        {"tools_called": ["search_products"], "tool_counts": {"search_products": 1}, "response_length_words": 32},
        {"tools_called": ["lookup_order", "get_faq"], "tool_counts": {"lookup_order": 1, "get_faq": 1}, "response_length_words": 55},
        {"tools_called": ["search_products"], "tool_counts": {"search_products": 1}, "response_length_words": 28},
        {"tools_called": ["lookup_order"], "tool_counts": {"lookup_order": 1}, "response_length_words": 42},
    ]

    resp_ba = requests.post(
        f"{API_URL}/agents/test-agent-retrieval/baseline",
        json={"scenarios": retrieval_scenarios},
        headers={"x-flagent-key": key_a},
        timeout=30,
    )
    print(f"  Status: {resp_ba.status_code}")
    print(f"  Body:   {resp_ba.text[:500]}")

    if resp_ba.status_code == 200:
        fp_a = resp_ba.json().get("fingerprint", {})
        if test_result("Agent A baseline recorded", True, f"tool_frequency: {fp_a.get('tool_frequency', {})}"):
            passed += 1
    else:
        test_result("Agent A baseline recorded", False, resp_ba.text)
        failed += 1

    # ------------------------------------------------------------------
    # TEST 4: Record baseline for Agent B (modification-heavy traces)
    # ------------------------------------------------------------------
    section("TEST 4: Record baseline for Agent B (modification-heavy)")

    modification_scenarios = [
        {"tools_called": ["issue_refund"], "tool_counts": {"issue_refund": 1}, "response_length_words": 45},
        {"tools_called": ["cancel_order", "send_email"], "tool_counts": {"cancel_order": 1, "send_email": 1}, "response_length_words": 60},
        {"tools_called": ["update_address"], "tool_counts": {"update_address": 1}, "response_length_words": 35},
        {"tools_called": ["issue_refund", "send_email"], "tool_counts": {"issue_refund": 1, "send_email": 1}, "response_length_words": 55},
        {"tools_called": ["cancel_order"], "tool_counts": {"cancel_order": 1}, "response_length_words": 40},
        {"tools_called": ["update_address", "send_email"], "tool_counts": {"update_address": 1, "send_email": 1}, "response_length_words": 50},
        {"tools_called": ["issue_refund", "cancel_order", "send_email"], "tool_counts": {"issue_refund": 1, "cancel_order": 1, "send_email": 1}, "response_length_words": 70},
        {"tools_called": ["issue_refund"], "tool_counts": {"issue_refund": 1}, "response_length_words": 42},
        {"tools_called": ["cancel_order", "update_address"], "tool_counts": {"cancel_order": 1, "update_address": 1}, "response_length_words": 48},
        {"tools_called": ["send_email"], "tool_counts": {"send_email": 1}, "response_length_words": 30},
    ]

    resp_bb = requests.post(
        f"{API_URL}/agents/test-agent-modification/baseline",
        json={"scenarios": modification_scenarios},
        headers={"x-flagent-key": key_b},
        timeout=30,
    )
    print(f"  Status: {resp_bb.status_code}")
    print(f"  Body:   {resp_bb.text[:500]}")

    if resp_bb.status_code == 200:
        fp_b = resp_bb.json().get("fingerprint", {})
        if test_result("Agent B baseline recorded", True, f"tool_frequency: {fp_b.get('tool_frequency', {})}"):
            passed += 1
    else:
        test_result("Agent B baseline recorded", False, resp_bb.text)
        failed += 1

    # ------------------------------------------------------------------
    # TEST 5: Score the SAME trace against Agent A and Agent B
    # ------------------------------------------------------------------
    section("TEST 5: Score SAME trace against both agents (expect different scores)")

    # This trace has 3x issue_refund — abnormal for retrieval agent, closer to normal for modification agent
    test_trace = {
        "tools_called": ["issue_refund", "issue_refund", "issue_refund"],
        "tool_counts": {"issue_refund": 3},
        "response_length_words": 50,
    }

    print(f"  Test trace: {json.dumps(test_trace)}")

    # Score against Agent A (retrieval)
    resp_sa = requests.post(
        f"{API_URL}/score-session",
        json={"trace": test_trace, "agent_id": "test-agent-retrieval"},
        headers={"x-flagent-key": key_a},
        timeout=15,
    )
    print(f"\n  Agent A (retrieval) response:")
    print(f"    Status: {resp_sa.status_code}")
    print(f"    Body:   {resp_sa.text}")
    score_a = resp_sa.json() if resp_sa.status_code == 200 else {}

    # Score against Agent B (modification)
    resp_sb = requests.post(
        f"{API_URL}/score-session",
        json={"trace": test_trace, "agent_id": "test-agent-modification"},
        headers={"x-flagent-key": key_b},
        timeout=15,
    )
    print(f"\n  Agent B (modification) response:")
    print(f"    Status: {resp_sb.status_code}")
    print(f"    Body:   {resp_sb.text}")
    score_b = resp_sb.json() if resp_sb.status_code == 200 else {}

    if score_a and score_b:
        s_a = score_a.get("score", -1)
        s_b = score_b.get("score", -1)
        different = abs(s_a - s_b) > 0.01
        if test_result(
            "Different scores for same trace",
            different,
            f"Agent A score: {s_a} ({score_a.get('classification')})  |  Agent B score: {s_b} ({score_b.get('classification')})",
        ):
            passed += 1
        else:
            failed += 1
    else:
        test_result("Different scores for same trace", False, "One or both scoring calls failed")
        failed += 1

    # ------------------------------------------------------------------
    # TEST 6: 401 on bad API key
    # ------------------------------------------------------------------
    section("TEST 6: 401 on bad API key")

    resp_bad = requests.post(
        f"{API_URL}/score-session",
        json={"trace": test_trace, "agent_id": "test-agent-retrieval"},
        headers={"x-flagent-key": "fgnt_THIS_IS_A_FAKE_KEY_12345"},
        timeout=15,
    )
    print(f"  Status: {resp_bad.status_code}")
    print(f"  Body:   {resp_bad.text}")

    if test_result("401 on bad key", resp_bad.status_code == 401):
        passed += 1
    else:
        failed += 1

    # ------------------------------------------------------------------
    # TEST 7: Legacy /score-session still works (no auth header)
    # ------------------------------------------------------------------
    section("TEST 7: Legacy /score-session (no auth header)")

    legacy_trace = {
        "tools_called": ["lookup_order"],
        "tool_counts": {"lookup_order": 1},
        "response_length_words": 40,
    }

    resp_legacy = requests.post(
        f"{API_URL}/score-session",
        json={"trace": legacy_trace},
        timeout=15,
    )
    print(f"  Status: {resp_legacy.status_code}")
    print(f"  Body:   {resp_legacy.text}")

    if resp_legacy.status_code == 200:
        legacy_result = resp_legacy.json()
        if test_result(
            "Legacy endpoint works",
            True,
            f"score: {legacy_result.get('score')}, class: {legacy_result.get('classification')}",
        ):
            passed += 1
    else:
        test_result("Legacy endpoint works", False, resp_legacy.text)
        failed += 1

    # ------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------
    total = passed + failed
    section("PHASE 1 VERIFICATION SUMMARY")
    print(f"  Passed: {passed}/{total}")
    print(f"  Failed: {failed}/{total}")
    print(f"  Result: {'✅ ALL TESTS PASSED' if failed == 0 else '❌ SOME TESTS FAILED'}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
