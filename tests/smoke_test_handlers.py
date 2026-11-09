"""Quick smoke test of the refactored handlers against STORAGE=memory."""
import sys
import os
import json

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))
os.environ["STORAGE"] = "memory"

from storage.factory import reset_storage
reset_storage()

from score_session.score_session import handler as score_handler
from register_agent.register_agent import handler as register_handler
from record_baseline.record_baseline import handler as baseline_handler

print("=" * 60)
print("  SMOKE TEST: Handlers with STORAGE=memory")
print("=" * 60)

passed = 0
failed = 0

# TEST 1: Legacy score-session (no auth)
print("\n--- TEST 1: Legacy /score-session ---")
event = {
    "body": json.dumps({
        "trace": {
            "tools_called": ["lookup_order"],
            "tool_counts": {"lookup_order": 1},
            "response_length_words": 40
        }
    }),
    "headers": {}
}
result = score_handler(event, None)
body = json.loads(result["body"])
print(f"  Status: {result['statusCode']}")
print(f"  Score: {body.get('score')}, Class: {body.get('classification')}")
if result["statusCode"] == 200 and body.get("classification") == "normal":
    print("  PASS")
    passed += 1
else:
    print("  FAIL")
    failed += 1

# TEST 2: Legacy alert
print("\n--- TEST 2: Legacy alert ---")
event2 = {
    "body": json.dumps({
        "trace": {
            "tools_called": ["issue_refund"] * 6,
            "tool_counts": {"issue_refund": 6},
            "response_length_words": 100
        }
    }),
    "headers": {}
}
result2 = score_handler(event2, None)
body2 = json.loads(result2["body"])
print(f"  Score: {body2.get('score')}, Class: {body2.get('classification')}")
if body2.get("classification") == "alert":
    print("  PASS")
    passed += 1
else:
    print("  FAIL")
    failed += 1

# TEST 3: Register agent
print("\n--- TEST 3: Register agent ---")
reg_event = {
    "body": json.dumps({
        "agent_id": "test-smoke",
        "name": "Smoke Agent",
        "tool_categories": {"lookup": "retrieval", "refund": "modification"}
    }),
    "headers": {}
}
reg_result = register_handler(reg_event, None)
reg_body = json.loads(reg_result["body"])
print(f"  Status: {reg_result['statusCode']}")
print(f"  Agent: {reg_body.get('agent_id')}")
api_key = reg_body.get("api_key", "")
print(f"  Key starts with: {api_key[:12]}...")
if reg_result["statusCode"] == 201 and api_key.startswith("fgnt_"):
    print("  PASS")
    passed += 1
else:
    print("  FAIL")
    failed += 1

# TEST 4: Record baseline (BYO scenarios)
print("\n--- TEST 4: Record baseline ---")
bl_event = {
    "body": json.dumps({
        "scenarios": [
            {"tools_called": ["lookup"], "tool_counts": {"lookup": 1}, "response_length_words": 40},
            {"tools_called": ["lookup"], "tool_counts": {"lookup": 1}, "response_length_words": 35},
            {"tools_called": ["refund"], "tool_counts": {"refund": 1}, "response_length_words": 45},
            {"tools_called": ["lookup", "refund"], "tool_counts": {"lookup": 1, "refund": 1}, "response_length_words": 55},
            {"tools_called": ["lookup"], "tool_counts": {"lookup": 1}, "response_length_words": 38},
        ]
    }),
    "headers": {"x-flagent-key": api_key},
    "pathParameters": {"agent_id": "test-smoke"},
}
bl_result = baseline_handler(bl_event, None)
bl_body = json.loads(bl_result["body"])
print(f"  Status: {bl_result['statusCode']}")
print(f"  Fingerprint: {bl_body.get('fingerprint', {}).get('tool_frequency', {})}")
if bl_result["statusCode"] == 200:
    print("  PASS")
    passed += 1
else:
    print(f"  FAIL: {bl_body}")
    failed += 1

# TEST 5: Authenticated score
print("\n--- TEST 5: Authenticated score ---")
auth_event = {
    "body": json.dumps({
        "trace": {
            "tools_called": ["lookup"],
            "tool_counts": {"lookup": 1},
            "response_length_words": 40
        },
        "agent_id": "test-smoke"
    }),
    "headers": {"x-flagent-key": api_key},
}
auth_result = score_handler(auth_event, None)
auth_body = json.loads(auth_result["body"])
print(f"  Status: {auth_result['statusCode']}")
print(f"  Score: {auth_body.get('score')}, Class: {auth_body.get('classification')}")
print(f"  Intent: {auth_body.get('intent_cluster')}, Baseline: {auth_body.get('baseline_used')}")
if auth_result["statusCode"] == 200:
    print("  PASS")
    passed += 1
else:
    print(f"  FAIL: {auth_body}")
    failed += 1

# TEST 6: 401 on bad key
print("\n--- TEST 6: 401 on bad key ---")
bad_event = {
    "body": json.dumps({
        "trace": {"tools_called": ["lookup"], "tool_counts": {"lookup": 1}, "response_length_words": 40},
        "agent_id": "test-smoke"
    }),
    "headers": {"x-flagent-key": "fgnt_FAKE_KEY"},
}
bad_result = score_handler(bad_event, None)
print(f"  Status: {bad_result['statusCode']}")
if bad_result["statusCode"] == 401:
    print("  PASS")
    passed += 1
else:
    print("  FAIL")
    failed += 1

# TEST 7: Duplicate register
print("\n--- TEST 7: Duplicate register returns 409 ---")
dup_result = register_handler(reg_event, None)
print(f"  Status: {dup_result['statusCode']}")
if dup_result["statusCode"] == 409:
    print("  PASS")
    passed += 1
else:
    print("  FAIL")
    failed += 1

print(f"\n{'=' * 60}")
print(f"  RESULTS: {passed}/{passed + failed} passed")
print(f"{'=' * 60}")

sys.exit(0 if failed == 0 else 1)

