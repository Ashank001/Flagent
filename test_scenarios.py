"""
test_scenarios.py — Local test script

Runs the scenario generator and prints all 50 scenarios for sanity checking.
Also optionally smoke-tests the mock agent with one scenario.

Usage:
    python test_scenarios.py              # generate 50 scenarios
    python test_scenarios.py --agent      # also run one scenario through mock agent
"""

import os
import sys
import json

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv
load_dotenv()

from scenario_generator import generate_scenarios


def main():
    run_agent_test = "--agent" in sys.argv

    print("=" * 60)
    print("  PS-4.1 — Scenario Generator Test")
    print("  Model: gemini-3.6-flash (free tier)")
    print("  Rate limit: ~4.5s between calls, 20s backoff on 429")
    print("=" * 60)

    # ---- Generate scenarios ----
    scenarios = generate_scenarios()

    print("\n" + "=" * 60)
    print(f"  ✅  {len(scenarios)} scenarios generated")
    print("=" * 60)

    for i, s in enumerate(scenarios, 1):
        print(f"  {i:2d}. {s}")

    # ---- Save to file ----
    output_path = os.path.join(os.path.dirname(__file__), "scenarios_output.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scenarios, f, indent=2, ensure_ascii=False)
    print(f"\n💾  Saved to {output_path}")

    # ---- Quick quality stats ----
    intent_keywords = {
        "lookup": ["order", "status", "track", "where", "check", "find"],
        "refund": ["refund", "money back", "return", "reimburse", "credit"],
        "email": ["email", "send", "mail", "receipt", "confirmation"],
        "address": ["address", "shipping", "deliver", "move", "change address"],
    }
    counts = {k: 0 for k in intent_keywords}
    for s in scenarios:
        s_lower = s.lower()
        for intent, keywords in intent_keywords.items():
            if any(kw in s_lower for kw in keywords):
                counts[intent] += 1

    print(f"\n📊  Intent distribution (keyword-based estimate):")
    for intent, count in counts.items():
        bar = "█" * count
        print(f"     {intent:10s} {count:2d}  {bar}")

    # ---- Optional: smoke-test the mock agent ----
    if run_agent_test and scenarios:
        print("\n" + "=" * 60)
        print("  🤖  Mock Agent Smoke Test")
        print("=" * 60)

        from mock_agent import run_session

        test_scenario = scenarios[0]
        print(f"\n  User: {test_scenario}")

        result = run_session(test_scenario)

        print(f"  Agent: {result['response_text'][:400]}")
        print(f"\n  Tool calls: {result['tool_call_count']}")
        print(f"  Tool sequence: {result['tool_sequence']}")
        print(f"  Response length: {result['response_length']} chars")

    print("\n✅  Done.")


if __name__ == "__main__":
    main()
