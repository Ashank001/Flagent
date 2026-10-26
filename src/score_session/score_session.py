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
from intent_classifier import classify_intent
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

def _select_fingerprint(baseline_item: dict, intent_cluster: str) -> tuple[dict, str]:
    """
    Select the right fingerprint for scoring based on intent cluster.

    Returns (fingerprint_dict, baseline_used) where baseline_used is either
    the intent cluster name or "blended".

    Falls back to blended if:
      - No intent_fingerprints stored (pre-Phase 2 baseline)
      - The intent cluster doesn't exist in intent_fingerprints
      - The cluster has fewer samples than min_cluster_samples
    """
    intent_fps = baseline_item.get("intent_fingerprints")
    min_samples = int(baseline_item.get("min_cluster_samples", 5))
    blended = baseline_item.get("fingerprint", {})

    if not intent_fps:
        return blended, "blended"

    cluster_data = intent_fps.get(intent_cluster)
    if not cluster_data:
        return blended, "blended"

    sample_count = int(cluster_data.get("sample_count", 0))
    if sample_count < min_samples:
        return blended, "blended"

    return cluster_data["fingerprint"], intent_cluster


def handler(event, context):
    """
    Score a session trace against the baseline fingerprint.

    LEGACY MODE (no x-flagent-key header):
        Behaves exactly as v1 — loads fingerprint from the local
        baseline_output.json, uses agent_id "mock-customer-support".
        No intent classification.  Keeps validate.py / dashboard.html working.

    AUTHENTICATED MODE (x-flagent-key header present):
        1. Validates the key
        2. Classifies the trace's intent via tool_categories
        3. Loads the matching intent-cluster fingerprint from DynamoDB
           (falls back to blended if cluster is too small)
        4. Scores using the agent's per-agent scoring_config
        5. Returns intent_cluster, baseline_used, score, classification,
           and per-component breakdown

    Request body:
        {
            "trace": {
                "tools_called": ["lookup_order", "issue_refund"],
                "tool_counts": {"lookup_order": 1, "issue_refund": 1},
                "response_length_words": 65
            },
            "agent_id": "my-agent",
            "include_all_clusters": false   // optional: score against ALL clusters for comparison
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
            # LEGACY MODE — exact v1 behavior, no intent classification
            agent_id = body.get("agent_id", "mock-customer-support")

            current_dir = os.path.dirname(os.path.abspath(__file__))
            baseline_path = os.path.join(current_dir, "..", "baseline_output.json")

            with open(baseline_path, "r", encoding="utf-8") as f:
                baseline = json.load(f)
            fingerprint = baseline["fingerprint"]

            # Score with default config (no scoring_config → module defaults)
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

        # -----------------------------------------------------------------
        # AUTHENTICATED MODE — intent-aware, per-agent scoring
        # -----------------------------------------------------------------
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

        agent = auth_result["agent"]

        # Extract tool_categories and scoring_config from agent record
        tool_categories = {}
        raw_cats = agent.get("tool_categories", {})
        if raw_cats:
            tool_categories = {str(k): str(v) for k, v in raw_cats.items()}

        scoring_config = _decimal_to_native(agent.get("scoring_config", {}))

        # Load baseline from DynamoDB AgentBaselines
        region = os.environ.get("AWS_REGION", "ap-south-1")
        baselines_table = os.environ.get("BASELINES_TABLE", "AgentBaselines")

        dynamodb = boto3.resource("dynamodb", region_name=region)
        bl_table = dynamodb.Table(baselines_table)

        response = bl_table.get_item(Key={"agent_id": agent_id})
        baseline_item = response.get("Item")

        if not baseline_item or "fingerprint" not in baseline_item:
            return {
                "statusCode": 404,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Content-Type,x-flagent-key",
                    "Access-Control-Allow-Methods": "OPTIONS,POST"
                },
                "body": json.dumps({
                    "error": f"No baseline found for agent '{agent_id}'. "
                             f"Record a baseline first via POST /agents/{agent_id}/baseline"
                })
            }

        # Convert all Decimal values
        baseline_item = _decimal_to_native(baseline_item)

        # Classify the incoming trace's intent
        intent_cluster = classify_intent(
            trace.get("tools_called", []), tool_categories
        )

        # Select the right fingerprint (per-intent or blended fallback)
        fingerprint, baseline_used = _select_fingerprint(
            baseline_item, intent_cluster
        )

        # Score with per-agent config
        result = score_session(trace, fingerprint, scoring_config)

        # Optionally score against ALL clusters for comparison
        all_cluster_scores = None
        if body.get("include_all_clusters"):
            all_cluster_scores = {}
            # Score against blended
            blended_fp = baseline_item.get("fingerprint", {})
            blended_result = score_session(trace, blended_fp, scoring_config)
            all_cluster_scores["blended"] = {
                "score": blended_result["score"],
                "classification": blended_result["classification"],
            }
            # Score against each intent cluster
            intent_fps = baseline_item.get("intent_fingerprints", {})
            for cluster_name, cluster_data in intent_fps.items():
                cluster_fp = cluster_data.get("fingerprint", {})
                cluster_result = score_session(trace, cluster_fp, scoring_config)
                all_cluster_scores[cluster_name] = {
                    "score": cluster_result["score"],
                    "classification": cluster_result["classification"],
                    "sample_count": cluster_data.get("sample_count", 0),
                }

        # Save to DynamoDB SessionScores
        sessions_table = os.environ.get("SESSIONS_TABLE", "SessionScores")
        s_table = dynamodb.Table(sessions_table)

        session_id = str(uuid.uuid4())

        save_item = json.loads(
            json.dumps({
                "agent_id": agent_id,
                "session_id": session_id,
                "score": result["score"],
                "classification": result["classification"],
                "components": result["components"],
                "intent_cluster": intent_cluster,
                "baseline_used": baseline_used,
                "trace": trace,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }),
            parse_float=Decimal,
        )
        s_table.put_item(Item=save_item)

        # Build response
        resp_body = {
            "session_id": session_id,
            "agent_id": agent_id,
            "intent_cluster": intent_cluster,
            "baseline_used": baseline_used,
            "score": result["score"],
            "classification": result["classification"],
            "components": result["components"],
        }
        if all_cluster_scores:
            resp_body["all_cluster_scores"] = all_cluster_scores

        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,x-flagent-key",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps(resp_body, cls=DecimalEncoder)
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
