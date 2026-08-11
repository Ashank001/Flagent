import json
import traceback
import sys
import os
import boto3

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scenario_generator import generate_scenarios

def handler(event, context):
    """
    Generate 50 diverse synthetic scenarios using Gemini.
    
    NOTE: This is a long-running operation (~2-3 min with rate limiting).
    API Gateway has a hard 29s timeout, so when called via API Gateway this
    will return a pre-generated scenario set. For fresh generation, invoke
    the Lambda directly: aws lambda invoke --function-name ps41-generate-scenarios
    """
    try:
        # Check if we already have pre-packaged scenarios
        current_dir = os.path.dirname(os.path.abspath(__file__))
        cached_path = os.path.join(current_dir, "..", "scenarios_output.json")
        
        if os.path.exists(cached_path):
            with open(cached_path, "r", encoding="utf-8") as f:
                scenarios = json.load(f)
            return {
                "statusCode": 200,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Allow-Methods": "OPTIONS,POST"
                },
                "body": json.dumps({
                    "scenarios": scenarios,
                    "count": len(scenarios),
                    "source": "cached"
                })
            }
        
        # If no cached file, generate fresh (will timeout via API Gateway)
        scenarios = generate_scenarios()
        
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "scenarios": scenarios,
                "count": len(scenarios),
                "source": "generated"
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
