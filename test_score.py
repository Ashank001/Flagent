import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from deviation_scorer import score_session

with open("baseline_output.json", "r", encoding="utf-8") as f:
    baseline = json.load(f)

fingerprint = baseline["fingerprint"]

trace1 = {
    "tools_called": ["lookup_order"],
    "tool_counts": {"lookup_order": 1},
    "response_length_words": 35,
}

trace2 = {
    "tools_called": ["lookup_order", "send_email", "update_address"],
    "tool_counts": {"lookup_order": 1, "send_email": 1, "update_address": 1},
    "response_length_words": 70,
}

trace3 = {
    "tools_called": ["lookup_order"]*4 + ["issue_refund"]*4 + ["send_email"]*4,
    "tool_counts": {"lookup_order": 4, "issue_refund": 4, "send_email": 4},
    "response_length_words": 85,
}

print("Test 1:", score_session(trace1, fingerprint))
print("Test 2:", score_session(trace2, fingerprint))
print("Test 3:", score_session(trace3, fingerprint))
