import json
import traceback
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from baseline_recorder import run_baseline

def handler(event, context):
    """
    Run the baseline recorder against all scenarios.
    
    NOTE: This is a long-running operation (~5-10 min with rate limiting).
    API Gateway has a hard 29s timeout. When called via API Gateway, this
    returns the pre-computed baseline fingerprint. For a fresh baseline run,
    invoke the Lambda directly: aws lambda invoke --function-name ps41-run-baseline
    """
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Check for pre-computed baseline first (fast path for API Gateway)
        baseline_path = os.path.join(current_dir, "..", "baseline_output.json")
        if os.path.exists(baseline_path):
            with open(baseline_path, "r", encoding="utf-8") as f:
                output = json.load(f)
            return {
                "statusCode": 200,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Allow-Methods": "OPTIONS,POST"
                },
                "body": json.dumps({
                    "fingerprint": output.get("fingerprint", {}),
                    "scenario_count": output.get("scenario_count", 0),
                    "source": "cached",
                    "status": "Baseline fingerprint loaded successfully"
                })
            }
        
        # Fall back to live generation (will timeout via API Gateway)
        scenarios_path = os.path.join(current_dir, "..", "scenarios_output.json")
        if not os.path.exists(scenarios_path):
            return {
                "statusCode": 400,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Allow-Methods": "OPTIONS,POST"
                },
                "body": json.dumps({"error": "scenarios_output.json not found. Call /generate-scenarios first."})
            }
        
        output = run_baseline(scenarios_path)
            
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "fingerprint": output.get("fingerprint", {}),
                "scenario_count": output.get("scenario_count", 0),
                "source": "generated",
                "status": "Baseline recorded successfully"
            })
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
