"""
gemini_utils.py — Shared Gemini client utilities

Provides:
- create_client(): initialises google-genai Client from env
- rate_limited_generate(): wrapper with rate limiting, model rotation,
  and smart retry-on-429 (parses retry delay from error response)

Gemini free-tier limits (per model):
  - 15 requests per minute (RPM)
  - 20 requests per day per model (RPD)

To work within the 20 RPD/model limit, we rotate across multiple available
models. With 3 models this gives us ~60 calls/day.
"""

import os
import re
import time
import json

from google import genai
from google.genai import types


# ---------------------------------------------------------------------------
# Rate-limiter state (module-level singleton)
# ---------------------------------------------------------------------------
_last_call_time: float = 0.0
_MIN_INTERVAL_SECONDS: float = 4.5  # ~13 calls/min, safely under 15 RPM cap

# Model rotation — spread calls across models to bypass 20 RPD/model limit
# Each model has its own daily quota; rotating triples effective quota.
_MODEL_POOL = [
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
]
_model_index: int = 0
_model_call_counts: dict[str, int] = {m: 0 for m in _MODEL_POOL}

# Max retries on 429 with parsed delay
_MAX_RETRIES = 3


def create_client() -> genai.Client:
    """Create a Gemini client from the GEMINI_API_KEY env var."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Copy .env.example -> .env and add your key."
        )
    return genai.Client(api_key=api_key)


def _pick_next_model(preferred: str | None = None) -> str:
    """
    Pick the next model from the pool using round-robin rotation.
    If a preferred model is given and it's in the pool, use it but still
    advance the rotation counter.
    """
    global _model_index

    if preferred and preferred not in _MODEL_POOL:
        # If caller specified a model outside the pool, just use it
        return preferred

    model = _MODEL_POOL[_model_index % len(_MODEL_POOL)]
    _model_index += 1
    return model


def _parse_retry_delay(exc: Exception) -> float | None:
    """Extract the retry delay in seconds from a Gemini 429 error."""
    exc_str = str(exc)
    # Look for "Please retry in Xs" or "retryDelay": "Ns"
    match = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", exc_str, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(r"retryDelay.*?(\d+)\s*s", exc_str, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check whether an exception is a 429 / rate-limit error."""
    exc_str = str(exc).lower()
    return "429" in exc_str or "resource_exhausted" in exc_str or "rate" in exc_str


def _is_daily_quota_error(exc: Exception) -> bool:
    """Check if the error is specifically a daily quota exhaustion."""
    exc_str = str(exc).lower()
    return "per_day" in exc_str or "perday" in exc_str or "daily" in exc_str


def rate_limited_generate(
    client: genai.Client,
    *,
    model: str | None = None,
    contents,
    config: types.GenerateContentConfig | None = None,
) -> object:
    """
    Call client.models.generate_content with:
      1. Rate limiting — waits so calls are >= 4.5s apart (15 RPM safe).
      2. Model rotation — cycles through _MODEL_POOL to spread daily quota.
      3. Smart retry — on 429, parse the retry delay, wait, try next model.

    Args:
        client: Gemini client instance
        model:  Override model name (None = auto-rotate from pool)
        contents: The prompt/contents to send
        config: Optional GenerateContentConfig

    Returns the GenerateContentResponse.
    """
    global _last_call_time

    # Pick model (rotate if none specified)
    use_model = model if model else _pick_next_model()

    for attempt in range(_MAX_RETRIES + 1):
        # ---- rate-limit wait ----
        elapsed = time.time() - _last_call_time
        if elapsed < _MIN_INTERVAL_SECONDS:
            sleep_for = _MIN_INTERVAL_SECONDS - elapsed
            time.sleep(sleep_for)

        # ---- attempt the call ----
        try:
            _last_call_time = time.time()
            kwargs = {"model": use_model, "contents": contents}
            if config is not None:
                kwargs["config"] = config

            response = client.models.generate_content(**kwargs)
            _model_call_counts[use_model] = _model_call_counts.get(use_model, 0) + 1
            return response

        except Exception as exc:
            if not _is_rate_limit_error(exc):
                raise  # Not a rate-limit error — re-raise immediately

            # Parse how long to wait
            retry_delay = _parse_retry_delay(exc) or 30.0

            if attempt < _MAX_RETRIES:
                # Try switching to a different model
                old_model = use_model
                use_model = _pick_next_model()
                if use_model == old_model and len(_MODEL_POOL) > 1:
                    use_model = _pick_next_model()  # skip to next

                wait_time = min(retry_delay + 5, 120)  # cap at 2 min
                print(
                    f"  [rate-limit] 429 on {old_model} "
                    f"(attempt {attempt + 1}/{_MAX_RETRIES + 1}) "
                    f"-- switching to {use_model}, waiting {wait_time:.0f}s ..."
                )
                time.sleep(wait_time)
            else:
                # All retries exhausted
                print(
                    f"  [rate-limit] All {_MAX_RETRIES + 1} attempts failed. "
                    f"Daily quota likely exhausted for all models."
                )
                print(f"  [rate-limit] Model call counts: {_model_call_counts}")
                raise


def get_model_stats() -> dict:
    """Return current call counts per model (for diagnostics)."""
    return dict(_model_call_counts)
