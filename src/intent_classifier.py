"""
intent_classifier.py — Rule-Based Intent Classification

Classifies a session's intent based on its tool calls and the agent's
registered tool_categories mapping.  No LLM calls, no hardcoded tool names.

Algorithm:
  1. Map each tool call to its category from tool_categories.
  2. Count category occurrences.
  3. If one category has > 50 % of calls, that's the intent.
  4. Otherwise return "mixed".
  5. Empty sessions return "general".
"""

from collections import Counter


def classify_intent(
    tools_called: list[str],
    tool_categories: dict[str, str],
) -> str:
    """
    Classify the intent of a session based on its tool-call sequence.

    Args:
        tools_called:    Ordered list of tool names invoked in the session.
        tool_categories: Agent-registered map of tool_name → category
                         (e.g. {"lookup_order": "retrieval",
                                "issue_refund": "modification"}).

    Returns:
        The dominant category string, "mixed", or "general" (no tools).
    """
    if not tools_called:
        return "general"

    category_counts: Counter = Counter()
    for tool in tools_called:
        category = tool_categories.get(tool, "unknown")
        category_counts[category] += 1

    total = sum(category_counts.values())
    if total == 0:
        return "general"

    dominant_category, dominant_count = category_counts.most_common(1)[0]

    # Dominant if strictly more than 50 % of tool calls fall into one category
    if dominant_count / total > 0.5:
        return dominant_category

    return "mixed"


def classify_traces(
    traces: list[dict],
    tool_categories: dict[str, str],
) -> dict[str, list[dict]]:
    """
    Group a list of session traces by their classified intent.

    Args:
        traces:          List of trace dicts, each having a "tools_called" key.
        tool_categories: Agent-registered tool→category map.

    Returns:
        Dict mapping intent_cluster → list of traces belonging to that cluster.
    """
    grouped: dict[str, list[dict]] = {}
    for trace in traces:
        intent = classify_intent(
            trace.get("tools_called", []), tool_categories
        )
        grouped.setdefault(intent, []).append(trace)
    return grouped
