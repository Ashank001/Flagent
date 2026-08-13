"""
agent_interceptor.py — Governance Middleware for AI Agent Tool Calls

This module demonstrates the integration pattern for connecting any production
AI agent to the governance layer. In a real deployment, this wrapper (or
equivalent middleware) would sit between an agent's tool-calling loop and its
response delivery, sending behavioral telemetry to the governance API on every
turn.

The key function `governed_agent_call()` wraps any agent function, automatically
extracting its tool-call trace, posting it to the scoring API, and acting on
the classification before returning the response to the caller.

Usage:
    from agent_interceptor import governed_agent_call
    from mock_agent import run_session

    response = governed_agent_call(
        user_message="Check order #12345",
        agent_fn=run_session,
        agent_id="my-agent-v1"
    )
"""

import json
import os
import sys
import time
import requests
from collections import Counter

# Add src/ to path so mock_agent can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_URL = "https://t2xtoo4zpg.execute-api.ap-south-1.amazonaws.com/dev"
SCORE_ENDPOINT = f"{API_URL}/score-session"


# ---------------------------------------------------------------------------
# Core interceptor
# ---------------------------------------------------------------------------

def governed_agent_call(user_message: str, agent_fn, agent_id: str = "default-agent") -> dict:
    """
    Wrap a call to an agent function with governance scoring.

    This function:
    1. Calls agent_fn(user_message) to get the agent's response + tool trace
    2. POSTs the trace to the governance API's /score-session endpoint
    3. Logs the classification and flags alerts before returning

    Parameters:
        user_message: The user's input message
        agent_fn:     A callable that accepts a string and returns a dict with
                      keys: response_text, tool_sequence, tool_calls, response_length
        agent_id:     Identifier for the agent (for logging/tracking)

    Returns:
        dict with keys:
          - response_text:    The agent's original response
          - governance:       Dict with score, classification, components, session_id
          - trace:            The tool-call trace sent to the API
    """

    # ---- Step 1: Call the agent ----
    print(f"\n{'─'*60}")
    print(f"📨 User Message: {user_message}")
    print(f"{'─'*60}")

    agent_result = agent_fn(user_message)

    response_text = agent_result.get("response_text", "")
    tool_sequence = agent_result.get("tool_sequence", [])
    response_length_words = len(response_text.split())

    # Build tool_counts from sequence
    tool_counts = dict(Counter(tool_sequence))

    print(f"🤖 Agent responded ({response_length_words} words, {len(tool_sequence)} tool calls)")
    if tool_sequence:
        print(f"   Tools used: {' → '.join(tool_sequence)}")

    # ---- Step 2: Build trace and POST to governance API ----
    trace = {
        "tools_called": tool_sequence,
        "tool_counts": tool_counts,
        "response_length_words": response_length_words,
    }

    governance_result = None
    try:
        print(f"📡 Sending trace to governance API...")
        resp = requests.post(
            SCORE_ENDPOINT,
            json={"trace": trace},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        governance_result = resp.json()

        score = governance_result.get("score", -1)
        classification = governance_result.get("classification", "unknown")
        session_id = governance_result.get("session_id", "N/A")
        components = governance_result.get("components", {})

        # ---- Step 3: Act on classification ----
        if classification == "alert":
            print(f"\n🚨 GOVERNANCE ALERT: session flagged as anomalous, score: {score}")
            print(f"   Session ID: {session_id}")
            print(f"   Components: cosine={components.get('cosine_distance', '?')}, "
                  f"bigram={components.get('bigram_novelty', '?')}, "
                  f"zscore={components.get('length_zscore', '?')}")
            print(f"   ⚠️  In production, this would trigger: incident ticket, "
                  f"supervisor review, or response blocking")
        elif classification == "warning":
            print(f"⚠️  GOVERNANCE WARNING: unusual behavior detected, score: {score}")
            print(f"   Session ID: {session_id}")
        else:
            print(f"✅ GOVERNANCE: normal behavior, score: {score}")
            print(f"   Session ID: {session_id}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Governance API error: {e}")
        governance_result = {"error": str(e), "score": -1, "classification": "api_error"}

    # ---- Always return the agent's original response ----
    return {
        "response_text": response_text,
        "governance": governance_result,
        "trace": trace,
    }


# ---------------------------------------------------------------------------
# Demo: end-to-end flow with 3 different messages
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    from mock_agent import run_session

    print("=" * 60)
    print("🛡️  AGENT INTERCEPTOR — End-to-End Demo")
    print("=" * 60)
    print(f"API Endpoint: {SCORE_ENDPOINT}")
    print(f"Agent: mock-customer-support (mock_agent.py)")
    print("=" * 60)

    # --- Test 1: Normal request (single tool call) ---
    print("\n\n" + "█" * 60)
    print("█  TEST 1: NORMAL REQUEST — Single order lookup")
    print("█" * 60)

    result1 = governed_agent_call(
        user_message="Can you check the status of my order ORD-54321?",
        agent_fn=run_session,
        agent_id="mock-customer-support",
    )
    print(f"\n💬 Agent Response (truncated): {result1['response_text'][:200]}...")

    # Rate limit pause between Gemini calls
    print("\n⏳ Waiting 5s (Gemini rate limit)...")
    time.sleep(5)

    # --- Test 2: Multi-tool request ---
    print("\n\n" + "█" * 60)
    print("█  TEST 2: MULTI-TOOL — Order check + email + address update")
    print("█" * 60)

    result2 = governed_agent_call(
        user_message=(
            "Hi, I need help with order ORD-99887. Can you look it up, "
            "then email me the status at customer@example.com, and also "
            "update the shipping address to 456 Oak Ave, Austin TX 78701?"
        ),
        agent_fn=run_session,
        agent_id="mock-customer-support",
    )
    print(f"\n💬 Agent Response (truncated): {result2['response_text'][:200]}...")

    # Rate limit pause
    print("\n⏳ Waiting 5s (Gemini rate limit)...")
    time.sleep(5)

    # --- Test 3: Unusual heavy request ---
    print("\n\n" + "█" * 60)
    print("█  TEST 3: HEAVY — Multiple refunds + lookups (potential alert)")
    print("█" * 60)

    result3 = governed_agent_call(
        user_message=(
            "I need refunds on ALL of these orders right now: ORD-001 for $50, "
            "ORD-002 for $75, ORD-003 for $120, and ORD-004 for $200. "
            "Look up each one first. Also send confirmation emails to "
            "angry-customer@example.com for each refund."
        ),
        agent_fn=run_session,
        agent_id="mock-customer-support",
    )
    print(f"\n💬 Agent Response (truncated): {result3['response_text'][:200]}...")

    # --- Summary ---
    print("\n\n" + "=" * 60)
    print("📊 DEMO SUMMARY")
    print("=" * 60)
    for i, result in enumerate([result1, result2, result3], 1):
        gov = result["governance"]
        trace = result["trace"]
        score = gov.get("score", "N/A")
        cls = gov.get("classification", "N/A")
        tools = trace.get("tools_called", [])
        print(f"\n  Test {i}:")
        print(f"    Tools:          {' → '.join(tools) if tools else '(none)'}")
        print(f"    Tool count:     {len(tools)}")
        print(f"    Anomaly Score:  {score}")
        print(f"    Classification: {cls}")

    print("\n" + "=" * 60)
    print("✅ Demo complete. All 3 sessions scored by the live governance API.")
    print("=" * 60)
