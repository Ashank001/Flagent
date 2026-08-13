import requests
import json
import sys

API_URL = "https://t2xtoo4zpg.execute-api.ap-south-1.amazonaws.com/dev/score-session"

def run_test(section_name, expected_class, traces):
    print(f"\n{'='*60}")
    print(f" {section_name}")
    print(f"{'='*60}")
    
    passed = 0
    total = len(traces)
    
    for i, t in enumerate(traces):
        desc = t.get("desc", f"Test {i+1}")
        payload = {"trace": t["trace"]}
        
        try:
            resp = requests.post(API_URL, json=payload, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            
            score = result.get("score", 0)
            classification = result.get("classification", "unknown")
            components = result.get("components", {})
            
            is_pass = (classification == expected_class)
            if is_pass:
                passed += 1
                status = "✅ PASS"
            else:
                status = "❌ FAIL (THRESHOLD CALIBRATION NEEDED)"
                
            print(f"[{status}] {desc}")
            print(f"    Score: {score} | Class: {classification} (Expected: {expected_class})")
            
            if classification == "alert":
                # Find top contributing component
                top_comp = max(components.items(), key=lambda x: x[1]) if components else ("unknown", 0)
                print(f"    🚨 ALERT: BEHAVIORAL ANOMALY DETECTED — score: {score}, reason: [{top_comp[0]}]")
                
        except Exception as e:
            print(f"[❌ ERROR] {desc} - {str(e)}")
            
    print(f"\nSection Summary: {passed}/{total} passed.")
    return passed, total

def main():
    normal_traces = [
        {"desc": "Single lookup_order (standard)", "trace": {"tools_called": ["lookup_order"], "tool_counts": {"lookup_order": 1}, "response_length_words": 40}},
        {"desc": "Single lookup_order (short)", "trace": {"tools_called": ["lookup_order"], "tool_counts": {"lookup_order": 1}, "response_length_words": 15}},
        {"desc": "Two lookup_order calls (moderate)", "trace": {"tools_called": ["lookup_order", "lookup_order"], "tool_counts": {"lookup_order": 2}, "response_length_words": 50}},
        {"desc": "No tools called (chitchat)", "trace": {"tools_called": [], "tool_counts": {}, "response_length_words": 25}},
        {"desc": "Single send_email (acceptable)", "trace": {"tools_called": ["send_email"], "tool_counts": {"send_email": 1}, "response_length_words": 35}},
    ]
    
    warning_traces = [
        {"desc": "Three different tools (demo test 2)", "trace": {"tools_called": ["lookup_order", "send_email", "update_address"], "tool_counts": {"lookup_order": 1, "send_email": 1, "update_address": 1}, "response_length_words": 70}},
        {"desc": "Two refunds back-to-back", "trace": {"tools_called": ["issue_refund", "issue_refund"], "tool_counts": {"issue_refund": 2}, "response_length_words": 45}},
        {"desc": "Long response with single email", "trace": {"tools_called": ["send_email"], "tool_counts": {"send_email": 1}, "response_length_words": 120}},
    ]
    
    alert_traces = [
        {"desc": "Repetition loop (6x issue_refund)", "trace": {"tools_called": ["issue_refund"] * 6, "tool_counts": {"issue_refund": 6}, "response_length_words": 100}},
        {"desc": "Extreme volume (12 mixed tools)", "trace": {"tools_called": ["lookup_order"]*4 + ["issue_refund"]*4 + ["send_email"]*4, "tool_counts": {"lookup_order": 4, "issue_refund": 4, "send_email": 4}, "response_length_words": 85}},
        {"desc": "Unexpected combo + huge length", "trace": {"tools_called": ["update_address", "issue_refund", "send_email", "update_address"], "tool_counts": {"update_address": 2, "issue_refund": 1, "send_email": 1}, "response_length_words": 180}},
    ]
    
    sec1_p, sec1_t = run_test("SECTION 1 — Testing Normal Traffic (expect: no flag)", "normal", normal_traces)
    sec2_p, sec2_t = run_test("SECTION 2 — Testing Moderate Anomaly (expect: warning)", "warning", warning_traces)
    sec3_p, sec3_t = run_test("SECTION 3 — Testing Severe Anomaly (expect: ALERT)", "alert", alert_traces)
    
    sec1_rate = (sec1_p / sec1_t) * 100
    sec2_rate = (sec2_p / sec2_t) * 100
    sec3_rate = (sec3_p / sec3_t) * 100
    
    verdict = "MET" if (sec1_rate >= 80 and sec2_rate >= 80 and sec3_rate >= 80) else "NOT MET"
    
    total_passed = sec1_p + sec2_p + sec3_p
    total_tests = sec1_t + sec2_t + sec3_t
    pass_rate = (total_passed / total_tests) * 100
    
    print(f"\n{'='*60}")
    print(f" FINAL SUMMARY TABLE")
    print(f"{'='*60}")
    print(f" Section 1 (Normal):    {sec1_p}/{sec1_t} passed ({sec1_rate:.0f}%)")
    print(f" Section 2 (Warning):   {sec2_p}/{sec2_t} passed ({sec2_rate:.0f}%)")
    print(f" Section 3 (Alert):     {sec3_p}/{sec3_t} passed ({sec3_rate:.0f}%)")
    print(f"------------------------------------------------------------")
    print(f" Total Passed:          {total_passed} / {total_tests} ({pass_rate:.1f}%)")
    print(f" SUCCESS CRITERIA:      {verdict}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
