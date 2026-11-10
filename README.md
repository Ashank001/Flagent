# Flagent — Agent Behavioral Baseline Monitor · PS-4.1

> A governance layer that automatically establishes an AI agent's behavioral baseline and monitors production sessions for anomalies and drift.

---

## Hosting History and Migration

Flagent was initially engineered and deployed as an AWS serverless architecture (API Gateway + 3 Python Lambda functions + DynamoDB tables + AWS Amplify static hosting). While this architecture served as a high-scalability reference implementation, running multiple AWS managed services incurs ongoing cloud costs and operational friction.

To make Flagent fully accessible, zero-cost, and portable across cloud providers, the project was migrated to a **modular, free-tier-compatible multi-cloud architecture**:

1. **Pluggable Storage Abstraction (`src/storage/`):**
   - Direct `boto3` calls were abstracted into a unified `StorageBackend` contract.
   - Three production-ready backends are supported via the `STORAGE` environment variable:
     - `memory`: Pure in-memory dictionary storage for lightning-fast testing and local development without cloud dependencies.
     - `firestore`: Google Cloud Firestore (Firebase Spark free tier) providing persistent agent profiles, baselines, and session scores at zero cost with in-memory TTL caching.
     - `dynamodb`: AWS DynamoDB backend preserved for backward compatibility.
2. **Containerized FastAPI Adapter (`app/main.py`):**
   - The original Lambda handlers (`run_baseline`, `score_session`, `generate_scenarios`, etc.) are wrapped by a lightweight FastAPI application, exposing the identical REST API contract without changing scoring or governance logic.
   - Packageable as a standard Docker container (`python:3.13-slim`, non-root user).
3. **Free-Tier Cloud Hosting (Render + Firestore):**
   - The containerized backend deploys directly to Render's free Web Service tier using `render.yaml`.
   - Data persists across dyno recycles via Google Cloud Firestore.
4. **Configurable Frontends (`config.js`):**
   - The vanilla dashboards (`dashboard.html` and `dashboard_v2.html`) load `config.js` to dynamically bind to the backend API endpoint (`http://localhost:8000` by default or any deployed Render URL).

---

## Architecture

```
                       ┌──────────────────────────────┐
                       │  Client / SDK / Dashboard   │
                       └──────────────┬───────────────┘
                                      │
                   ┌──────────────────┴──────────────────┐
                   ▼                                     ▼
        ┌─────────────────────┐               ┌─────────────────────┐
        │  AWS API Gateway    │               │   FastAPI Adapter   │
        │  (Legacy Serverless)│               │   (Docker / Render) │
        └──────────┬──────────┘               └──────────┬──────────┘
                   │                                     │
                   ▼                                     ▼
        ┌────────────────────────────────────────────────────────┐
        │                 Core Handler Logic                     │
        │  generate_scenarios · run_baseline · score_session     │
        └──────────────────────────┬─────────────────────────────┘
                                   │
                   ┌───────────────┴───────────────┐
                   ▼                               ▼
        ┌─────────────────────┐         ┌─────────────────────┐
        │    Google Gemini    │         │  Storage Interface  │
        │  (Free Tier Flash)  │         │  (get_storage())    │
        └─────────────────────┘         └──────────┬──────────┘
                                                   │
                ┌───────────────────┬──────────────┴────────────────────┐
                ▼                   ▼                                   ▼
        ┌───────────────┐   ┌───────────────┐                   ┌───────────────┐
        │ In-Memory DB  │   │  GCP Firestore│                   │ AWS DynamoDB  │
        │ (Dev / Tests) │   │ (Free Spark)  │                   │ (Legacy Prod) │
        └───────────────┘   └───────────────┘                   └───────────────┘
```

**Deviation Scoring Engine:** Evaluates tool-call sequences using a 4-component weighted model:
- **Cosine Distance (20%):** Frequency alignment with the established baseline tool distribution.
- **Bigram Novelty (20%):** Penalty for tool transitions unseen during baseline calibration.
- **Volume Anomaly (45%):** Poisson probability of total tool-call volume.
- **Response Length (15%):** Normalized Z-score of assistant output length.

---

## Quick Start (Docker / Local)

### 1. In-Memory Mode (Zero Credentials Required)

Run the backend locally with ephemeral in-memory storage:

```bash
# Build the Docker image
docker build -t flagent:local .

# Run the container
docker run -d --name flagent-app -p 8000:8000 -e STORAGE=memory flagent:local
```

Verify the health check:
```bash
curl http://localhost:8000/health
# {"status":"healthy","storage":"MemoryStorage"}
```

### 2. Firestore Mode (Persistent Free Tier)

1. Create a free Firebase project and generate a Service Account Key JSON.
2. Seed the baseline fingerprint (runs offline, 0 LLM calls, idempotent):
   ```bash
   $env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\service-account.json"
   $env:STORAGE = "firestore"
   python scripts/seed_baseline.py
   ```
3. Run the container mounting your credentials or passing `FIREBASE_SERVICE_ACCOUNT_JSON`:
   ```bash
   docker run -d --name flagent-app -p 8000:8000 \
     -e STORAGE=firestore \
     -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/sa.json \
     -v "C:\path\to\service-account.json:/run/secrets/sa.json:ro" \
     flagent:local
   ```

---

## Deploy on Render

The repository includes a ready-to-use Render Blueprint: [`render.yaml`](render.yaml).

