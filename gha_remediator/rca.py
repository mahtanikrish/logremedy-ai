from __future__ import annotations

from typing import List, Optional, Dict, Any

from .types import RCAReport, LogLine, LogBlock
from .classifier import classify_failure
from .preprocess import (
    key_log_filter,
    key_log_expand,
    token_overflow_prune,
    raw_tail_select,
    approx_tokens,
    PreprocessConfig,
)
from .logs import to_lines, build_success_templates
from .llm.base import LLMClient, LLMConfig, last_response_metadata
from . import prompts

WEAK_RCA_LABELS = {
    "unknown",
    "unknown_failure",
    "unknown_root_cause",
    "generic_failure",
    "insufficient_information",
}
WEAK_RCA_PHRASES = (
    "not enough info",
    "not enough information",
    "insufficient info",
    "insufficient information",
    "unknown root cause",
    "needs investigation",
    "unable to determine",
    "cannot determine",
    "unclear from the log",
)


def _is_dependabot_transitive_conflict(text: str) -> bool:
    return (
        "transitive_update_not_possible" in text
        or (
            "dependabot encountered" in text
            and "error performing the update" in text
        )
        or (
            "latest possible version that can be installed is" in text
            and "conflicting dependencies" in text
        )
    )


def _extract_dependabot_target_package(text: str) -> Optional[str]:
    import re

    match = re.search(
        r"checking if\s+([a-z0-9_@./-]+)\s+[0-9][a-z0-9_.-]*\s+needs updating",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return None


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


def _block_tokens(blocks: List[LogBlock]) -> int:
    return sum(approx_tokens(block.to_text()) for block in blocks)


def _block_tokens_for_model(blocks: List[LogBlock], model: Optional[str]) -> int:
    return sum(approx_tokens(block.to_text(), model=model) for block in blocks)


def _prompt_approx_tokens(failure_class: str, blocks: List[LogBlock], model: Optional[str]) -> int:
    user = (
        f"Predicted failure_class: {failure_class}\n\n"
        f"Log evidence blocks:\n{prompts.format_blocks(blocks)}"
    )
    schema = "\n\nYou MUST output valid JSON only.\nSchema:\n" + prompts.RCA_SCHEMA_HINT
    return (
        approx_tokens(prompts.RCA_SYSTEM, model=model)
        + approx_tokens(user, model=model)
        + approx_tokens(schema, model=model)
    )

def _llm_rca_is_weak(
    *,
    failure_class: str,
    root_cause_label: Optional[str],
    root_cause_text: Optional[str],
    causes: List[str],
) -> bool:
    label = (root_cause_label or "").strip().lower()
    text = (root_cause_text or "").strip().lower()
    joined_causes = " ".join(causes).strip().lower()
    if not root_cause_text and not causes:
        return True
    if label in WEAK_RCA_LABELS:
        return True
    if any(phrase in text for phrase in WEAK_RCA_PHRASES):
        return True
    if joined_causes and any(phrase in joined_causes for phrase in WEAK_RCA_PHRASES):
        return True
    if failure_class != "unknown_failure" and text in {"unknown", "unknown failure"}:
        return True
    return False

def heuristic_root_cause(failure_class: str, key_lines: List[LogLine]) -> List[str]:
    text = "\n".join(l.text for l in key_lines).lower()
    if failure_class == "environment_dependency_failure":
        if _is_dependabot_transitive_conflict(text):
            package = _extract_dependabot_target_package(text)
            if package:
                return [
                    f"Dependabot could not update {package} because transitive dependency constraints block the fixed version."
                ]
            return ["Dependabot security update is blocked by transitive dependency constraints."]
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
        if _is_dependabot_transitive_conflict(text):
            return "dependabot_transitive_dependency_conflict"
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


def _heuristic_signal_lines(blocks: List[LogBlock], key_lines: List[LogLine]) -> List[LogLine]:
    if blocks:
        return [line for block in blocks for line in block.lines]
    if len(key_lines) <= 80:
        return key_lines
    return key_lines[-80:]

def run_rca(
    raw_log_text: str,
    success_log_texts: Optional[List[str]] = None,
    cfg: PreprocessConfig = PreprocessConfig(),
    llm: Optional[LLMClient] = None,
    llm_cfg: Optional[LLMConfig] = None,
    preprocessing_mode: str = "curated",
) -> RCAReport:
    llm_cfg = llm_cfg or LLMConfig()
    token_model = llm_cfg.model
    lines = to_lines(raw_log_text)
    failure_class = classify_failure(raw_log_text)

    success_templates = None
    if preprocessing_mode == "curated" and success_log_texts:
        success_templates = build_success_templates(success_log_texts)

    if preprocessing_mode == "raw_tail":
        key_lines = raw_tail_select(lines, cfg=cfg, model=token_model)
        blocks = []
        if key_lines:
            blocks = [LogBlock(start=key_lines[0].lineno, end=key_lines[-1].lineno, lines=key_lines)]
    elif preprocessing_mode == "curated":
        key_lines = key_log_filter(lines, success_templates=success_templates, cfg=cfg)
        blocks = key_log_expand(lines, key_lines, cfg=cfg)
        blocks = token_overflow_prune(blocks, key_lines, cfg=cfg, model=token_model)
    else:
        raise ValueError(f"Unsupported preprocessing_mode: {preprocessing_mode}")

    meta: Dict[str, Any] = {
        "num_lines": len(lines),
        "num_key_lines": len(key_lines),
        "num_blocks": len(blocks),
        "preprocessing_mode": preprocessing_mode,
        "success_log_count": len(success_log_texts or []),
        "raw_log_approx_tokens": approx_tokens(raw_log_text, model=token_model),
        "selected_input_approx_tokens": (
            _block_tokens_for_model(blocks, token_model)
            if blocks
            else approx_tokens("\n".join(l.text for l in key_lines), model=token_model)
        ),
        "curated_input_approx_tokens": _block_tokens_for_model(blocks, token_model) if preprocessing_mode == "curated" else None,
        "prompt_approx_tokens": _prompt_approx_tokens(failure_class, blocks, token_model),
    }
    heuristic_lines = _heuristic_signal_lines(blocks, key_lines)

    if llm is None:
        causes = heuristic_root_cause(failure_class, heuristic_lines)
        root_cause_text = causes[0] if causes else None
        root_cause_label = heuristic_root_cause_label(failure_class, heuristic_lines)
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

    user = (
        f"Predicted failure_class: {failure_class}\n\n"
        f"Log evidence blocks:\n{prompts.format_blocks(blocks)}"
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
    llm_meta = last_response_metadata(llm)
    if llm_meta:
        meta["llm"] = llm_meta

    if _llm_rca_is_weak(
        failure_class=failure_class,
        root_cause_label=root_cause_label,
        root_cause_text=root_cause_text,
        causes=causes,
    ):
        heuristic_causes = heuristic_root_cause(failure_class, heuristic_lines)
        heuristic_text = heuristic_causes[0] if heuristic_causes else None
        heuristic_label = heuristic_root_cause_label(failure_class, heuristic_lines)
        meta["rca_mode"] = "heuristic_fallback_from_llm"
        meta["llm_rca_rejected"] = True
        meta["llm_root_cause_label"] = root_cause_label
        meta["llm_root_cause_text"] = root_cause_text
        meta["llm_root_causes"] = causes
        meta["root_cause_label"] = heuristic_label
        meta["root_cause_text"] = heuristic_text
        meta["llm_confidence_raw"] = confidence
        return RCAReport(
            failure_class=failure_class,
            key_lines=key_lines[:200],
            blocks=blocks,
            root_causes=heuristic_causes,
            root_cause_label=heuristic_label,
            root_cause_text=heuristic_text,
            confidence=None,
            evidence_line_numbers=evidence_line_numbers,
            notes=notes,
            metadata=meta,
        )

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
