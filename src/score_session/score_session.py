import json
import traceback
import sys
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deviation_scorer import score_session
from auth import is_legacy_request, validate_api_key_from_event
import boto3

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super(DecimalEncoder, self).default(o)

def _decimal_to_native(obj):
    """Recursively convert Decimal values from DynamoDB to float/int."""
    if isinstance(obj, Decimal):
        if obj == int(obj):
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_native(i) for i in obj]
    return obj

def handler(event, context):
    """
    Score a session trace against the baseline fingerprint.
    
    LEGACY MODE (no x-flagent-key header):
        Behaves exactly as v1 — loads fingerprint from the local
        baseline_output.json, uses agent_id "mock-customer-support".
        This keeps validate.py, dashboard.html, and agent_interceptor.py working.

    AUTHENTICATED MODE (x-flagent-key header present):
        Validates the key, loads the agent's fingerprint from DynamoDB,
        and scores against that. Requires agent_id in the request body.

    Request body:
        {
            "trace": {
                "tools_called": ["lookup_order", "issue_refund"],
                "tool_counts": {"lookup_order": 1, "issue_refund": 1},
                "response_length_words": 65
            },
            "agent_id": "my-agent"    // optional in legacy mode, required in auth mode
        }
    
    Returns anomaly score (0-100) and classification (normal/warning/alert).
    Saves result to SessionScores DynamoDB table.
    """
    try:
        body = json.loads(event.get("body", "{}"))
        trace = body.get("trace")
        
        if not trace:
            return {
                "statusCode": 400,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Content-Type,x-flagent-key",
                    "Access-Control-Allow-Methods": "OPTIONS,POST"
                },
                "body": json.dumps({
                    "error": "Missing 'trace' in request body.",
                    "example": {
                        "trace": {
                            "tools_called": ["lookup_order"],
                            "tool_counts": {"lookup_order": 1},
                            "response_length_words": 40
                        }
                    }
                })
            }
        
        # -----------------------------------------------------------------
        # Determine mode: legacy vs authenticated
        # -----------------------------------------------------------------
        if is_legacy_request(event):
            # LEGACY MODE — exact v1 behavior
            agent_id = body.get("agent_id", "mock-customer-support")
            
            current_dir = os.path.dirname(os.path.abspath(__file__))
            baseline_path = os.path.join(current_dir, "..", "baseline_output.json")
            
            with open(baseline_path, "r", encoding="utf-8") as f:
                baseline = json.load(f)
            fingerprint = baseline["fingerprint"]
        
        else:
            # AUTHENTICATED MODE — load fingerprint from DynamoDB
            agent_id = body.get("agent_id")
            
            if not agent_id:
                return {
                    "statusCode": 400,
                    "headers": {
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Headers": "Content-Type,x-flagent-key",
                        "Access-Control-Allow-Methods": "OPTIONS,POST"
                    },
                    "body": json.dumps({
                        "error": "agent_id is required in the request body when using API key auth"
                    })
                }
            
            # Validate API key
            auth_result = validate_api_key_from_event(event, agent_id)
            if not auth_result["valid"]:
                return {
                    "statusCode": 401,
                    "headers": {
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Headers": "Content-Type,x-flagent-key",
                        "Access-Control-Allow-Methods": "OPTIONS,POST"
                    },
                    "body": json.dumps({"error": auth_result["error"]})
                }
            
            # Load fingerprint from DynamoDB AgentBaselines
            region = os.environ.get("AWS_REGION", "ap-south-1")
            baselines_table = os.environ.get("BASELINES_TABLE", "AgentBaselines")
            
            dynamodb = boto3.resource("dynamodb", region_name=region)
            table = dynamodb.Table(baselines_table)
            
            response = table.get_item(Key={"agent_id": agent_id})
            item = response.get("Item")
            
            if not item or "fingerprint" not in item:
                return {
                    "statusCode": 404,
                    "headers": {
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Headers": "Content-Type,x-flagent-key",
                        "Access-Control-Allow-Methods": "OPTIONS,POST"
                    },
                    "body": json.dumps({
                        "error": f"No baseline found for agent '{agent_id}'. Record a baseline first via POST /agents/{agent_id}/baseline"
                    })
                }
            
            # Convert Decimal values from DynamoDB to native Python types
            fingerprint = _decimal_to_native(item["fingerprint"])
        
        # -----------------------------------------------------------------
        # Score the session
        # -----------------------------------------------------------------
        result = score_session(trace, fingerprint)
        
        # Save to DynamoDB SessionScores
        region = os.environ.get("AWS_REGION", "ap-south-1")
        table_name = os.environ.get("SESSIONS_TABLE", "SessionScores")
        
        dynamodb = boto3.resource("dynamodb", region_name=region)
        table = dynamodb.Table(table_name)
        
        session_id = str(uuid.uuid4())
        
        item = json.loads(
            json.dumps({
                "agent_id": agent_id,
                "session_id": session_id,
                "score": result["score"],
                "classification": result["classification"],
                "components": result["components"],
                "trace": trace,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }),
            parse_float=Decimal,
        )
        table.put_item(Item=item)
        
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,x-flagent-key",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "session_id": session_id,
                "agent_id": agent_id,
                "score": result["score"],
                "classification": result["classification"],
                "components": result["components"],
            }, cls=DecimalEncoder)
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,x-flagent-key",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({"error": str(e)})
        }
