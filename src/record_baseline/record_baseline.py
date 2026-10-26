"""
record_baseline.py — Lambda handler for POST /agents/{agent_id}/baseline

Onboarding endpoint.  Accepts EITHER:

  (a) system_prompt + tool_list  →  LLM generates scenarios & simulates
      tool-call traces, then aggregates into a fingerprint.

  (b) scenarios (list of session traces)  →  aggregates directly into a
      fingerprint.  No LLM needed ("bring your own").

v2 — Phase 2:  Builds per-intent-cluster fingerprints in addition to the
global blended fingerprint.  Intent classification is rule-based, driven
by the agent's registered tool_categories.

The fingerprint data is stored in the AgentBaselines DynamoDB table keyed
by agent_id.

Requires x-flagent-key header matching the registered agent's key.
"""

import json
import math
import traceback
import sys
import os
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth import validate_api_key_from_event
from intent_classifier import classify_traces

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,x-flagent-key",
    "Access-Control-Allow-Methods": "OPTIONS,POST",
}


# ---------------------------------------------------------------------------
# Fingerprint aggregation (same algorithm as baseline_recorder.py)
# ---------------------------------------------------------------------------

def _aggregate_fingerprint(session_traces: list[dict]) -> dict:
    """
    Aggregate session traces into a single behavioral fingerprint.

    Each trace must have:
        tools_called:          list[str]
        tool_counts:           dict[str, int]
        response_length_words: int
    """
    n = len(session_traces)
    if n == 0:
        raise ValueError("No session traces to aggregate.")

    # --- Tool frequency: average calls per session for each tool ---
    tool_totals: Counter = Counter()
    all_tools: set = set()
    for trace in session_traces:
        counts = trace.get("tool_counts", {})
        for tool, count in counts.items():
            tool_totals[tool] += int(count)
            all_tools.add(tool)

    tool_frequency = {
        tool: round(tool_totals[tool] / n, 4) for tool in sorted(all_tools)
    }

    # --- Common bigrams: consecutive tool-call pairs ---
    bigram_counts: Counter = Counter()
    for trace in session_traces:
        seq = trace.get("tools_called", [])
        for i in range(len(seq) - 1):
            bigram_key = f"{seq[i]}->{seq[i + 1]}"
            bigram_counts[bigram_key] += 1

    common_bigrams = dict(bigram_counts.most_common())

    # --- Response length stats ---
    lengths = [t.get("response_length_words", 0) for t in session_traces]
    avg_length = sum(lengths) / n
    variance = sum((ln - avg_length) ** 2 for ln in lengths) / n
    std_length = math.sqrt(variance)

    return {
        "tool_frequency": tool_frequency,
        "common_bigrams": common_bigrams,
        "avg_response_length": round(avg_length, 2),
        "std_response_length": round(std_length, 2),
    }


def _build_intent_fingerprints(
    session_traces: list[dict],
    tool_categories: dict[str, str],
    min_cluster_samples: int = 5,
) -> dict:
    """
    Build per-intent-cluster fingerprints plus a global blended fingerprint.

    Args:
        session_traces:      All session traces for the agent.
        tool_categories:     Agent-registered tool→category map.
        min_cluster_samples: Minimum traces to form a standalone cluster
                             fingerprint.  Clusters below this threshold
                             fall back to the blended fingerprint at scoring
                             time.

    Returns:
        {
            "blended":              <fingerprint_dict>,
            "intent_fingerprints":  {
                "retrieval": {"fingerprint": <fp>, "sample_count": N},
                "modification": {"fingerprint": <fp>, "sample_count": N},
                ...
            },
            "min_cluster_samples":  int,
        }
    """
    # Group traces by classified intent
    grouped = classify_traces(session_traces, tool_categories)

    # Per-cluster fingerprints
    intent_fps: dict = {}
    for intent, traces in grouped.items():
        fp = _aggregate_fingerprint(traces)
        intent_fps[intent] = {
            "fingerprint": fp,
            "sample_count": len(traces),
        }

    # Global blended fingerprint (all traces together)
    blended = _aggregate_fingerprint(session_traces)

    return {
        "blended": blended,
        "intent_fingerprints": intent_fps,
        "min_cluster_samples": min_cluster_samples,
    }


# ---------------------------------------------------------------------------
# LLM-based synthetic trace generation (option a)
# ---------------------------------------------------------------------------

