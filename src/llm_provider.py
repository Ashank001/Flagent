"""
llm_provider.py — Clean LLM Provider Interface

Abstracts LLM calls behind a provider interface so the system is not locked
to any single vendor.  The provider and model name are read from environment
variables; the code never hardcodes a model string.

Supported providers:
  - gemini (default): Google Gemini via the google-genai SDK

Environment variables:
  - LLM_PROVIDER:   "gemini" (default)
  - LLM_MODEL:      e.g. "gemini-2.0-flash" (default)
  - GEMINI_API_KEY:  required when LLM_PROVIDER=gemini
"""

import os
import json
import abc


class LLMProvider(abc.ABC):
    """Abstract base for LLM text-generation providers."""

    @abc.abstractmethod
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate text from a prompt.  Returns the response text."""
        ...


class GeminiProvider(LLMProvider):
    """Google Gemini provider using the google-genai SDK."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model or os.environ.get("LLM_MODEL", "gemini-2.0-flash")

        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set.  "
                "Set it as an environment variable or pass api_key explicitly."
            )

        from google import genai  # lazy import — not needed for BYO-scenario path

        self.client = genai.Client(api_key=self.api_key)

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system_prompt if system_prompt else None,
            temperature=0.7,
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        return response.text


def get_provider() -> LLMProvider:
    """Factory: return the configured LLM provider instance.

    Reads LLM_PROVIDER env var (default "gemini") and instantiates the
    corresponding class.
    """
    provider_name = os.environ.get("LLM_PROVIDER", "gemini").lower()

    if provider_name == "gemini":
        return GeminiProvider()
    else:
        raise ValueError(
            f"Unsupported LLM_PROVIDER: '{provider_name}'.  "
            f"Supported: gemini"
        )
