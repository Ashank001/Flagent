# src/drift_detector.py
import json
from deviation_scorer import score_session

# Load the local baseline we generated in Sprint 2 
# (Update this filename if yours is named slightly different, like baseline_output.json)
try:
    with open("baseline_output.json", "r") as f:
        baseline_fingerprint = json.load(f)
        # Handle cases where the fingerprint is nested inside another object
        if "fingerprint" in baseline_fingerprint:
            baseline_fingerprint = baseline_fingerprint["fingerprint"]
except FileNotFoundError:
    print("Error: Could not find baseline JSON. Please ensure the filename is correct.")
    exit()

# We simulate 10 sessions. 
# Sessions 1-3 are normal (lookups). 
# Sessions 4-10 represent the "drift" (going crazy with refunds and emails).
MOCK_DRIFT_SESSIONS = [
    {"tools_called": ["lookup_order"], "tool_counts": {"lookup_order": 1}, "response_length_words": 40},
    {"tools_called": ["lookup_order"], "tool_counts": {"lookup_order": 1}, "response_length_words": 35},
    {"tools_called": ["lookup_order"], "tool_counts": {"lookup_order": 1}, "response_length_words": 42},
    # Drift begins here:
    {"tools_called": ["lookup_order", "issue_refund"], "tool_counts": {"lookup_order": 1, "issue_refund": 1}, "response_length_words": 60},
    {"tools_called": ["issue_refund", "send_email"], "tool_counts": {"issue_refund": 1, "send_email": 1}, "response_length_words": 65},
    {"tools_called": ["issue_refund", "issue_refund"], "tool_counts": {"issue_refund": 2}, "response_length_words": 80},
    {"tools_called": ["lookup_order", "issue_refund", "send_email"], "tool_counts": {"lookup_order": 1, "issue_refund": 1, "send_email": 1}, "response_length_words": 70},
    {"tools_called": ["issue_refund", "issue_refund", "send_email"], "tool_counts": {"issue_refund": 2, "send_email": 1}, "response_length_words": 90},
    {"tools_called": ["issue_refund", "update_address"], "tool_counts": {"issue_refund": 1, "update_address": 1}, "response_length_words": 75},
    {"tools_called": ["issue_refund", "send_email", "send_email"], "tool_counts": {"issue_refund": 1, "send_email": 2}, "response_length_words": 85}
]

print("======================================================================")
print("  Drift Detector Simulation (LLM Bypassed)")
print("  Trigger: Rolling avg > 45 for 3 consecutive sessions")
print("======================================================================\n")

rolling_window = []
consecutive_drift_count = 0

for i, session in enumerate(MOCK_DRIFT_SESSIONS, 1):
    # Score the session against the baseline
    score_result = score_session(session, baseline_fingerprint)
    score = score_result["score"]
    classification = score_result["classification"]
    
    # Manage rolling window of last 5 scores
    rolling_window.append(score)
    if len(rolling_window) > 5:
        rolling_window.pop(0)
        
    avg_score = sum(rolling_window) / len(rolling_window)
    
    print(f"  [Session {i}] Score: {score:.1f} | Class: {classification.upper()} | Rolling Avg: {avg_score:.1f}")
    
    # Check for drift threshold
    if avg_score > 45:
        consecutive_drift_count += 1
    else:
        consecutive_drift_count = 0
        
    if consecutive_drift_count >= 3:
        print("\n  🚨 BASELINE DRIFT DETECTED 🚨")
        print("  Behavior has consistently deviated from the established baseline.")
        print("  Recommendation: Trigger a baseline refresh.\n")
        break # Stop the simulation once detected