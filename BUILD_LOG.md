# Build Log — PS-4.1 Agent Behavioral Baseline Builder

## Current Status
**Sprint 2 — Mock agent + scenario generator complete.** 50 diverse synthetic scenarios generated via Gemini 3.6 Flash (free tier). Mock customer-support agent with 4 tools wired to Gemini function calling. Next task: implement baseline recorder (run agent against all 50 scenarios and record behavioural fingerprint).

## Architecture Decisions
- **Google Gemini (free tier)** as LLM provider — using `google-genai` Python SDK. No billing or credit card required.
- **Model: `gemini-3.6-flash`** — `gemini-2.5-flash` is no longer available to new API keys. Discovered via `client.models.list()` and confirmed working. Model names change over time — may need revisiting.
- **Rate limiting** — Gemini free tier capped at 15 RPM. Implemented a module-level rate limiter in `gemini_utils.py`: sleeps 4.5s between calls (~13 RPM, safely under cap). On 429 errors, waits 20s and retries once before failing.
- **Batch scenario generation** — 4 batches of 13 scenarios each (lookup-heavy, refund-heavy, email-heavy, address+multi-tool), then deduped to 50 unique. This produces better variety than a single 50-scenario prompt.
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
- [x] `gemini_utils.py` — `/src/gemini_utils.py` — Shared Gemini client: create_client(), rate_limited_generate() with 4.5s spacing + 429 retry. Tested: Y
- [x] `mock_agent.py` — `/src/mock_agent.py` — Mock customer-support agent with 4 tools (lookup_order, issue_refund, send_email, update_address) wired to Gemini function calling. Returns behavioural metrics per session. Tested: Y (via test_scenarios.py)
- [x] `scenario_generator.py` — `/src/scenario_generator.py` — Generates 50 diverse scenarios in 4 batches via Gemini, dedupes to 50 unique. Tested: Y — produced 50 unique scenarios with good intent distribution
- [x] `test_scenarios.py` — `/test_scenarios.py` — Test script: runs generator, prints all 50 scenarios + intent distribution stats. Optional `--agent` flag smoke-tests mock agent. Tested: Y
- [x] `scenarios_output.json` — `/scenarios_output.json` — Last generated set of 50 scenarios (JSON array). Tested: N/A (output data)

## Known Issues / TODO
- [ ] Implement baseline recorder — run mock agent against all 50 scenarios, record behavioural fingerprint (Sprint 3)
- [ ] Implement session scorer — compare production sessions against baseline (Sprint 4)
- [ ] Add baseline drift detector logic
- [ ] Add per-cluster baselines (bonus)
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
