from __future__ import annotations

from typing import Any, Mapping, Sequence


def build_capability(
    *,
    selected_validator: str,
    selection_reason: str,
    matching_validators: Sequence[str] | None = None,
    suppressed_validators: Sequence[str] | None = None,
    availability: str,
    outcome: str,
    summary: str,
    execution_mode: str,
    fallback_used: bool,
) -> dict[str, Any]:
    return {
        "selected_validator": selected_validator,
        "selection_reason": selection_reason,
        "matching_validators": list(matching_validators or []),
        "suppressed_validators": list(suppressed_validators or []),
        "availability": availability,
        "outcome": outcome,
        "summary": summary,
        "execution_mode": execution_mode,
        "fallback_used": fallback_used,
    }


def early_exit_capability(
    *,
    summary: str,
    outcome: str = "rejected",
    selected_validator: str = "none",
    selection_reason: str = "verification terminated before validator selection",
    execution_mode: str = "deterministic",
) -> dict[str, Any]:
    return build_capability(
        selected_validator=selected_validator,
        selection_reason=selection_reason,
        matching_validators=[],
        suppressed_validators=[],
        availability="not_needed",
        outcome=outcome,
        summary=summary,
        execution_mode=execution_mode,
        fallback_used=False,
    )


def capability_from_selection(
    selection: Mapping[str, Any],
    *,
    availability: str,
    outcome: str,
    summary: str,
    execution_mode: str,
    fallback_used: bool = False,
) -> dict[str, Any]:
    return build_capability(
        selected_validator=str(selection.get("name", "none")),
        selection_reason=str(selection.get("reason", "")),
        matching_validators=selection.get("matching_validators", []),
        suppressed_validators=selection.get("suppressed_validators", []),
        availability=availability,
        outcome=outcome,
        summary=summary,
        execution_mode=execution_mode,
        fallback_used=fallback_used,
    )
