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

        self.base = "https://models.inference.ai.azure.com"
        self.api_version = "2024-02-15-preview"

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

        deployment = cfg.model or "gpt-4o-mini"

        url = (
            f"{self.base}/openai/deployments/{deployment}/chat/completions"
            f"?api-version={self.api_version}"
        )

        payload = {
            "model": deployment,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        user
                        + "\n\nYou MUST output valid JSON only.\n"
                        + "Schema:\n"
                        + schema_hint
                    ),
                },
            ],
            "temperature": cfg.temperature or 0,
        }
        if cfg.max_output_tokens is not None:
            payload["max_tokens"] = cfg.max_output_tokens

        headers = {
            "api-key": self.token,          
            "Content-Type": "application/json",
        }

        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()

        data = r.json()
        content = data["choices"][0]["message"]["content"]
        text = self._coerce_content_to_text(content)
        json_text = self._extract_json_text(text)

        return json.loads(json_text)
