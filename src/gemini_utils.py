"""
gemini_utils.py — Shared Gemini client utilities

Provides:
- create_client(): initialises google-genai Client from env
- rate_limited_generate(): wrapper with 4s sleep between calls + retry on 429
"""

import os
import time
import json

from google import genai
from google.genai import types


# ---------------------------------------------------------------------------
# Rate-limiter state (module-level singleton)
# ---------------------------------------------------------------------------
_last_call_time: float = 0.0
_MIN_INTERVAL_SECONDS: float = 4.5  # ~13 calls/min, safely under 15 RPM cap


def create_client() -> genai.Client:
    """Create a Gemini client from the GEMINI_API_KEY env var."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Copy .env.example → .env and add your key."
        )
    return genai.Client(api_key=api_key)


def rate_limited_generate(
    client: genai.Client,
    *,
    model: str = "gemini-3.6-flash",
    contents,
    config: types.GenerateContentConfig | None = None,
) -> object:
    """
    Call client.models.generate_content with:
      1. Rate limiting — waits so calls are ≥4.5 s apart (15 RPM cap safe).
      2. Retry-on-429 — if we get a 429, wait 20 s and retry once.

    Returns the GenerateContentResponse.
    """
    global _last_call_time

    # ---- rate-limit wait ----
    elapsed = time.time() - _last_call_time
    if elapsed < _MIN_INTERVAL_SECONDS:
        sleep_for = _MIN_INTERVAL_SECONDS - elapsed
        print(f"  [rate-limit] sleeping {sleep_for:.1f}s …")
        time.sleep(sleep_for)

    # ---- first attempt ----
    try:
        _last_call_time = time.time()
        kwargs = {"model": model, "contents": contents}
        if config is not None:
            kwargs["config"] = config
        response = client.models.generate_content(**kwargs)
        return response
    except Exception as exc:
        if _is_rate_limit_error(exc):
            print("  [rate-limit] 429 received — backing off 20 s …")
            time.sleep(20)
            _last_call_time = time.time()
            response = client.models.generate_content(**kwargs)
            return response
        raise


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check whether an exception is a 429 / rate-limit error."""
    exc_str = str(exc).lower()
    return "429" in exc_str or "rate" in exc_str or "resource_exhausted" in exc_str
