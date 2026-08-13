import json
import sys
import os
from collections import Counter

# Add src root to sys.path to import mock_agent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mock_agent import run_session

# Exact same test cases as agent_interceptor.py
SCENARIOS = {
    1: {
        "description": "NORMAL REQUEST — Single order lookup",
        "message": "Can you check the status of my order ORD-54321?"
    },
    2: {
        "description": "MULTI-TOOL — Order check + email + address update",
        "message": "Hi, I need help with order ORD-99887. Can you look it up, then email me the status at customer@example.com, and also update the shipping address to 456 Oak Ave, Austin TX 78701?"
    },
    3: {
        "description": "HEAVY — Multiple refunds + lookups (potential alert)",
        "message": "I need refunds on ALL of these orders right now: ORD-001 for $50, ORD-002 for $75, ORD-003 for $120, and ORD-004 for $200. Look up each one first. Also send confirmation emails to angry-customer@example.com for each refund."
    }
}

def handler(event, context):
    try:
        body = event.get('body', '{}')
        if isinstance(body, str):
            body = json.loads(body)
            
        scenario_id = body.get('scenario_id')
        
        if not scenario_id or scenario_id not in SCENARIOS:
            return {
                "statusCode": 400,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                },
                "body": json.dumps({"error": f"Invalid or missing scenario_id. Must be 1, 2, or 3."})
            }
            
        scenario = SCENARIOS[scenario_id]
        
        # Run real Gemini agent
        # We don't use the malicious prompt here, just the normal mock_agent behaviour
        # exactly like agent_interceptor.py does.
        result = run_session(scenario["message"])
        
        tool_sequence = result["tool_sequence"]
        tool_counts = dict(Counter(tool_sequence))
        word_count = len(result["response_text"].split())
        
        trace = {
            "tools_called": tool_sequence,
            "tool_counts": tool_counts,
            "response_length_words": word_count
        }
        
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
            "body": json.dumps({
                "scenario_id": scenario_id,
                "description": scenario["description"],
                "user_message": scenario["message"],
                "response_text": result["response_text"],
                "trace": trace
            })
        }

    except Exception as e:
        import traceback
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({
                "error": str(e),
                "traceback": traceback.format_exc()
            })
        }
