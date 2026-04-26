from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Dict, Any

@dataclass(frozen=True)
class LLMConfig:
    model: str = "gpt-4o-mini"
    reasoning_effort: Optional[str] = None
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = 1200

class LLMClient(Protocol):
    def generate_json(self, *, system: str, user: str, schema_hint: str, cfg: LLMConfig) -> Dict[str, Any]:
        ...


def last_response_metadata(llm: Optional[LLMClient]) -> Dict[str, Any]:
    metadata = getattr(llm, "last_response_metadata", None)
    if isinstance(metadata, dict):
        return dict(metadata)
    return {}