1. Fork or push this repository to GitHub.
2. In the [Render Dashboard](https://dashboard.render.com/), select **New +** → **Blueprint**.
3. Connect your repository. Render will automatically parse `render.yaml`.
4. Fill in the required environment variables marked with `sync: false`:
   - `FIREBASE_SERVICE_ACCOUNT_JSON`: Paste the raw JSON string of your Firebase service account.
   - `GEMINI_API_KEY`: Your Google AI Studio API key.
5. Deploy. Render will build the Docker container and start the service with `/health` monitoring.

---

## Deploy on AWS (SAM)

> [!WARNING]
> **AWS Stack Status:** The original AWS stack in `ap-south-1` (API Gateway, Lambda, DynamoDB, Amplify) has been **decommissioned and is not currently running live**. The SAM packaging configuration (`template.yaml` and `sam build`) has been fully updated and re-verified locally to ensure the canonical baseline fingerprint (`src/data/baseline_output.json`) is packaged properly. Deploying live to AWS requires active AWS credentials and an active AWS subscription.

### Local SAM Packaging & Build Verification

```bash
# Build the SAM application locally
sam build

# Verify packaged assets
dir .aws-sam\build\ScoreSessionFunction\data
```

### Deploying to Your AWS Account

```bash
# Guided deployment
sam deploy --guided
#  Stack Name:               flagent
#  AWS Region:               ap-south-1 (or your preferred region)
#  Parameter GeminiApiKey:   [paste your key]
#  Confirm IAM role creation: Y
#  Save to samconfig.toml:   Y
```

---

## Dashboards & Frontend Configuration

Flagent includes two vanilla HTML/CSS/JavaScript dashboards:
- **`dashboard.html`**: Core governance dashboard with the 3-step live demo (Normal, Warning, Alert).
- **`dashboard_v2.html`**: Enhanced multi-agent governance interface featuring an interactive onboarding wizard, session simulator, and visual drift timeline.

### Configuring the API Endpoint

Both dashboards read their target backend URL from [`config.js`](config.js):

```javascript
// config.js
window.FLAGENT_CONFIG = window.FLAGENT_CONFIG || {};
window.FLAGENT_CONFIG.API_BASE_URL = 'http://localhost:8000'; // Or your deployed Render URL
```

To use:
1. Ensure `config.js` sits in the same directory as the HTML file.
2. Open `dashboard.html` or `dashboard_v2.html` directly in your web browser, or host them on Vercel, Netlify, or GitHub Pages.

---

## v2 Status and Honest Limitations

### Feature Status
- **Multi-Agent Registry:** Implemented. Agents can be registered via `POST /register-agent`, with per-agent metadata and baselines.
- **Deviation Scorer:** Fully calibrated. Tested against normal sessions (score ~2.94), warning sessions (score ~30–55), and adversarial loops (score ~98.04).
- **TTL Caching:** Firestore reads for agent profiles and baseline fingerprints are cached in-memory with configurable TTL (default 300s) to minimize quota consumption.
- **Idempotent Baseline Seeding:** `scripts/seed_baseline.py` allows offline provisioning of the reference `mock-customer-support` agent without LLM dependency.

### Honest Limitations
1. **Render Free Tier Spin-Down:**
   - Free Web Services on Render sleep after 15 minutes of inactivity. Initial wake-up requests may take 30–50 seconds.
2. **Gemini Free Quota Limitations:**
   - Synthetic scenario generation relies on Gemini free tier (`~15 RPM` limit). While `gemini_utils.py` incorporates batching and exponential back-off, concurrent generation requests may experience queueing latency.
3. **Firestore Spark Tier Limits:**
   - Spark tier permits 50,000 document reads and 20,000 document writes daily. The in-memory TTL cache mitigates baseline read amplification, but high-throughput production workloads (>20k sessions/day) require upgrading to Firestore Blaze or deploying on DynamoDB.
4. **Decommissioned AWS Staging Endpoints:**
   - Legacy links pointing to `execute-api.ap-south-1.amazonaws.com` or `amplifyapp.com` in older commits are inactive.

---

## Verification & Automated Test Suites

All tests and validation scripts support dynamic base URLs via the `API_BASE_URL` environment variable (default: `http://localhost:8000`).

### 1. Full Production Validation Suite (`validate.py`)
Hits the live `/score-session` endpoint across 11 test scenarios:
```bash
$env:PYTHONUTF8 = "1"
python validate.py
```
**Expected Output:**
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

### 2. Phase 1 & 2 Storage Contract & Route Verifications
```bash
# Verify Phase 1 storage contracts (re-runnable, unique agent IDs)
python verify_phase1.py

# Verify Phase 2 FastAPI routes and API gateway equivalence
python verify_phase2.py
```

### 3. Unit and SDK Test Suites
```bash
# Storage backend contract tests (Memory backend)
pytest tests/test_storage_contract.py -v

# FastAPI route mapping tests
pytest app/test_routes.py -v

# Flagent Python SDK test suite
pytest flagent-sdk/tests -v
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend Adapter | FastAPI, Uvicorn (Python 3.13) |
| Containerization | Docker (`python:3.13-slim`), non-root execution |
| Cloud Hosting | Render (Web Service Blueprint: `render.yaml`) |
| Storage Backends | In-Memory · Google Cloud Firestore · AWS DynamoDB |
| Scoring Engine | 4-component deviation scorer (Cosine, Bigram, Volume, Length) |
| Synthetic Baselines | Google Gemini (`gemini-2.0-flash` with rate limiting) |
| Dashboards | Vanilla HTML5 / CSS3 / JavaScript + Chart.js (`config.js`) |
