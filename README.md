# PS-4.1 Agent Behavioral Baseline Builder

This project automatically establishes a behavioral baseline for an AI agent at deployment time using synthetic traffic, then monitors production against it to detect anomalies and baseline drift.

## Deployment Steps

Deploy this project to AWS using the AWS SAM CLI.

1. **Install dependencies and build the SAM application:**
   ```bash
   sam build
   ```
   *Note: If you run into Python runtime issues on Windows, you can add the `--use-container` flag if you have Docker installed, or ensure Python 3.12 is explicitly on your PATH.*

2. **Deploy the application to your AWS account:**
   ```bash
   sam deploy --guided
   ```
   Follow the prompts during the guided deployment.
   - **Stack Name**: `ps41-baseline-builder`
   - **AWS Region**: `ap-south-1` (or your preferred region)
   - **Parameter GeminiApiKey**: `[Enter your Gemini API Key here]`
   - **Confirm changes before deploy**: `Y`
   - **Allow SAM CLI IAM role creation**: `Y`
   - **Disable rollback**: `N`
   - **Save arguments to configuration file**: `Y`

Once deployment is complete, SAM will output the `ApiEndpoint` URL for your API Gateway. Export this URL to your terminal for easy testing:
```bash
$env:API_URL="https://<YOUR-API-ID>.execute-api.ap-south-1.amazonaws.com/dev"
```

---

## Verification Steps (Success Criteria)

Below are the commands to hit each of the 3 API Gateway endpoints, mapped explicitly to the problem statement's success criteria.

### Success Criteria #1: Generate Baselines Automatically
*“Given an agent's system prompt and tool list, automatically generate 50 diverse synthetic test scenarios and record the agent's baseline behaviour...”*

**Step A: Generate Scenarios** (Takes ~30s due to rate limits)
```bash
curl -X POST "$env:API_URL/generate-scenarios"
```

**Step B: Run Baseline & Record Fingerprint** (Takes ~2-3 mins due to rate limits)
```bash
curl -X POST "$env:API_URL/run-baseline"
```
*This saves the statistical fingerprint to the `AgentBaselines` DynamoDB table.*

### Success Criteria #2: Tiered Anomaly Scoring
*“Evaluate new tool-call sequences and output an anomaly score classifying them as normal, warning, or alert.”*

**Step C: Score a Production Session**
```bash
curl -X POST -H "Content-Type: application/json" -d '{"user_message": "Hi, check my order #12345."}' "$env:API_URL/score-session"
```
*This runs the session through the mock agent, calculates the Cosine Distance, Bigram Novelty, and Length Z-Score, outputs the anomaly classification (`NORMAL`, `WARNING`, `ALERT`), and saves the score to the `SessionScores` DynamoDB table.*

### Success Criteria #3: Baseline Drift Detection
*“Identify when a new deployment’s baseline significantly drifts from the previous baseline.”*

We provided a local automated drift simulation script for this criterion that forces a malicious/drifted prompt and evaluates a rolling average. 

Run it locally to verify the alert logic:
```bash
python src/drift_detector.py
```
