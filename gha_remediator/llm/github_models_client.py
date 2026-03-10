from __future__ import annotations
import os, json
import requests
from typing import Dict, Any

from .base import LLMClient, LLMConfig


class GitHubModelsClient(LLMClient):
    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN not set")

        self.base = "https://models.inference.ai.azure.com"
        self.api_version = "2024-02-15-preview"

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

        return json.loads(content)