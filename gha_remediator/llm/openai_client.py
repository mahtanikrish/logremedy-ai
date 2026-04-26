from __future__ import annotations

import json
import os
from typing import Dict, Any, Optional

from .base import LLMClient, LLMConfig

class OpenAIResponsesClient(LLMClient):
    """OpenAI Responses API client wrapper (official OpenAI Python SDK)."""

    def __init__(self, api_key: Optional[str] = None):
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as e:
            raise RuntimeError("openai package not installed. Run: pip install openai") from e

        self._OpenAI = OpenAI
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.last_response_metadata: Dict[str, Any] = {}

    def generate_json(self, *, system: str, user: str, schema_hint: str, cfg: LLMConfig) -> Dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        self.last_response_metadata = {}

        client = self._OpenAI(api_key=self._api_key)

        instructions = system + "\n\nYou MUST output valid JSON only. No markdown. No extra text."
        input_text = user + "\n\nSchema hint (follow exactly):\n" + schema_hint

        kwargs: Dict[str, Any] = {
            "model": cfg.model,
            "instructions": instructions,
            "input": input_text,
        }
        if cfg.temperature is not None:
            kwargs["temperature"] = cfg.temperature
        if cfg.max_output_tokens is not None:
            kwargs["max_output_tokens"] = cfg.max_output_tokens
        if cfg.reasoning_effort is not None:
            kwargs["reasoning_effort"] = cfg.reasoning_effort

        resp = client.responses.create(**kwargs)
        usage = getattr(resp, "usage", None)
        usage_payload: Dict[str, Any] = {}
        if usage is not None:
            usage_payload = {
                "prompt_tokens": getattr(usage, "input_tokens", None),
                "completion_tokens": getattr(usage, "output_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }
        self.last_response_metadata = {
            "model": cfg.model,
            "usage": usage_payload,
        }
        text = getattr(resp, "output_text", None)
        if text is None:
            text = str(resp)

        return json.loads(text)
