# Build Log — PS-4.1 Agent Behavioral Baseline Builder

## Current Status
**PROJECT COMPLETE.** 
All Lambda handlers (`generate_scenarios`, `run_baseline`, `score_session`) are successfully wired to their respective modules. `template.yaml` is fully parameterized with a shared `src/` CodeUri and a top-level `GeminiApiKey` SAM parameter. The `README.md` is populated with precise deployment and verification steps mapped to the problem statement success criteria.

## Completed Components
- [x] `BUILD_LOG.md` — `/BUILD_LOG.md` — Persistent build log. Tested: N/A
- [x] `template.yaml` — `/template.yaml` — SAM template: 3 Lambdas, 2 DynamoDB tables, 1 API Gateway. Tested: Y
- [x] `generate_scenarios.py` — `/src/generate_scenarios/generate_scenarios.py` — Lambda handler calling `scenario_generator.py`. Tested: Y
- [x] `run_baseline.py` — `/src/run_baseline/run_baseline.py` — Lambda handler calling `baseline_recorder.py`. Tested: Y
- [x] `score_session.py` — `/src/score_session/score_session.py` — Lambda handler calling `production_monitor.py`. Tested: Y
- [x] `requirements.txt` — `/src/requirements.txt` — Consolidated Python deps for SAM build. Tested: Y
- [x] `.env.example` — `/.env.example` — Template for required environment variables
- [x] `.gitignore` — `/.gitignore` — Excludes .env, __pycache__, .aws-sam, samconfig.toml
- [x] `gemini_utils.py` — `/src/gemini_utils.py` — Shared Gemini client: create_client(), rate_limited_generate() with model rotation and smart 429 retry. Tested: Y
- [x] `mock_agent.py` — `/src/mock_agent.py` — Mock customer-support agent with 4 tools (lookup_order, issue_refund, send_email, update_address) wired to Gemini function calling. Returns behavioural metrics per session. Tested: Y
- [x] `scenario_generator.py` — `/src/scenario_generator.py` — Generates 50 diverse scenarios in 4 batches via Gemini, dedupes to 50 unique. Tested: Y
- [x] `test_scenarios.py` — `/test_scenarios.py` — Test script: runs generator, prints all 50 scenarios + intent distribution stats. Tested: Y
- [x] `scenarios_output.json` — `/scenarios_output.json` — Last generated set of 50 scenarios (JSON array). Tested: N/A
- [x] `baseline_recorder.py` — `/src/baseline_recorder.py` — Takes 50 synthetic scenarios, runs mock agent on each, and saves aggregate fingerprint to DynamoDB and `baseline_output.json`. Tested: Y
- [x] `deviation_scorer.py` — `/src/deviation_scorer.py` — Scores session anomaly (0-100) vs baseline fingerprint using Cosine Distance (40%), Bigram Novelty (35%), and Length Z-score (25%). Tested: Y
- [x] `test_calibration.py` — `/test_calibration.py` — Validates the scoring algorithm on baseline dataset. Tested: Y (3/3 checks passed)
- [x] `baseline_output.json` — `/baseline_output.json` — Local copy of the generated baseline fingerprint + traces.
- [x] `production_monitor.py` — `/src/production_monitor.py` — Evaluates new sessions, scores via deviation_scorer, and saves to DynamoDB `SessionScores`.
- [x] `test_production_monitor.py` — `/test_production_monitor.py` — Tests NORMAL/WARNING/ALERT tier classification.
- [x] `drift_detector.py` — `/src/drift_detector.py` — Simulates prompt drift and triggers alert on rolling 5-session average > 45.
- [x] `README.md` — `/README.md` — Deployment instructions and API Gateway verification curl commands mapped to success criteria.

## Known Issues / TODO
*(None — Project Complete)*

## Final AWS Resources
| Resource Type | Name | Region | Notes |
|---|---|---|---|
| API Gateway | `ps41-baseline-api` | `ap-south-1` | REST API, Stage: `dev` |
| Lambda Function | `ps41-generate-scenarios` | `ap-south-1` | POST `/generate-scenarios` |
| Lambda Function | `ps41-run-baseline` | `ap-south-1` | POST `/run-baseline`, 300s timeout |
| Lambda Function | `ps41-score-session` | `ap-south-1` | POST `/score-session` |
| DynamoDB Table | `AgentBaselines` | `ap-south-1` | PK: `agent_id` (S), PAY_PER_REQUEST |
| DynamoDB Table | `SessionScores` | `ap-south-1` | PK: `agent_id` (S), SK: `session_id` (S), PAY_PER_REQUEST |

## How to Run/Test Locally
```bash
# Set PYTHONUTF8=1 on Windows to avoid encoding issues with emoji output
# PowerShell: $env:PYTHONUTF8="1"

# Generate 50 scenarios (takes ~30s with rate limiting)
python test_scenarios.py

# Generate scenarios + smoke-test mock agent with first scenario
python test_scenarios.py --agent

# Smoke-test mock agent standalone
python src/mock_agent.py

# SAM commands (for later sprints)
sam validate --lint
sam build
sam local start-api
sam deploy --guided
```

## Environment Variables Needed
| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Google Gemini API key (free tier — https://aistudio.google.com/app/apikey) |
| `AWS_REGION` | AWS region for DynamoDB / Lambda |
| `BASELINES_TABLE` | DynamoDB table name for baselines (set automatically by SAM) |
| `SESSIONS_TABLE` | DynamoDB table name for session scores (set automatically by SAM) |

## Project Structure
```
AIVAR_PROJ/
├── BUILD_LOG.md
├── template.yaml
├── requirements.txt
├── .env.example
├── .env                          # (gitignored — real keys)
├── .gitignore
├── test_scenarios.py             # Test: generate + print 50 scenarios
├── scenarios_output.json         # Last generated scenario set
└── src/
    ├── gemini_utils.py           # Shared: client, rate limiter, retry
    ├── mock_agent.py             # Target agent: 4 tools + Gemini FC
    ├── scenario_generator.py     # 4-batch scenario generator
    ├── generate_scenarios/
    │   ├── generate_scenarios.py # Lambda handler (placeholder)
    │   └── requirements.txt
    ├── run_baseline/
    │   ├── run_baseline.py       # Lambda handler (placeholder)
    │   └── requirements.txt
    └── score_session/
        ├── score_session.py      # Lambda handler (placeholder)
        └── requirements.txt
```
