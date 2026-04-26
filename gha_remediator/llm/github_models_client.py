from __future__ import annotations
import json
import os
import re
from typing import Any, Dict

import requests

from .base import LLMClient, LLMConfig


class GitHubModelsClient(LLMClient):
    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN not set")

        self.base = os.environ.get("GITHUB_MODELS_BASE", "https://models.inference.ai.azure.com")
        self.api_version = os.environ.get("GITHUB_MODELS_API_VERSION", "2024-02-15-preview")
        self.last_response_metadata: Dict[str, Any] = {}

    @staticmethod
    def _use_modern_endpoint(model: str) -> bool:
        return "/" in model

    @staticmethod
    def _coerce_content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict):
                    if "text" in item and isinstance(item["text"], str):
                        chunks.append(item["text"])
                    elif item.get("type") == "text" and isinstance(item.get("content"), str):
                        chunks.append(item["content"])
                elif isinstance(item, str):
                    chunks.append(item)
            return "\n".join(chunks).strip()
        return str(content).strip()

    @staticmethod
    def _extract_json_text(text: str) -> str:
        s = text.strip()
        if not s:
            raise RuntimeError("LLM returned empty content.")

        # Strip markdown fences if present.
        if s.startswith("```"):
            s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
            s = re.sub(r"\s*```$", "", s)
            s = s.strip()

        # Fast path.
        try:
            json.loads(s)
            return s
        except Exception:
            pass

        # Find first JSON object/array in mixed text.
        starts = [i for i in (s.find("{"), s.find("[")) if i != -1]
        if not starts:
            raise RuntimeError(f"LLM did not return JSON. Raw output head: {s[:220]!r}")

        decoder = json.JSONDecoder()
        for start in sorted(starts):
            try:
                _, end = decoder.raw_decode(s[start:])
                return s[start : start + end]
            except Exception:
                continue

        raise RuntimeError(f"Unable to parse JSON from model output. Raw output head: {s[:220]!r}")

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema_hint: str,
        cfg: LLMConfig,
    ) -> Dict[str, Any]:
        self.last_response_metadata = {}

        deployment = cfg.model or "gpt-4o-mini"
        request_user = (
            user
            + "\n\nYou MUST output valid JSON only.\n"
            + "Schema:\n"
            + schema_hint
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": request_user},
        ]
        temperature = cfg.temperature if cfg.temperature is not None else 0

        if self._use_modern_endpoint(deployment):
            base = os.environ.get("GITHUB_MODELS_BASE", "https://models.github.ai/inference").rstrip("/")
            url = f"{base}/chat/completions"
            headers = {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            }
            payload = {
                "model": deployment,
                "messages": messages,
                "temperature": temperature,
            }
            if cfg.max_output_tokens is not None:
                payload["max_tokens"] = cfg.max_output_tokens
            if cfg.reasoning_effort is not None:
                payload["reasoning_effort"] = cfg.reasoning_effort
        else:
            url = (
                f"{self.base}/openai/deployments/{deployment}/chat/completions"
                f"?api-version={self.api_version}"
            )
            headers = {
                "api-key": self.token,
                "Content-Type": "application/json",
            }
            payload = {
                "model": deployment,
                "messages": messages,
                "temperature": temperature,
            }
            if cfg.max_output_tokens is not None:
                payload["max_tokens"] = cfg.max_output_tokens

        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()

        data = r.json()
        usage = data.get("usage")
        usage_payload: Dict[str, Any] = {}
        if isinstance(usage, dict):
            usage_payload = {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
        self.last_response_metadata = {
            "model": deployment,
            "endpoint": "modern" if self._use_modern_endpoint(deployment) else "legacy",
            "usage": usage_payload,
        }
        content = data["choices"][0]["message"]["content"]
        text = self._coerce_content_to_text(content)
        json_text = self._extract_json_text(text)

        return json.loads(json_text)
