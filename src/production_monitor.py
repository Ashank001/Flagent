"""
production_monitor.py — Production Monitor / Session Scorer

Accepts a new session, runs it through the target agent, scores it using the 
baseline fingerprint, and saves the result to DynamoDB SessionScores table.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import boto3
from botocore.exceptions import ClientError

from mock_agent import run_session
from deviation_scorer import score_session


def _ensure_session_scores_table_exists(table_name: str, region: str) -> None:
    dynamodb = boto3.client("dynamodb", region_name=region)
    try:
        dynamodb.describe_table(TableName=table_name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"  [dynamo] Creating table '{table_name}' ...")
            dynamodb.create_table(
                TableName=table_name,
                KeySchema=[
                    {"AttributeName": "agent_id", "KeyType": "HASH"},
                    {"AttributeName": "session_id", "KeyType": "RANGE"}
                ],
                AttributeDefinitions=[
                    {"AttributeName": "agent_id", "AttributeType": "S"},
                    {"AttributeName": "session_id", "AttributeType": "S"}
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            dynamodb.get_waiter("table_exists").wait(TableName=table_name)
            print(f"  [dynamo] Table '{table_name}' created.")
        else:
            raise


def process_session(user_message: str, agent_id: str = "mock-customer-support", system_prompt: str | None = None) -> dict:
    """Run session, score it, save to DynamoDB, and return results."""
    # 1. Load Fingerprint
    baseline_path = os.path.join(os.path.dirname(__file__), "..", "baseline_output.json")
    if not os.path.exists(baseline_path):
        raise RuntimeError("baseline_output.json not found. Run baseline_recorder.py first.")
        
    with open(baseline_path, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    fingerprint = baseline["fingerprint"]

    # 2. Run target agent
    result = run_session(user_message, system_prompt=system_prompt)
    
    trace = {
        "tools_called": result["tool_sequence"],
        "tool_counts": result["tool_counts"] if "tool_counts" in result else __import__('collections').Counter(result["tool_sequence"]),
        "response_length_words": len(result["response_text"].split()),
    }
    
    # 3. Score session
    score_result = score_session(trace, fingerprint)
    
    # 4. Save to DynamoDB
    region = os.environ.get("AWS_REGION", "ap-south-1")
    table_name = os.environ.get("SESSIONS_TABLE", "SessionScores")
    
    _ensure_session_scores_table_exists(table_name, region)
    
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)
    
    session_id = str(uuid.uuid4())
    
    item = json.loads(
        json.dumps(
            {
                "agent_id": agent_id,
                "session_id": session_id,
                "score": score_result["score"],
                "classification": score_result["classification"],
                "components": score_result["components"],
                "trace": trace,
                "scenario": user_message[:500],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        parse_float=Decimal,
    )
    table.put_item(Item=item)
    
    return {
        "session_id": session_id,
        "score_result": score_result,
        "trace": trace
    }



