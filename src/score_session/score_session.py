import json
import traceback
import sys
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deviation_scorer import score_session
import boto3

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super(DecimalEncoder, self).default(o)

def handler(event, context):
    """
    Score a session trace against the baseline fingerprint.
    
    Accepts a JSON body with a 'trace' object:
    {
        "trace": {
            "tools_called": ["lookup_order", "issue_refund"],
            "tool_counts": {"lookup_order": 1, "issue_refund": 1},
            "response_length_words": 65
        }
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
                    "Access-Control-Allow-Headers": "Content-Type",
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
        
        # Load baseline fingerprint
        current_dir = os.path.dirname(os.path.abspath(__file__))
        baseline_path = os.path.join(current_dir, "..", "baseline_output.json")
        
        with open(baseline_path, "r", encoding="utf-8") as f:
            baseline = json.load(f)
        fingerprint = baseline["fingerprint"]
        
        # Score the session
        result = score_session(trace, fingerprint)
        
        # Save to DynamoDB
        region = os.environ.get("AWS_REGION", "ap-south-1")
        table_name = os.environ.get("SESSIONS_TABLE", "SessionScores")
        
        dynamodb = boto3.resource("dynamodb", region_name=region)
        table = dynamodb.Table(table_name)
        
        session_id = str(uuid.uuid4())
        
        item = json.loads(
            json.dumps({
                "agent_id": "mock-customer-support",
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
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "session_id": session_id,
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
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({"error": str(e)})
        }
