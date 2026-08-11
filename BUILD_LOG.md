# Build Log — PS-4.1 Agent Behavioral Baseline Builder

## Current Status
**Sprint 1 — Scaffold complete.** SAM project structure created with 3 placeholder Lambda functions, 2 DynamoDB tables, API Gateway. LLM provider: **Google Gemini (free tier)**. Not yet deployed. Next task: implement `generate-scenarios` Lambda with Gemini API integration.

## Architecture Decisions
- **Google Gemini (free tier)** as LLM provider — using `google-genai` Python SDK. No billing or credit card required. Chosen over Anthropic/OpenAI to stay on free tier.
- **AWS SAM** for IaC — single `template.yaml` defines all resources; deploys via `sam build && sam deploy --guided` locally (no CloudShell).
- **Python 3.12** Lambda runtime — latest SAM-supported version; good google-genai SDK support.
- **PAY_PER_REQUEST** DynamoDB billing — avoids provisioned capacity costs during development; switch to provisioned for production if needed.
- **Per-function `requirements.txt`** — each Lambda in `src/<function>/` has its own `requirements.txt` so SAM builds isolated packages. Avoids bloated deployment zips.
- **API Gateway (SAM explicit)** — using `AWS::Serverless::Api` with named stage `dev` for a stable endpoint URL.
- **GEMINI_API_KEY as env var** — passed to Lambdas at runtime. Stored in `.env` locally (gitignored), will need to be set as a Lambda env var or SSM parameter for deployment.

## Completed Components
- [x] `BUILD_LOG.md` — `/BUILD_LOG.md` — Persistent build log. Tested: N/A
- [x] `template.yaml` — `/template.yaml` — SAM template: 3 Lambdas, 2 DynamoDB tables, 1 API Gateway. Tested: N (not yet deployed)
- [x] `generate_scenarios.py` — `/src/generate_scenarios/generate_scenarios.py` — Placeholder handler for POST /generate-scenarios. Tested: N
- [x] `run_baseline.py` — `/src/run_baseline/run_baseline.py` — Placeholder handler for POST /run-baseline. Tested: N
- [x] `score_session.py` — `/src/score_session/score_session.py` — Placeholder handler for POST /score-session. Tested: N
- [x] `requirements.txt` — `/requirements.txt` — Top-level Python deps (boto3, google-genai, python-dotenv)
- [x] `.env.example` — `/.env.example` — Template for required environment variables
- [x] `.gitignore` — `/.gitignore` — Excludes .env, __pycache__, .aws-sam, samconfig.toml

## Known Issues / TODO
- [ ] Implement `generate-scenarios` Lambda — Gemini-powered scenario generation (Sprint 2)
- [ ] Implement `run-baseline` Lambda — execute agent against scenarios, record fingerprint (Sprint 3)
- [ ] Implement `score-session` Lambda — compare production sessions against baseline (Sprint 4)
- [ ] Add baseline drift detector logic
- [ ] Add per-cluster baselines (bonus)
- [ ] Run `sam build && sam deploy --guided` (final sprint)

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
# Validate the SAM template
sam validate --lint

# Build all functions
sam build

# Start local API for testing (requires Docker)
sam local start-api

# Invoke a single function locally
sam local invoke GenerateScenariosFunction --event events/generate_scenarios.json

# Deploy (first time — guided creates samconfig.toml)
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
├── .gitignore
└── src/
    ├── generate_scenarios/
    │   ├── generate_scenarios.py
    │   └── requirements.txt
    ├── run_baseline/
    │   ├── run_baseline.py
    │   └── requirements.txt
    └── score_session/
        ├── score_session.py
        └── requirements.txt
```
