"""
test_calibration.py — Calibration Test

Scores every baseline session (from baseline_output.json) against the
aggregate fingerprint. Verifies the scoring formula produces a sensible
distribution:
  - Most baseline scenarios should score < 30 (normal)
  - A few may land 30-50 (borderline warning — natural variance)
  - None should be > 70 (alert)

This test does NOT make any Gemini API calls — it uses the already-recorded
session data.

Usage:
    python test_calibration.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv()

# pyrefly: ignore [missing-import]
from deviation_scorer import score_session


def main():
    baseline_path = os.path.join(
        os.path.dirname(__file__), "baseline_output.json"
    )
    if not os.path.exists(baseline_path):
        print("ERROR: baseline_output.json not found.")
        print("Run baseline_recorder.py first.")
        sys.exit(1)

    with open(baseline_path, "r", encoding="utf-8") as f:
        baseline = json.load(f)

    fingerprint = baseline["fingerprint"]
    session_results = baseline["session_results"]

    print("=" * 78)
    print("  Calibration Test -- Scoring baseline scenarios against fingerprint")
    print("=" * 78)
    print(f"\n  Fingerprint summary:")
    print(f"    tool_frequency:      {fingerprint['tool_frequency']}")
    print(f"    avg_response_length: {fingerprint['avg_response_length']} words")
    print(f"    std_response_length: {fingerprint['std_response_length']} words")
    print(f"    common_bigrams:      {len(fingerprint['common_bigrams'])} unique pairs")
    print()

    # Header
    print(f"  {'#':>3}  {'SCORE':>6}  {'CLASS':>8}  "
          f"{'COS':>5}  {'BIG':>5}  {'LEN':>5}  "
          f"{'TC':>2}  {'WD':>3}  SCENARIO")
    print(f"  {'---':>3}  {'------':>6}  {'--------':>8}  "
          f"{'-----':>5}  {'-----':>5}  {'-----':>5}  "
          f"{'--':>2}  {'---':>3}  {'--------'}")

    scores = []
    for i, result in enumerate(session_results):
        trace = {
            "tools_called": result["tools_called"],
            "tool_counts": result["tool_counts"],
            "response_length_words": result["response_length_words"],
        }
        s = score_session(trace, fingerprint)
        scores.append(s)

        label = s["classification"].upper()
        c = s["components"]
        tc = result["tool_call_count"]
        wd = result["response_length_words"]
        scenario_short = result["scenario"][:42]

        # Color-code for readability (ANSI)
        if s["classification"] == "normal":
            tag = "  "
        elif s["classification"] == "warning":
            tag = "* "
        else:
            tag = "! "

        print(
            f"{tag}{i + 1:3d}  {s['score']:6.1f}  {label:>8s}  "
            f"{c['cosine_distance']:5.1f}  {c['bigram_novelty']:5.1f}  "
            f"{c['length_zscore']:5.1f}  "
            f"{tc:2d}  {wd:3d}  {scenario_short}..."
        )

    # ---- Summary ----
    normal_count = sum(1 for s in scores if s["classification"] == "normal")
    warning_count = sum(1 for s in scores if s["classification"] == "warning")
    alert_count = sum(1 for s in scores if s["classification"] == "alert")
    avg_score = sum(s["score"] for s in scores) / len(scores) if scores else 0
    max_score = max(s["score"] for s in scores) if scores else 0
    min_score = min(s["score"] for s in scores) if scores else 0

    print(f"\n  {'=' * 72}")
    print(f"  DISTRIBUTION SUMMARY")
    print(f"  {'=' * 72}")
    print(f"    Normal  (< 30):   {normal_count:3d} / {len(scores)}")
    print(f"    Warning (30-70):  {warning_count:3d} / {len(scores)}")
    print(f"    Alert   (> 70):   {alert_count:3d} / {len(scores)}")
    print(f"    Average score:    {avg_score:.1f}")
    print(f"    Score range:      {min_score:.1f} -- {max_score:.1f}")

    # ---- Pass/fail criteria ----
    print(f"\n  CALIBRATION CHECKS:")
    checks_passed = 0
    total_checks = 3

    # Check 1: majority normal
    pct_normal = normal_count / len(scores) * 100 if scores else 0
    ok1 = pct_normal >= 70
    status1 = "PASS" if ok1 else "FAIL"
    print(f"    [{status1}] >= 70% normal:  {pct_normal:.0f}%")
    checks_passed += int(ok1)

    # Check 2: at least a few warnings (natural variance)
    ok2 = warning_count >= 2
    status2 = "PASS" if ok2 else "INFO"
    print(f"    [{status2}] >= 2 warnings:  {warning_count}")
    if ok2:
        checks_passed += 1
    else:
        # Not a hard fail — just informational
        checks_passed += 1
        print(f"          (Fewer warnings than expected — scoring may be lenient.)")

    # Check 3: no alerts on baseline data
    ok3 = alert_count == 0
    status3 = "PASS" if ok3 else "FAIL"
    print(f"    [{status3}] 0 alerts:       {alert_count}")
    checks_passed += int(ok3)

    print(f"\n    Result: {checks_passed}/{total_checks} checks passed.")

    if pct_normal < 70 or alert_count > 0:
        print("\n    >> ADJUSTMENT NEEDED: Consider tuning weights in deviation_scorer.py")

    print()


if __name__ == "__main__":
    main()
