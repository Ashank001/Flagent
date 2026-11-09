"""
app/main.py — FastAPI adapter for Flagent Lambda handlers.

Each route:
  1. Receives the HTTP request via FastAPI
  2. Builds an API-Gateway-proxy-style event dict (same shape Lambda gets)
  3. Calls the existing handler(event, context=None)
  4. Converts the {statusCode, headers, body} response dict to a FastAPI Response

No scoring logic lives here — this is a pure adapter layer.

Environment variables:
  STORAGE          memory | dynamodb | firestore  (default: memory)
  ALLOWED_ORIGINS  comma-separated origins for CORS  (default: *)
  PORT             port for uvicorn  (default: 8000)
"""

import json
import os
import sys

# ---------------------------------------------------------------------------
# Put src/ on the path BEFORE any handler imports so they resolve correctly
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
_SRC = os.path.join(_REPO_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------------
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "*")
_origins: list[str] = (
    ["*"]
    if _raw_origins.strip() == "*"
    else [o.strip() for o in _raw_origins.split(",") if o.strip()]
)

app = FastAPI(title="Flagent", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Content-Type", "x-flagent-key"],
    expose_headers=[],
)

# ---------------------------------------------------------------------------
# Lazy handler imports — imported once at first request to avoid import-time
# side-effects (e.g. boto3 client creation) for unused backends.
# ---------------------------------------------------------------------------
_handlers: dict = {}


def _get_handler(module_path: str, fn_name: str = "handler"):
    """Import a handler module from src/ and cache it."""
    key = module_path
    if key not in _handlers:
        import importlib
        mod = importlib.import_module(module_path)
        _handlers[key] = getattr(mod, fn_name)
    return _handlers[key]


# ---------------------------------------------------------------------------
# Core adapter: build Lambda event → call handler → build FastAPI Response
# ---------------------------------------------------------------------------
async def _call_handler(
    handler_fn,
    request: Request,
    path_params: dict | None = None,
) -> Response:
    """
    Convert a FastAPI Request into an API-Gateway-proxy-style event dict,
    call the Lambda handler, and return a FastAPI Response.
    """
    raw_body = await request.body()
    body_str = raw_body.decode("utf-8") if raw_body else "{}"

    # API Gateway proxy event shape
    event = {
        "httpMethod": request.method,
        "path": request.url.path,
        "pathParameters": path_params or {},
        "queryStringParameters": dict(request.query_params) or None,
        "headers": dict(request.headers),  # FastAPI gives lowercase keys
        "body": body_str,
        "isBase64Encoded": False,
        "requestContext": {},
    }

    result = handler_fn(event, context=None)

    status_code = result.get("statusCode", 200)
    headers = result.get("headers", {})
    body = result.get("body", "")

    # Determine content-type for the response
    content_type = headers.get("Content-Type", headers.get("content-type", "application/json"))

    return Response(
        content=body,
        status_code=status_code,
        headers={k: v for k, v in headers.items()},
        media_type=content_type,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check — used by Render and docker-compose."""
    return {
        "status": "ok",
        "storage": os.environ.get("STORAGE", "memory"),
    }


@app.post("/generate-scenarios")
async def generate_scenarios(request: Request):
    fn = _get_handler("generate_scenarios.generate_scenarios")
    return await _call_handler(fn, request)


@app.post("/run-baseline")
async def run_baseline(request: Request):
    fn = _get_handler("run_baseline.run_baseline")
    return await _call_handler(fn, request)


@app.post("/score-session")
async def score_session(request: Request):
    fn = _get_handler("score_session.score_session")
    return await _call_handler(fn, request)


@app.post("/run-demo")
async def run_demo(request: Request):
    fn = _get_handler("run_demo.run_demo")
    return await _call_handler(fn, request)


@app.post("/agents/register")
async def register_agent(request: Request):
    fn = _get_handler("register_agent.register_agent")
    return await _call_handler(fn, request)


@app.post("/agents/{agent_id}/baseline")
async def record_baseline(agent_id: str, request: Request):
    fn = _get_handler("record_baseline.record_baseline")
    return await _call_handler(fn, request, path_params={"agent_id": agent_id})


# ---------------------------------------------------------------------------
# Entry point for local development (outside Docker)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)