def _generate_synthetic_traces(
    system_prompt: str,
    tool_list: list[str],
    tool_categories: dict,
) -> list[dict]:
    """
    Use the configured LLM provider to:
      1. Generate diverse user scenarios for the agent
      2. Simulate which tools the agent would call for each scenario

    Returns a list of trace dicts ready for _aggregate_fingerprint().
    """
    from llm_provider import get_provider

    provider = get_provider()
    tools_desc = ", ".join(tool_list)

    # ---- Step 1: Generate user scenarios ----
    gen_prompt = (
        f"You are helping test an AI agent.\n"
        f"The agent has these tools: {tools_desc}\n\n"
        f"Agent's system prompt:\n{system_prompt}\n\n"
        f"Generate 20 diverse, realistic user messages that this agent would "
        f"receive in production.  Include a mix of simple (1 tool) and "
        f"complex (2-3 tools) requests.\n"
        f"Return ONLY a JSON array of strings, no other text.\n\n"
        f'Example: ["Can you check order #123?", "I need a refund for order #456"]'
    )
    scenarios_text = provider.generate(gen_prompt)

    # Parse scenarios (robust to markdown fences)
    try:
        clean = scenarios_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
            clean = clean.rsplit("```", 1)[0]
        scenarios = json.loads(clean)
    except (json.JSONDecodeError, IndexError):
        scenarios = [f"Help me with request #{i}" for i in range(1, 21)]

    # ---- Step 2: Simulate tool-call behavior per scenario ----
    traces: list[dict] = []
    batch_size = 5

    for batch_start in range(0, len(scenarios), batch_size):
        batch = scenarios[batch_start : batch_start + batch_size]

        sim_prompt = (
            f"You are simulating an AI agent's tool-calling behavior.\n"
            f"The agent has these tools: {tools_desc}\n"
            f"Tool categories: {json.dumps(tool_categories)}\n\n"
            f"For each user message below, predict what tools the agent "
            f"would call and in what order.  A well-behaved agent calls "
            f"only the tools needed.\n\n"
            f"User messages:\n{json.dumps(batch, indent=2)}\n\n"
            f"Return a JSON array of objects, one per message:\n"
            f'[{{"tools_called": ["tool1", "tool2"], '
            f'"response_length_words": 45}}, ...]\n\n'
            f"Rules:\n"
            f"- Only use tools from the available list\n"
            f"- Simple requests: 1-2 tools\n"
            f"- Complex requests: 2-4 tools\n"
            f"- response_length_words: typically 20-80 words\n"
            f"- Return ONLY the JSON array"
        )
        result_text = provider.generate(sim_prompt)

        try:
            clean = result_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1]
                clean = clean.rsplit("```", 1)[0]
            batch_traces = json.loads(clean)
        except (json.JSONDecodeError, IndexError):
            batch_traces = [
                {
                    "tools_called": [tool_list[0]] if tool_list else [],
                    "response_length_words": 40,
                }
                for _ in batch
            ]

        for trace in batch_traces:
            tools_called = trace.get("tools_called", [])
            # Filter to only valid tools from the registered set
            tools_called = [t for t in tools_called if t in tool_list]

            traces.append(
                {
                    "tools_called": tools_called,
                    "tool_counts": dict(Counter(tools_called)),
                    "response_length_words": trace.get(
                        "response_length_words", 40
                    ),
                }
            )

    return traces


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def handler(event, context):
    """
    Record a behavioral baseline for a registered agent.

    Path:    POST /agents/{agent_id}/baseline
    Headers: x-flagent-key (required)

    Body option (a) — LLM-generated:
        {
            "system_prompt": "You are a helpful support agent...",
            "tool_list": ["lookup_order", "issue_refund", "send_email"]
        }

    Body option (b) — bring your own:
        {
            "scenarios": [
                {
                    "tools_called": ["lookup_order"],
                    "tool_counts": {"lookup_order": 1},
                    "response_length_words": 40
                },
                ...
            ]
        }
    """
    try:
        # ---- Extract agent_id from path ----
        path_params = event.get("pathParameters", {}) or {}
        agent_id = path_params.get("agent_id")

        if not agent_id:
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": "Missing agent_id in path"}),
            }

        # ---- Authenticate ----
        auth_result = validate_api_key_from_event(event, agent_id)
        if not auth_result["valid"]:
            return {
                "statusCode": 401,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": auth_result["error"]}),
            }

        body = json.loads(event.get("body", "{}"))
        agent = auth_result["agent"]

        # Extract tool_categories (DynamoDB returns Decimal-wrapped map)
        tool_categories = {}
        raw_cats = agent.get("tool_categories", {})
        if raw_cats:
            tool_categories = {str(k): str(v) for k, v in raw_cats.items()}

        # Extract min_cluster_samples from agent scoring_config
        scoring_config = agent.get("scoring_config", {})
        min_cluster_samples = int(
            scoring_config.get("min_cluster_samples", 5)
        )

        # ---- Determine mode ----
        if "scenarios" in body:
            # Option (b): user-supplied traces
            session_traces = body["scenarios"]

            if not isinstance(session_traces, list) or len(session_traces) == 0:
                return {
                    "statusCode": 400,
                    "headers": CORS_HEADERS,
                    "body": json.dumps({
                        "error": "scenarios must be a non-empty list of session traces"
                    }),
                }

            # Auto-fill missing fields
            for i, trace in enumerate(session_traces):
                if "tools_called" not in trace:
                    return {
                        "statusCode": 400,
                        "headers": CORS_HEADERS,
                        "body": json.dumps({
                            "error": f"Scenario {i} missing 'tools_called'"
                        }),
                    }
                if "tool_counts" not in trace:
                    trace["tool_counts"] = dict(Counter(trace["tools_called"]))
                if "response_length_words" not in trace:
                    trace["response_length_words"] = 40

            source = "user_supplied"

        elif "system_prompt" in body and "tool_list" in body:
            # Option (a): LLM-generated
            system_prompt = body["system_prompt"]
            tool_list = body["tool_list"]

            if not isinstance(tool_list, list) or len(tool_list) == 0:
                return {
                    "statusCode": 400,
                    "headers": CORS_HEADERS,
                    "body": json.dumps({
                        "error": "tool_list must be a non-empty list of tool names"
                    }),
                }

            session_traces = _generate_synthetic_traces(
                system_prompt, tool_list, tool_categories
            )
            source = "llm_generated"

        else:
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({
                    "error": (
                        "Request must include either 'scenarios' (list of traces) "
                        "or 'system_prompt' + 'tool_list'"
                    ),
                    "examples": {
                        "bring_your_own": {
                            "scenarios": [
                                {
                                    "tools_called": ["lookup_order"],
                                    "tool_counts": {"lookup_order": 1},
                                    "response_length_words": 40,
                                }
                            ]
                        },
                        "llm_generated": {
                            "system_prompt": "You are a helpful agent...",
                            "tool_list": ["lookup_order", "issue_refund"],
                        },
                    },
                }),
            }

        # ---- Build per-intent + blended fingerprints ----
        intent_data = _build_intent_fingerprints(
            session_traces, tool_categories, min_cluster_samples
        )
        blended_fingerprint = intent_data["blended"]
        intent_fingerprints = intent_data["intent_fingerprints"]

        # ---- Persist to DynamoDB ----
        import boto3

        region = os.environ.get("AWS_REGION", "ap-south-1")
        table_name = os.environ.get("BASELINES_TABLE", "AgentBaselines")

        dynamodb = boto3.resource("dynamodb", region_name=region)
        table = dynamodb.Table(table_name)

        item = json.loads(
            json.dumps(
                {
                    "agent_id": agent_id,
                    "fingerprint": blended_fingerprint,   # backward compat
                    "intent_fingerprints": intent_fingerprints,
                    "min_cluster_samples": min_cluster_samples,
                    "scenario_count": len(session_traces),
                    "source": source,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            parse_float=Decimal,
        )
        table.put_item(Item=item)

        # ---- Build response with intent summary ----
        intent_summary = {
            intent: {
                "sample_count": data["sample_count"],
                "tools": list(data["fingerprint"]["tool_frequency"].keys()),
            }
            for intent, data in intent_fingerprints.items()
        }

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "agent_id": agent_id,
                "fingerprint": blended_fingerprint,
                "intent_clusters": intent_summary,
                "min_cluster_samples": min_cluster_samples,
                "scenario_count": len(session_traces),
                "source": source,
                "message": "Baseline recorded with per-intent clusters",
            }),
        }

    except Exception as e:
        traceback.print_exc()
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)}),
        }
