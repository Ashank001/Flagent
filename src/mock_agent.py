"""
mock_agent.py — Mock customer-support agent (target agent)

A simple customer-support agent with 4 mock tools wired to Gemini 2.5 Flash
via function calling. Used as the "target agent" whose behaviour we baseline.

Tools:
  - lookup_order(order_id)
  - issue_refund(order_id, amount)
  - send_email(to, subject)
  - update_address(order_id, new_address)
"""

import json
import os
import sys
import time

# Add parent dir so we can import gemini_utils as a sibling module
sys.path.insert(0, os.path.dirname(__file__))

from google.genai import types
from gemini_utils import create_client, rate_limited_generate


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a customer support agent for an e-commerce company. "
    "Help users with orders, refunds, and account updates. "
    "Use the available tools to look up orders, issue refunds, send emails, "
    "and update addresses. Always confirm actions with the user before "
    "proceeding. Be polite, concise, and helpful."
)

# ---------------------------------------------------------------------------
# Mock tool implementations  (no real integrations — fake success responses)
# ---------------------------------------------------------------------------

def lookup_order(order_id: str) -> dict:
    """Look up order details by order ID."""
    return {
        "order_id": order_id,
        "status": "shipped",
        "items": ["Wireless Mouse", "USB-C Cable"],
        "total": 45.99,
        "estimated_delivery": "2026-08-15",
    }


def issue_refund(order_id: str, amount: float) -> dict:
    """Issue a refund for a specific order."""
    return {
        "order_id": order_id,
        "refund_amount": amount,
        "status": "refund_initiated",
        "refund_id": f"RF-{order_id}-001",
    }


def send_email(to: str, subject: str) -> dict:
    """Send an email to the specified address."""
    return {
        "to": to,
        "subject": subject,
        "status": "sent",
        "message_id": f"MSG-{hash(to + subject) % 100000:05d}",
    }


def update_address(order_id: str, new_address: str) -> dict:
    """Update the shipping address for an order."""
    return {
        "order_id": order_id,
        "new_address": new_address,
        "status": "address_updated",
    }


# Map of tool name → callable
TOOL_FUNCTIONS = {
    "lookup_order": lookup_order,
    "issue_refund": issue_refund,
    "send_email": send_email,
    "update_address": update_address,
}

# ---------------------------------------------------------------------------
# Gemini function declarations
# ---------------------------------------------------------------------------

TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="lookup_order",
        description="Look up order details (status, items, total, delivery date) by order ID.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "order_id": {
                    "type": "STRING",
                    "description": "The order ID to look up (e.g. 'ORD-12345').",
                }
            },
            "required": ["order_id"],
        },
    ),
    types.FunctionDeclaration(
        name="issue_refund",
        description="Issue a monetary refund for a specific order.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "order_id": {
                    "type": "STRING",
                    "description": "The order ID to refund.",
                },
                "amount": {
                    "type": "NUMBER",
                    "description": "The dollar amount to refund.",
                },
            },
            "required": ["order_id", "amount"],
        },
    ),
    types.FunctionDeclaration(
        name="send_email",
        description="Send an email to the given address with a subject line.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "to": {
                    "type": "STRING",
                    "description": "Recipient email address.",
                },
                "subject": {
                    "type": "STRING",
                    "description": "Email subject line.",
                },
            },
            "required": ["to", "subject"],
        },
    ),
    types.FunctionDeclaration(
        name="update_address",
        description="Update the shipping address for an order that hasn't been delivered yet.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "order_id": {
                    "type": "STRING",
                    "description": "The order ID whose address to update.",
                },
                "new_address": {
                    "type": "STRING",
                    "description": "The new shipping address.",
                },
            },
            "required": ["order_id", "new_address"],
        },
    ),
]

GEMINI_TOOLS = [types.Tool(function_declarations=TOOL_DECLARATIONS)]


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------

def run_session(user_message: str, *, max_turns: int = 6) -> dict:
    """
    Run a single user message through the mock agent.

    Returns a dict with behavioural metrics:
      - response_text:   final agent reply
      - tool_calls:      list of {name, args, result}
      - tool_call_count: total tool invocations
      - response_length: character length of final reply
      - tool_sequence:   ordered list of tool names called
    """
    client = create_client()

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=GEMINI_TOOLS,
        temperature=0.2,
    )

    # Build initial conversation
    contents = [
        types.Content(role="user", parts=[types.Part.from_text(text=user_message)])
    ]

    tool_calls_log = []
    final_text = ""

    for turn in range(max_turns):
        response = rate_limited_generate(
            client, contents=contents, config=config
        )

        candidate = response.candidates[0]
        model_content = candidate.content

        # Check if model wants to call a function
        has_fc = False
        function_response_parts = []

        for part in model_content.parts:
            if part.function_call:
                has_fc = True
                fc = part.function_call
                fn_name = fc.name
                fn_args = dict(fc.args) if fc.args else {}

                # Execute the mock tool
                fn = TOOL_FUNCTIONS.get(fn_name)
                if fn:
                    result = fn(**fn_args)
                else:
                    result = {"error": f"Unknown tool: {fn_name}"}

                tool_calls_log.append({
                    "name": fn_name,
                    "args": fn_args,
                    "result": result,
                })

                function_response_parts.append(
                    types.Part.from_function_response(
                        name=fn_name,
                        response={"result": result},
                    )
                )

        if has_fc:
            # Add model's response + our function results to conversation
            contents.append(model_content)
            contents.append(
                types.Content(role="user", parts=function_response_parts)
            )
        else:
            # Model gave a text response — we're done
            final_text = candidate.content.parts[0].text if candidate.content.parts else ""
            break

    return {
        "response_text": final_text,
        "tool_calls": tool_calls_log,
        "tool_call_count": len(tool_calls_log),
        "response_length": len(final_text),
        "tool_sequence": [tc["name"] for tc in tool_calls_log],
    }


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    print("=" * 60)
    print("Mock Agent — Smoke Test")
    print("=" * 60)

    test_msg = "Can you check the status of my order ORD-98765?"
    print(f"\nUser: {test_msg}\n")

    result = run_session(test_msg)

    print(f"Agent: {result['response_text'][:500]}")
    print(f"\n--- Behavioural Metrics ---")
    print(f"Tool calls: {result['tool_call_count']}")
    print(f"Tool sequence: {result['tool_sequence']}")
    print(f"Response length: {result['response_length']} chars")
    for tc in result["tool_calls"]:
        print(f"  → {tc['name']}({tc['args']}) → {tc['result']}")
