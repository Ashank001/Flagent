# Flagent — Agent Behavioral Baseline Monitor · PS-4.1

> A governance layer that automatically establishes an AI agent's behavioral baseline and monitors production sessions for anomalies and drift.

---

## What It Does

Flagent is **not an agent itself** — it is an observability and governance layer that wraps any existing agent. It generates 50 synthetic baseline sessions at deployment time, computes a statistical behavioral fingerprint (tool-call distribution, bigram sequences, volume patterns, response length), and scores every live production session against that fingerprint in real-time. Sessions that deviate significantly trigger tiered alerts (normal → warning → 🚨 alert), and a rolling-average drift detector flags when the agent's behavior has fundamentally shifted over time.

---

## Architecture

```
Browser / Client
      │
      ▼
 API Gateway  (ps41-baseline-api · ap-south-1)
      │
      ├── POST /generate-scenarios ──► Lambda: ps41-generate-scenarios
      │                                         └── Gemini (free tier) → 50 synthetic scenarios
      │
      ├── POST /run-baseline ─────────► Lambda: ps41-run-baseline
      │                                         └── mock_agent × 50 → fingerprint → DynamoDB: AgentBaselines
      │
      └── POST /score-session ────────► Lambda: ps41-score-session
                                                └── deviation_scorer → DynamoDB: SessionScores
                                                    (Cosine 20% · Bigram 20% · Volume 45% · Length 15%)
```

**Key components:** AWS Lambda · API Gateway · DynamoDB · Google Gemini (free tier) · AWS SAM

---

## Live Demo

| | Link |
|--|------|
| 🚀 **AWS Live App** | [https://staging.d1bxsdy33ywxqy.amplifyapp.com/dashboard.html](https://staging.d1bxsdy33ywxqy.amplifyapp.com/dashboard.html) |
| 🐙 **GitHub Pages mirror** | [https://Ashank001.github.io/Flagent/dashboard.html](https://Ashank001.github.io/Flagent/dashboard.html) |

1. Open either link above in Chrome/Edge.
2. Click **"Run Full Demo"** in the *Live Governance Demo* section.
3. Watch three scenarios execute sequentially against the live API:
   - **Test 1** (normal order lookup) → NORMAL
   - **Test 2** (multi-tool session) → WARNING
   - **Test 3** (mass refund loop × 12 calls) → 🚨 ALERT

The dashboard calls the live deployed AWS API (`t2xtoo4zpg.execute-api.ap-south-1.amazonaws.com/dev`) in real-time — no login or local setup required.

---

## Deployment

### Prerequisites
- AWS CLI configured (`aws configure`)
- AWS SAM CLI installed
- Python 3.12
- A Gemini API key from [aistudio.google.com](https://aistudio.google.com/app/apikey) — **free tier, ~1 500 tokens/min limit; the rate limiter in `gemini_utils.py` handles this automatically with batching and back-off**

### Steps

```bash
# 1. Clone and set your API key
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=your_key_here

# 2. Build the SAM application
sam build

# 3. Deploy (first time — interactive)
sam deploy --guided
#  Stack Name:               flagent
#  AWS Region:               ap-south-1
#  Parameter GeminiApiKey:  [paste your key]
#  Confirm IAM role creation: Y
#  Save to samconfig.toml:   Y

# Subsequent deployments (uses saved config)
sam deploy
```

SAM outputs the `ApiEndpoint` URL on completion. Export it for testing:

```powershell
$env:API_URL = "https://<YOUR-API-ID>.execute-api.ap-south-1.amazonaws.com/dev"
```

---

## Verification

### 1. Automated validation suite — hits the live `/score-session` endpoint

```bash
# Windows PowerShell (set UTF-8 for emoji output)
$env:PYTHONUTF8 = "1"
python validate.py
```

**Expected output:**

```
============================================================
 FINAL SUMMARY TABLE
============================================================
 Section 1 (Normal):    5/5 passed (100%)
 Section 2 (Warning):   3/3 passed (100%)
 Section 3 (Alert):     3/3 passed (100%)
------------------------------------------------------------
 Total Passed:          11 / 11 (100.0%)
 SUCCESS CRITERIA:      MET
============================================================
```

### 2. Governance middleware / interceptor pattern

```bash
python agent_interceptor.py
```

**Expected output (3 sequential tests):**

```
[Test 1] simple order lookup  → Score: ~2–8    | Class: NORMAL
[Test 2] multi-tool session   → Score: ~30–55  | Class: WARNING
[Test 3] 12-call refund loop  → Score: >60     | Class: ALERT  🚨 GOVERNANCE ALERT
```

This proves Flagent works as **pluggable enterprise middleware** — it wraps any Python agent function, intercepts the tool-call trace, posts it to the scoring API, and returns the classification before the caller receives the result.

---

## PS-4.1 Success Criteria Checklist

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | **Automatic baseline generation** — given an agent's system prompt and tool list, generate 50 diverse synthetic scenarios and record behavioral fingerprint | ✅ | `validate.py` 11/11 · `BUILD_LOG.md §Verification` |
| 2 | **Tiered anomaly scoring** — evaluate tool-call sequences and output a score classifying sessions as normal / warning / alert | ✅ | `validate.py` Sections 1–3 (100%) · `BUILD_LOG.md §BUG-002` |
| 3 | **Baseline drift detection** — identify when an agent's behavior has fundamentally shifted from its established baseline | ✅ | `BUILD_LOG.md §Drift Verification` · `real_drift_test.py` (alert at Session 8) |

Full raw test output and calibration reasoning: [`BUILD_LOG.md`](BUILD_LOG.md)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM | Google Gemini (free tier) — `gemini-2.0-flash` with `gemini-2.0-flash-lite` fallback |
| Compute | AWS Lambda (Python 3.12, 3 functions) |
| Storage | AWS DynamoDB (`AgentBaselines`, `SessionScores`) — PAY_PER_REQUEST |
| API | AWS API Gateway — REST, stage: `dev` |
| IaC | AWS SAM (single `template.yaml`) |
| Scoring | 4-component deviation scorer: Cosine Distance · Bigram Novelty · Volume Anomaly · Length Z-score |
| Dashboard | Vanilla HTML/CSS/JS (`dashboard.html`) — no build step, opens directly in browser |

> **Gemini quota note:** The free tier limit is ~1 500 tokens/min. `gemini_utils.py` handles this with 4-batch generation and exponential back-off retry — no manual intervention needed for normal operation.
