"""
minimal.py — Minimal working example of the Flagent SDK

Demonstrates:
  1. Creating the client
  2. Wrapping tool functions
  3. Using the @governed() decorator
  4. Reading the score result

Run against the live API:
    cd flagent-sdk
    pip install -e .
    python examples/minimal.py
"""

from flagent import Flagent

# ----- Configuration -----
API_URL = "https://t2xtoo4zpg.execute-api.ap-south-1.amazonaws.com/dev"
API_KEY = "YOUR_API_KEY_HERE"        # from POST /agents/register
AGENT_ID = "YOUR_AGENT_ID_HERE"      # your registered agent_id

# ----- 1. Create client -----
fg = Flagent(
    api_url=API_URL,
    api_key=API_KEY,
    agent_id=AGENT_ID,
    mode="enforce",   # "shadow" for non-blocking, "enforce" for sync scoring
)


# ----- 2. Define your tool functions -----
def lookup_order(order_id):
    """Simulate an order lookup."""
    return {"order_id": order_id, "status": "shipped", "eta": "2 days"}


def issue_refund(order_id, amount):
    """Simulate issuing a refund."""
    return {"order_id": order_id, "refunded": amount}


# ----- 3. Wrap them -----
tools = fg.wrap_tools({
    "lookup_order": lookup_order,
    "issue_refund": issue_refund,
})


# ----- 4. Decorate your agent function -----
@fg.governed(
    on_alert=lambda r: print(f"🚨 ALERT! Score: {r.score}, Classification: {r.classification}"),
    on_warning=lambda r: print(f"⚠️  Warning. Score: {r.score}"),
)
def handle_request(user_message: str) -> str:
    """Your agent's main handler."""
    # Normal behavior: look up order
    result = tools["lookup_order"]("ORD-12345")

    # The SDK auto-captures this tool call
    return f"Your order status: {result['status']}, ETA: {result['eta']}"


# ----- 5. Run it -----
if __name__ == "__main__":
    print("Running governed agent...")
    response = handle_request("Where is my order?")
    print(f"Agent response: {response}")

    # Access the last score result
    result = handle_request.last_result
    if result:
        print(f"\nGovernance Score: {result.score}")
        print(f"Classification:   {result.classification}")
        print(f"Intent Cluster:   {result.intent_cluster}")
        print(f"Baseline Used:    {result.baseline_used}")
        print(f"Components:       {result.components}")
    else:
        print("\n(No score result — API may be unreachable)")
