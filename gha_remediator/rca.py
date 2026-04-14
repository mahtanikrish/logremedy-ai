from __future__ import annotations

from typing import List, Optional, Dict, Any

from .types import RCAReport, LogLine
from .classifier import classify_failure
from .preprocess import key_log_filter, key_log_expand, token_overflow_prune, PreprocessConfig
from .logs import to_lines, build_success_templates
from .llm.base import LLMClient, LLMConfig
from . import prompts


def normalise_confidence(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalise_line_numbers(values: Any) -> List[int]:
    if not isinstance(values, list):
        return []
    out: List[int] = []
    for value in values:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


def normalise_notes(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value).strip()]


def normalise_root_cause_label(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    out: List[str] = []
    last_was_sep = False
    for char in text:
        if char.isalnum():
            out.append(char)
            last_was_sep = False
        else:
            if not last_was_sep:
                out.append("_")
                last_was_sep = True
    normalized = "".join(out).strip("_")
    return normalized or None


def normalise_root_cause_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def merge_root_cause_texts(primary_text: Optional[str], causes: List[str]) -> List[str]:
    merged: List[str] = []
    for value in [primary_text, *causes]:
        text = normalise_root_cause_text(value)
        if text and text not in merged:
            merged.append(text)
    return merged

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


def heuristic_root_cause_label(failure_class: str, key_lines: List[LogLine]) -> str:
    text = "\n".join(l.text for l in key_lines).lower()
    if failure_class == "environment_dependency_failure":
        if "no module named" in text or "modulenotfounderror" in text:
            return "missing_python_dependency"
        if "pnpm" in text and ("not found" in text or "command not found" in text):
            return "missing_pnpm_in_ci_environment"
        if "could not find a version" in text or "no matching distribution" in text:
            return "dependency_resolution_failure"
        return "environment_dependency_failure"
    if failure_class == "workflow_configuration_error":
        return "workflow_configuration_error"
    if failure_class == "build_failure":
        if "black" in text and "would reformat" in text:
            return "black_formatting_violation"
        if "prettier" in text and "code style issues found" in text:
            return "prettier_formatting_violation"
        if "codespell" in text:
            return "codespell_violation"
        if "clang-tidy" in text and "narrowing conversion" in text:
            return "clang_tidy_narrowing_conversion"
        return "build_failure"
    if failure_class == "test_failure":
        return "test_failure"
    if failure_class == "infrastructure_failure":
        return "infrastructure_failure"
    return "unknown_root_cause"

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
        root_cause_text = causes[0] if causes else None
        root_cause_label = heuristic_root_cause_label(failure_class, key_lines[:50])
        meta["rca_mode"] = "heuristic"
        return RCAReport(
            failure_class=failure_class,
            key_lines=key_lines[:200],
            blocks=blocks,
            root_causes=causes,
            root_cause_label=root_cause_label,
            root_cause_text=root_cause_text,
            confidence=None,
            evidence_line_numbers=[],
            notes=[],
            metadata=meta,
        )

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
    root_cause_label = normalise_root_cause_label(out.get("root_cause_label"))
    root_cause_text = normalise_root_cause_text(out.get("root_cause_text"))
    causes = [normalise_root_cause_text(x) for x in out.get("root_causes", [])]
    causes = [x for x in causes if x][:5]
    causes = merge_root_cause_texts(root_cause_text, causes) or ["(LLM did not provide root_causes)"]
    if root_cause_text is None and causes:
        root_cause_text = causes[0]
    confidence = normalise_confidence(out.get("confidence"))
    evidence_line_numbers = normalise_line_numbers(out.get("evidence_line_numbers"))
    notes = normalise_notes(out.get("notes"))
    meta["rca_mode"] = "llm"
    meta["root_cause_label"] = root_cause_label
    meta["root_cause_text"] = root_cause_text
    meta["llm_confidence"] = confidence
    meta["evidence_line_numbers"] = evidence_line_numbers
    meta["notes"] = notes

    return RCAReport(
        failure_class=failure_class,
        key_lines=key_lines[:200],
        blocks=blocks,
        root_causes=causes,
        root_cause_label=root_cause_label,
        root_cause_text=root_cause_text,
        confidence=confidence,
        evidence_line_numbers=evidence_line_numbers,
        notes=notes,
        metadata=meta,
    )
