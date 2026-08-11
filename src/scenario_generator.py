"""
scenario_generator.py — Synthetic scenario generator

Generates exactly 50 diverse, realistic user-task scenarios for the mock
customer-support agent. Uses Gemini 2.5 Flash in 4 batches of ~13 scenarios
each (with different framings for variety), then dedupes to 50.

Respects the Gemini free-tier 15 RPM limit via gemini_utils rate limiter.
"""

import json
import os
import sys

# Add parent dir so we can import gemini_utils as a sibling module
sys.path.insert(0, os.path.dirname(__file__))

# pyrefly: ignore [missing-import]
from google.genai import types
from gemini_utils import create_client, rate_limited_generate
from mock_agent import SYSTEM_PROMPT, TOOL_DECLARATIONS


# ---------------------------------------------------------------------------
# Batch prompts — each batch emphasises a different slice of the behaviour
# space to maximise diversity across the 50 scenarios.
# ---------------------------------------------------------------------------

BATCH_PROMPTS = [
    # Batch 1: Lookup-heavy + mixed
    """You are generating synthetic test scenarios for an AI customer support agent.

The agent has this system prompt:
\"{system_prompt}\"

The agent has these tools:
{tool_list}

Generate exactly 13 diverse, realistic user messages that a real customer might send.
Focus this batch on ORDER LOOKUP scenarios, but include 3-4 that combine lookup
with other actions (e.g. "check my order and also update the address").

Requirements:
- Each scenario is a single user message string (1-3 sentences).
- Vary the phrasing, tone (polite, frustrated, casual, formal), and complexity.
- Include some with typos or informal language.
- Include edge cases: missing order IDs, multiple orders, vague requests.
- Do NOT number them. Do NOT add explanations.

Return ONLY a valid JSON array of 13 strings. No markdown formatting, no code fences.""",

    # Batch 2: Refund-heavy + escalations
    """You are generating synthetic test scenarios for an AI customer support agent.

The agent has this system prompt:
\"{system_prompt}\"

The agent has these tools:
{tool_list}

Generate exactly 13 diverse, realistic user messages focused on REFUND scenarios.
Include 3-4 that involve partial refunds, disputed amounts, or refund + follow-up
email confirmation.

Requirements:
- Each scenario is a single user message string (1-3 sentences).
- Vary tone: angry customer wanting full refund, polite partial refund request,
  confused customer unsure if they qualify.
- Include edge cases: no order ID provided, refund for wrong amount, asking to
  refund an already-refunded order.
- Do NOT number them. Do NOT add explanations.

Return ONLY a valid JSON array of 13 strings. No markdown formatting, no code fences.""",

    # Batch 3: Email + communication tasks
    """You are generating synthetic test scenarios for an AI customer support agent.

The agent has this system prompt:
\"{system_prompt}\"

The agent has these tools:
{tool_list}

Generate exactly 13 diverse, realistic user messages focused on EMAIL and
COMMUNICATION tasks. Include scenarios where the customer wants:
- A confirmation email sent
- A receipt forwarded
- An email to a different address
- A combination of send_email + another tool (e.g. lookup then email receipt)

Requirements:
- Each scenario is a single user message string (1-3 sentences).
- Vary the phrasing and complexity.
- Include edge cases: invalid email format, no subject specified, asking to
  email someone else about their order.
- Do NOT number them. Do NOT add explanations.

Return ONLY a valid JSON array of 13 strings. No markdown formatting, no code fences.""",

    # Batch 4: Address updates + multi-tool combos
    """You are generating synthetic test scenarios for an AI customer support agent.

The agent has this system prompt:
\"{system_prompt}\"

The agent has these tools:
{tool_list}

Generate exactly 13 diverse, realistic user messages. Split them as:
- 6 focused on ADDRESS UPDATE scenarios (change shipping address, fix typo
  in address, update to PO box, etc.)
- 7 MULTI-TOOL COMBINATION scenarios that require 2+ tools in sequence
  (e.g. "look up order, change address, and email me confirmation")

Requirements:
- Each scenario is a single user message string (1-3 sentences).
- Vary tone and complexity.
- Include edge cases: order already delivered, ambiguous address, multiple
  orders needing different address changes.
- Do NOT number them. Do NOT add explanations.

Return ONLY a valid JSON array of 13 strings. No markdown formatting, no code fences.""",
]


def _build_tool_list_str() -> str:
    """Build a human-readable tool list from the function declarations."""
    lines = []
    for decl in TOOL_DECLARATIONS:
        # decl.parameters may be a pydantic Schema or a plain dict
        params = decl.parameters
        if params is None:
            param_names = []
        elif hasattr(params, "properties") and params.properties:
            param_names = list(params.properties.keys())
        elif isinstance(params, dict):
            param_names = list(params.get("properties", {}).keys())
        else:
            param_names = []
        lines.append(f"- {decl.name}({', '.join(param_names)}): {decl.description}")
    return "\n".join(lines)


def generate_scenarios(*, target_count: int = 50) -> list[str]:
    """
    Generate diverse synthetic scenarios in batches, dedupe, and return
    exactly `target_count` unique scenario strings.
    """
    client = create_client()
    tool_list_str = _build_tool_list_str()
    all_scenarios: list[str] = []

    config = types.GenerateContentConfig(
        temperature=0.9,          # High temp for diversity
        max_output_tokens=4096,
    )

    for i, prompt_template in enumerate(BATCH_PROMPTS):
        batch_num = i + 1
        print(f"\n📦 Generating batch {batch_num}/{len(BATCH_PROMPTS)} …")

        prompt = prompt_template.format(
            system_prompt=SYSTEM_PROMPT,
            tool_list=tool_list_str,
        )

        response = rate_limited_generate(
            client, contents=prompt, config=config
        )

        raw_text = response.text.strip()

        # Parse JSON — handle possible markdown code fences
        raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        try:
            batch = json.loads(raw_text)
            if isinstance(batch, list):
                print(f"   ✓ Got {len(batch)} scenarios")
                all_scenarios.extend(batch)
            else:
                print(f"   ⚠ Unexpected JSON type: {type(batch)}")
        except json.JSONDecodeError as e:
            print(f"   ✗ JSON parse error: {e}")
            print(f"   Raw response (first 300 chars): {raw_text[:300]}")

    # --- Deduplicate ---
    seen = set()
    unique: list[str] = []
    for s in all_scenarios:
        normalised = s.strip().lower()
        if normalised not in seen:
            seen.add(normalised)
            unique.append(s.strip())

    print(f"\n🔍 Total raw: {len(all_scenarios)}, unique: {len(unique)}")

    # Trim or warn if we don't have enough
    if len(unique) >= target_count:
        unique = unique[:target_count]
    else:
        print(
            f"⚠ Only {len(unique)} unique scenarios (target: {target_count}). "
            f"Consider re-running or adding another batch."
        )

    return unique


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # pyrefly: ignore [missing-import]
    from dotenv import load_dotenv
    load_dotenv()

    scenarios = generate_scenarios()

    print("\n" + "=" * 60)
    print(f"  Generated {len(scenarios)} scenarios")
    print("=" * 60)
    for i, s in enumerate(scenarios, 1):
        print(f"  {i:2d}. {s}")

    # Also dump to JSON file for downstream use
    output_path = os.path.join(os.path.dirname(__file__), "..", "scenarios_output.json")
    output_path = os.path.normpath(output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scenarios, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Saved to {output_path}")
