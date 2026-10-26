"""
verify_phase2.py — Phase 2 Verification Script

Tests per-intent baselines:
  1. Register an agent with tools in BOTH retrieval and modification categories
  2. Record baseline with enough traces in each category (>= min_cluster_samples)
  3. Score a "3 refunds" trace → should classify as modification, use modification cluster
  4. Use include_all_clusters to show the SAME trace scores differently against each cluster
  5. Confirm legacy validate.py still passes (done separately)

Usage:
    $env:PYTHONUTF8="1"
    python verify_phase2.py
"""

import requests
import json
import sys

API_URL = "https://t2xtoo4zpg.execute-api.ap-south-1.amazonaws.com/dev"

AGENT_ID = "test-mixed-agent-v2"


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
    # TEST 1: Register mixed agent
    # ------------------------------------------------------------------
    section("TEST 1: Register agent with retrieval + modification tools")

    resp = requests.post(f"{API_URL}/agents/register", json={
        "agent_id": AGENT_ID,
        "name": "Mixed Support Agent",
        "tool_categories": {
            "search_products": "retrieval",
            "lookup_order": "retrieval",
            "get_faq": "retrieval",
            "check_inventory": "retrieval",
            "track_shipment": "retrieval",
            "issue_refund": "modification",
            "cancel_order": "modification",
            "update_address": "modification",
            "apply_coupon": "modification",
            "send_email": "communication",
        }
    }, timeout=15)
    print(f"  Status: {resp.status_code}")
    print(f"  Body:   {resp.text[:300]}")

    if resp.status_code == 201:
        api_key = resp.json()["api_key"]
        if test_result("Agent registered", True):
            passed += 1
    elif resp.status_code == 409:
        print("  Agent already exists. Delete from DynamoDB and re-run, or use a different ID.")
        sys.exit(1)
    else:
        test_result("Agent registered", False, resp.text)
        sys.exit(1)

    # ------------------------------------------------------------------
    # TEST 2: Record baseline with 6 retrieval + 6 modification traces
    # ------------------------------------------------------------------
    section("TEST 2: Record baseline with mixed traces (6 retrieval + 6 modification)")

    scenarios = [
        # --- 6 retrieval traces ---
        {"tools_called": ["search_products"], "response_length_words": 35},
        {"tools_called": ["lookup_order"], "response_length_words": 40},
        {"tools_called": ["search_products", "lookup_order"], "response_length_words": 50},
        {"tools_called": ["get_faq"], "response_length_words": 30},
        {"tools_called": ["check_inventory", "track_shipment"], "response_length_words": 45},
        {"tools_called": ["lookup_order", "track_shipment"], "response_length_words": 42},
        # --- 6 modification traces (ensure >50% modification tools in each) ---
        {"tools_called": ["issue_refund"], "response_length_words": 45},
        {"tools_called": ["cancel_order"], "response_length_words": 40},
        {"tools_called": ["update_address"], "response_length_words": 35},
        {"tools_called": ["issue_refund", "cancel_order", "send_email"], "response_length_words": 55},
        {"tools_called": ["cancel_order", "update_address"], "response_length_words": 48},
        {"tools_called": ["apply_coupon", "issue_refund"], "response_length_words": 50},
    ]

    resp = requests.post(
        f"{API_URL}/agents/{AGENT_ID}/baseline",
        json={"scenarios": scenarios},
        headers={"x-flagent-key": api_key},
        timeout=30,
    )
    print(f"  Status: {resp.status_code}")
    result = resp.json() if resp.status_code == 200 else {}
    print(f"  Clusters: {json.dumps(result.get('intent_clusters', {}), indent=4)}")
    print(f"  Min cluster samples: {result.get('min_cluster_samples')}")

    if resp.status_code == 200:
        clusters = result.get("intent_clusters", {})
        has_retrieval = "retrieval" in clusters
        has_modification = "modification" in clusters
        if test_result(
            "Per-intent clusters created",
            has_retrieval and has_modification,
            f"retrieval: {clusters.get('retrieval', {}).get('sample_count', 0)} samples, "
            f"modification: {clusters.get('modification', {}).get('sample_count', 0)} samples",
        ):
            passed += 1
        else:
            failed += 1
    else:
        test_result("Per-intent clusters created", False, resp.text)
        failed += 1

    # ------------------------------------------------------------------
    # TEST 3: Score "3 refunds" — should classify as modification
    # ------------------------------------------------------------------
    section("TEST 3: Score '3 refunds' trace with include_all_clusters=true")

    refund_trace = {
        "tools_called": ["issue_refund", "issue_refund", "issue_refund"],
        "tool_counts": {"issue_refund": 3},
        "response_length_words": 50,
    }

    resp = requests.post(
        f"{API_URL}/score-session",
        json={
            "trace": refund_trace,
            "agent_id": AGENT_ID,
            "include_all_clusters": True,
        },
        headers={"x-flagent-key": api_key},
        timeout=15,
    )
    print(f"  Status: {resp.status_code}")
    result = resp.json() if resp.status_code == 200 else {}
    print(f"  Intent cluster:  {result.get('intent_cluster')}")
    print(f"  Baseline used:   {result.get('baseline_used')}")
    print(f"  Score:           {result.get('score')}")
    print(f"  Classification:  {result.get('classification')}")
    print(f"  Components:      {json.dumps(result.get('components', {}))}")

    all_scores = result.get("all_cluster_scores", {})
    if all_scores:
        print(f"\n  --- All cluster scores for the SAME trace ---")
        for cluster, data in all_scores.items():
            print(f"    {cluster:15s}  score: {data['score']:6.2f}  class: {data['classification']}")

    if resp.status_code == 200:
        intent = result.get("intent_cluster")
        baseline = result.get("baseline_used")
        if test_result(
            "Classified as 'modification'",
            intent == "modification",
            f"intent_cluster={intent}",
        ):
            passed += 1
        else:
            failed += 1

        if test_result(
            "Used modification cluster fingerprint",
            baseline == "modification",
            f"baseline_used={baseline}",
        ):
            passed += 1
        else:
            failed += 1

        # Check that scores differ between clusters
        mod_score = all_scores.get("modification", {}).get("score", -1)
        ret_score = all_scores.get("retrieval", {}).get("score", -1)
        if mod_score >= 0 and ret_score >= 0:
            different = abs(mod_score - ret_score) > 1.0
            if test_result(
                "Different scores against different clusters",
                different,
                f"modification cluster: {mod_score}  |  retrieval cluster: {ret_score}  |  delta: {abs(mod_score - ret_score):.2f}",
            ):
                passed += 1
            else:
                failed += 1
        else:
            test_result("Different scores against different clusters", False, "Could not compare")
            failed += 1
    else:
        test_result("Classified as 'modification'", False, resp.text)
        test_result("Used modification cluster fingerprint", False, "")
        test_result("Different scores against different clusters", False, "")
        failed += 3

    # ------------------------------------------------------------------
    # TEST 4: Score a retrieval trace — should use retrieval cluster
    # ------------------------------------------------------------------
    section("TEST 4: Score retrieval trace — should use retrieval cluster")

    retrieval_trace = {
        "tools_called": ["search_products", "lookup_order"],
        "tool_counts": {"search_products": 1, "lookup_order": 1},
        "response_length_words": 45,
    }

    resp = requests.post(
        f"{API_URL}/score-session",
        json={
            "trace": retrieval_trace,
            "agent_id": AGENT_ID,
        },
        headers={"x-flagent-key": api_key},
        timeout=15,
    )
    print(f"  Status: {resp.status_code}")
    result = resp.json() if resp.status_code == 200 else {}
    print(f"  Intent cluster:  {result.get('intent_cluster')}")
    print(f"  Baseline used:   {result.get('baseline_used')}")
    print(f"  Score:           {result.get('score')}")
    print(f"  Classification:  {result.get('classification')}")

    if resp.status_code == 200:
        intent = result.get("intent_cluster")
        if test_result(
            "Retrieval trace uses retrieval cluster",
            intent == "retrieval",
            f"intent_cluster={intent}, baseline_used={result.get('baseline_used')}",
        ):
            passed += 1
        else:
            failed += 1
    else:
        test_result("Retrieval trace uses retrieval cluster", False, resp.text)
        failed += 1

    # ------------------------------------------------------------------
    # TEST 5: Legacy endpoint still works
    # ------------------------------------------------------------------
    section("TEST 5: Legacy /score-session (no auth, no intent)")

    legacy_trace = {
        "tools_called": ["lookup_order"],
        "tool_counts": {"lookup_order": 1},
        "response_length_words": 40,
    }

    resp = requests.post(
        f"{API_URL}/score-session",
        json={"trace": legacy_trace},
        timeout=15,
    )
    print(f"  Status: {resp.status_code}")
    result = resp.json() if resp.status_code == 200 else {}
    print(f"  Score: {result.get('score')}, Class: {result.get('classification')}")
    # Legacy should NOT have intent_cluster in response
    has_intent = "intent_cluster" in result

    if resp.status_code == 200:
        if test_result(
            "Legacy works, no intent_cluster in response",
            not has_intent,
            f"score={result.get('score')}, class={result.get('classification')}",
        ):
            passed += 1
        else:
            failed += 1
    else:
        test_result("Legacy works", False, resp.text)
        failed += 1

    # ------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------
    total = passed + failed
    section("PHASE 2 VERIFICATION SUMMARY")
    print(f"  Passed: {passed}/{total}")
    print(f"  Failed: {failed}/{total}")
    print(f"  Result: {'✅ ALL TESTS PASSED' if failed == 0 else '❌ SOME TESTS FAILED'}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
