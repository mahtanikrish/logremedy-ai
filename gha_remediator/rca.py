from __future__ import annotations

from typing import List, Optional, Dict, Any

from .types import RCAReport, LogLine
from .classifier import classify_failure
from .preprocess import key_log_filter, key_log_expand, token_overflow_prune, PreprocessConfig
from .logs import to_lines, build_success_templates
from .llm.base import LLMClient, LLMConfig
from . import prompts

def heuristic_root_cause(failure_class: str, key_lines: List[LogLine]) -> List[str]:
    text = "\n".join(l.text for l in key_lines).lower()
    if failure_class == "environment_dependency_failure":
        if "no module named" in text or "modulenotfounderror" in text:
            return ["Missing Python dependency (module import failed)."]
        if "could not find a version" in text or "no matching distribution" in text:
            return ["Python dependency resolution failed (version not available / incompatible)."]
        return ["Environment or dependency setup failed."]
    if failure_class == "workflow_configuration_error":
        return ["GitHub Actions workflow/config invalid (YAML/schema/input mismatch)."]
    if failure_class == "build_failure":
        return ["Build step failed (compiler/typechecker/bundler reported errors)."]
    if failure_class == "test_failure":
        return ["Tests failed (assertion/runner reported failing suite)."]
    if failure_class == "infrastructure_failure":
        return ["Infrastructure/auth failure (permissions/credentials/network)."]
    return ["Unknown root cause (needs investigation)."]

def run_rca(raw_log_text: str, success_log_texts: Optional[List[str]] = None, cfg: PreprocessConfig = PreprocessConfig(), llm: Optional[LLMClient] = None, llm_cfg: Optional[LLMConfig] = None,) -> RCAReport:
    lines = to_lines(raw_log_text)
    failure_class = classify_failure(raw_log_text)

    success_templates = None
    if success_log_texts:
        success_templates = build_success_templates(success_log_texts)

    key_lines = key_log_filter(lines, success_templates=success_templates, cfg=cfg)
    blocks = key_log_expand(lines, key_lines, cfg=cfg)
    blocks = token_overflow_prune(blocks, key_lines, cfg=cfg)

    meta: Dict[str, Any] = {
        "num_lines": len(lines),
        "num_key_lines": len(key_lines),
        "num_blocks": len(blocks),
    }

    if llm is None:
        causes = heuristic_root_cause(failure_class, key_lines[:50])
        meta["rca_mode"] = "heuristic"
        return RCAReport(failure_class=failure_class, key_lines=key_lines[:200], blocks=blocks, root_causes=causes, metadata=meta)

    llm_cfg = llm_cfg or LLMConfig()
    user = (
        f"Predicted failure_class: {failure_class}\n\n"
        f"Curated evidence blocks:\n{prompts.format_blocks(blocks)}"
    )
    out = llm.generate_json(
        system=prompts.RCA_SYSTEM,
        user=user,
        schema_hint=prompts.RCA_SCHEMA_HINT,
        cfg=llm_cfg,
    )
    causes = [str(x) for x in out.get("root_causes", [])][:5] or ["(LLM did not provide root_causes)"]
    meta["rca_mode"] = "llm"
    meta["llm_confidence"] = out.get("confidence")
    meta["evidence_line_numbers"] = out.get("evidence_line_numbers")

    return RCAReport(
        failure_class=failure_class,
        key_lines=key_lines[:200],
        blocks=blocks,
        root_causes=causes,
        metadata=meta,
    )
