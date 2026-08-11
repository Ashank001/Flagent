# Build Log — PS-4.1 Agent Behavioral Baseline Builder

## Current Status
**Sprint 4 — Production Monitor and Drift Detector Complete.** 
- Built `production_monitor.py` which takes a new session, runs it through the target agent, scores it using the baseline fingerprint via `deviation_scorer`, and saves the final result to the `SessionScores` DynamoDB table.
- Added `test_production_monitor.py` with 3 test sessions (NORMAL, WARNING, ALERT) that successfully classify in the correct anomaly tiers.
- Built `drift_detector.py` to simulate a model update (where the agent is overly eager to issue refunds). It tracks a rolling average over 10 sessions and alerts when it crosses a threshold for 3 consecutive sessions.

Next task: Deploy API Gateway and Lambdas via AWS SAM.

## Architecture Decisions
- **Google Gemini (free tier)** as LLM provider — using `google-genai` Python SDK. No billing or credit card required.
- **Model Rotation** — Due to the 20 requests/day/model limit on Gemini free tier, `gemini_utils.py` uses model rotation across 4 models (`gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3-flash-preview`) to get 80+ daily calls. It also parses retry delays from 429 errors for smart backoff.
- **Fingerprint Schema** — Includes:
  - `tool_frequency`: average calls per session for each tool
  - `common_bigrams`: counts of consecutive tool calls across sessions
  - `avg_response_length`: average response length (in words)
  - `std_response_length`: standard deviation of response length
- **Scoring Formula** — 0-100 anomaly score computed from 3 weighted components:
  1. **Cosine distance** (40%): tool-frequency vector vs baseline.
  2. **Bigram novelty** (35%): % of session bigrams NOT in baseline.
  3. **Length z-score** (25%): absolute z-score of session length, capped at 3 and normalized.
  - Classification: <30 = `normal`, 30-70 = `warning`, >70 = `alert`.
- **Production Monitor & DynamoDB** — `production_monitor.py` creates and writes to `SessionScores` with partition key `agent_id` and sort key `session_id`.
- **AWS SAM** for IaC — single `template.yaml` defines all resources; deploys via `sam build && sam deploy --guided` locally (no CloudShell).
- **Python 3.12** Lambda runtime — latest SAM-supported version.
- **PAY_PER_REQUEST** DynamoDB billing — avoids provisioned capacity costs during development.
- **Per-function `requirements.txt`** — each Lambda in `src/<function>/` has its own `requirements.txt` so SAM builds isolated packages.
- **API Gateway (SAM explicit)** — `AWS::Serverless::Api` with stage `dev`.
- **GEMINI_API_KEY as env var** — stored in `.env` locally (gitignored).

## Completed Components
- [x] `BUILD_LOG.md` — `/BUILD_LOG.md` — Persistent build log. Tested: N/A
- [x] `template.yaml` — `/template.yaml` — SAM template: 3 Lambdas, 2 DynamoDB tables, 1 API Gateway. Tested: N (not yet deployed)
- [x] `generate_scenarios.py` — `/src/generate_scenarios/generate_scenarios.py` — Placeholder Lambda handler for POST /generate-scenarios. Tested: N
- [x] `run_baseline.py` — `/src/run_baseline/run_baseline.py` — Placeholder Lambda handler for POST /run-baseline. Tested: N
- [x] `score_session.py` — `/src/score_session/score_session.py` — Placeholder Lambda handler for POST /score-session. Tested: N
- [x] `requirements.txt` — `/requirements.txt` — Top-level Python deps (boto3, google-genai, python-dotenv)
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

## Known Issues / TODO
- [ ] Wire scenario_generator.py logic into the generate-scenarios Lambda handler
- [ ] Run `sam build && sam deploy --guided` (final sprint)
- [ ] Note: `gemini-3.6-flash` model name may change — if API returns 404, re-run model discovery

## AWS Resources Created
| Resource Type | Name | Region | Notes |
|---|---|---|---|
| DynamoDB Table | `AgentBaselines` | (pending deploy) | PK: `agent_id` (S), PAY_PER_REQUEST |
| DynamoDB Table | `SessionScores` | (pending deploy) | PK: `agent_id` (S), SK: `session_id` (S), PAY_PER_REQUEST |
| Lambda Function | `ps41-generate-scenarios` | (pending deploy) | POST /generate-scenarios |
| Lambda Function | `ps41-run-baseline` | (pending deploy) | POST /run-baseline, 300s timeout |
| Lambda Function | `ps41-score-session` | (pending deploy) | POST /score-session |
| API Gateway | `ps41-baseline-api` | (pending deploy) | Stage: dev |

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
