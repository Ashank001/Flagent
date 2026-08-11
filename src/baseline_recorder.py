"""
baseline_recorder.py — Behavioral Baseline Recorder

Takes the 50 synthetic scenarios, runs each through the mock agent (via
mock_agent.run_session), and records per-session behavioural metrics.
Aggregates into a single fingerprint and saves to DynamoDB + local JSON.

Fingerprint schema:
  - tool_frequency:      {tool_name: avg calls per session}
  - common_bigrams:      {"toolA->toolB": count} for consecutive tool calls
  - avg_response_length: float (words)
  - std_response_length: float (words)

Usage:
    python src/baseline_recorder.py                          # default agent_id
    python src/baseline_recorder.py --agent-id my-agent-v2   # custom agent_id
"""

import json
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import boto3
from botocore.exceptions import ClientError
from mock_agent import run_session


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------

def _ensure_table_exists(table_name: str, region: str) -> None:
    """Create AgentBaselines table if it doesn't exist."""
    dynamodb = boto3.client("dynamodb", region_name=region)
    try:
        dynamodb.describe_table(TableName=table_name)
        print(f"  [dynamo] Table '{table_name}' already exists.")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"  [dynamo] Creating table '{table_name}' ...")
            dynamodb.create_table(
                TableName=table_name,
                KeySchema=[{"AttributeName": "agent_id", "KeyType": "HASH"}],
                AttributeDefinitions=[
                    {"AttributeName": "agent_id", "AttributeType": "S"}
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            dynamodb.get_waiter("table_exists").wait(TableName=table_name)
            print(f"  [dynamo] Table '{table_name}' created.")
        else:
            raise


def _save_fingerprint_to_dynamo(
    agent_id: str, fingerprint: dict, scenario_count: int
) -> None:
    """Write the fingerprint to the AgentBaselines DynamoDB table."""
    region = os.environ.get("AWS_REGION", "ap-south-1")
    table_name = os.environ.get("BASELINES_TABLE", "AgentBaselines")

    _ensure_table_exists(table_name, region)

    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    # DynamoDB can't store Python floats — round-trip through JSON → Decimal
    item = json.loads(
        json.dumps(
            {
                "agent_id": agent_id,
                "fingerprint": fingerprint,
                "scenario_count": scenario_count,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        parse_float=Decimal,
    )
    table.put_item(Item=item)
    print(f"  [dynamo] Saved fingerprint for '{agent_id}' to '{table_name}'.")


# ---------------------------------------------------------------------------
# Fingerprint aggregation
# ---------------------------------------------------------------------------

def _aggregate_fingerprint(session_results: list[dict]) -> dict:
    """
    Aggregate individual session results into a single behavioural fingerprint.

    Returns:
        {
            "tool_frequency":      {tool_name: avg_calls_per_session},
            "common_bigrams":      {"toolA->toolB": count},
            "avg_response_length": float,
            "std_response_length": float,
        }
    """
    n = len(session_results)
    if n == 0:
        raise ValueError("No session results to aggregate.")

    # --- Tool frequency: average calls per session for each tool ---
    tool_totals: Counter = Counter()
    all_tools: set[str] = set()
    for result in session_results:
        for tool, count in result["tool_counts"].items():
            tool_totals[tool] += count
            all_tools.add(tool)

    tool_frequency = {
        tool: round(tool_totals[tool] / n, 4) for tool in sorted(all_tools)
    }

    # --- Common bigrams: consecutive tool-call pairs across all sessions ---
    bigram_counts: Counter = Counter()
    for result in session_results:
        seq = result["tools_called"]
        for i in range(len(seq) - 1):
            bigram_key = f"{seq[i]}->{seq[i + 1]}"
            bigram_counts[bigram_key] += 1

    common_bigrams = dict(bigram_counts.most_common())

    # --- Response length stats (in words) ---
    lengths = [r["response_length_words"] for r in session_results]
    avg_length = sum(lengths) / n
    variance = sum((l - avg_length) ** 2 for l in lengths) / n
    std_length = math.sqrt(variance)

    return {
        "tool_frequency": tool_frequency,
        "common_bigrams": common_bigrams,
        "avg_response_length": round(avg_length, 2),
        "std_response_length": round(std_length, 2),
    }


# ---------------------------------------------------------------------------
# Main recorder
# ---------------------------------------------------------------------------

def run_baseline(
    scenarios_path: str, agent_id: str = "mock-customer-support"
) -> dict:
    """
    Run all scenarios through the mock agent and build a behavioural baseline.

    1. Load scenarios from JSON file
    2. Run each through mock_agent.run_session() (rate-limited)
    3. Record per-session metrics
    4. Aggregate into fingerprint
    5. Save to DynamoDB + local JSON

    Returns the full baseline output dict.
    """
    # Load scenarios
    with open(scenarios_path, "r", encoding="utf-8") as f:
        scenarios = json.load(f)

    print(f"\n{'=' * 60}")
    print(f"  Baseline Recorder — {len(scenarios)} scenarios")
    print(f"  Agent ID: {agent_id}")
    print(f"{'=' * 60}")

    # Check for partial progress (resume support)
    progress_path = os.path.join(
        os.path.dirname(scenarios_path), "baseline_progress.json"
    )
    session_results: list[dict] = []
    start_idx = 0

    if os.path.exists(progress_path):
        with open(progress_path, "r", encoding="utf-8") as f:
            progress = json.load(f)
        if progress.get("agent_id") == agent_id:
            session_results = progress.get("session_results", [])
            start_idx = len(session_results)
            print(f"  Resuming from scenario {start_idx + 1} (found progress file).")

    # Run each scenario
    start_time = time.time()
    for i in range(start_idx, len(scenarios)):
        scenario = scenarios[i]
        print(f"\n  [{i + 1:2d}/{len(scenarios)}] {scenario[:65]}...")

        try:
            result = run_session(scenario)
        except Exception as exc:
            print(f"    ERROR: {exc}")
            print(f"    Saving progress and stopping.")
            _save_progress(progress_path, agent_id, session_results)
            raise

        word_count = len(result["response_text"].split())

        session_record = {
            "scenario": scenario,
            "tools_called": result["tool_sequence"],
            "tool_call_count": result["tool_call_count"],
            "tool_counts": dict(Counter(result["tool_sequence"])),
            "response_length_words": word_count,
            "response_text": result["response_text"][:500],  # truncate for storage
        }
        session_results.append(session_record)

        # Print per-session summary
        tools_str = ", ".join(result["tool_sequence"]) if result["tool_sequence"] else "(none)"
        print(f"    Tools: [{tools_str}]  |  Words: {word_count}")

        # Save progress every 5 scenarios
        if (i + 1) % 5 == 0:
            _save_progress(progress_path, agent_id, session_results)

    elapsed = time.time() - start_time
    print(f"\n  All {len(scenarios)} scenarios complete in {elapsed:.0f}s.")

    # Aggregate fingerprint
    fingerprint = _aggregate_fingerprint(session_results)

    print(f"\n  --- Fingerprint ---")
    print(f"  tool_frequency:      {fingerprint['tool_frequency']}")
    print(f"  avg_response_length: {fingerprint['avg_response_length']} words")
    print(f"  std_response_length: {fingerprint['std_response_length']} words")
    print(f"  common_bigrams:      {len(fingerprint['common_bigrams'])} unique pairs")
    for bigram, count in list(fingerprint["common_bigrams"].items())[:10]:
        print(f"    {bigram}: {count}")

    # Save full output locally
    output = {
        "agent_id": agent_id,
        "fingerprint": fingerprint,
        "session_results": session_results,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario_count": len(scenarios),
    }
    output_path = os.path.join(
        os.path.dirname(scenarios_path), "baseline_output.json"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved baseline to {output_path}")

    # Save fingerprint to DynamoDB
    try:
        _save_fingerprint_to_dynamo(agent_id, fingerprint, len(scenarios))
    except Exception as exc:
        print(f"  WARNING: DynamoDB save failed: {exc}")
        print(f"  Fingerprint is still saved locally in {output_path}")

    # Clean up progress file
    if os.path.exists(progress_path):
        os.remove(progress_path)

    return output


def _save_progress(path: str, agent_id: str, session_results: list[dict]) -> None:
    """Save incremental progress so we can resume on failure."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"agent_id": agent_id, "session_results": session_results},
            f,
            ensure_ascii=False,
        )
    print(f"    [progress saved: {len(session_results)} sessions]")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_id = "mock-customer-support"
    for arg in sys.argv[1:]:
        if arg.startswith("--agent-id="):
            agent_id = arg.split("=", 1)[1]
        elif arg == "--agent-id" and sys.argv.index(arg) + 1 < len(sys.argv):
            agent_id = sys.argv[sys.argv.index(arg) + 1]

    scenarios_path = os.path.join(
        os.path.dirname(__file__), "..", "scenarios_output.json"
    )
    scenarios_path = os.path.normpath(scenarios_path)

    if not os.path.exists(scenarios_path):
        print(f"ERROR: Scenarios file not found: {scenarios_path}")
        print("Run test_scenarios.py first to generate scenarios.")
        sys.exit(1)

    run_baseline(scenarios_path, agent_id=agent_id)
