from __future__ import annotations

import re
from typing import List, Optional, Sequence

from ..types import LogLine, RCAReport, RemediationPlan, RepoContext

_WEAK_RCA_LABELS = {
    "",
    "unknown",
    "unknown_failure",
    "unknown_root_cause",
    "generic_failure",
    "insufficient_information",
}


def backfill_guidance(
    plan: RemediationPlan,
    report: RCAReport,
    repo_context: Optional[RepoContext] = None,
) -> RemediationPlan:
    if plan.guidance:
        return plan

    guidance = _build_guidance(report, plan, repo_context=repo_context)
    if not guidance:
        return plan

    plan.guidance = guidance
    plan.evidence["guidance_fallback"] = {
        "applied": True,
        "count": len(guidance),
        "source": "heuristic",
    }
    return plan


def _build_guidance(
    report: RCAReport,
    plan: RemediationPlan,
    repo_context: Optional[RepoContext] = None,
) -> List[str]:
    label = (report.root_cause_label or "").strip().lower()
    blob = "\n".join(line.text for line in report.key_lines[:200])
    lowered = blob.lower()

    if report.failure_class == "test_failure":
        return _build_test_failure_guidance(
            report,
            plan,
            repo_context=repo_context,
            label=label,
            blob=blob,
            lowered=lowered,
        )

    if label in _WEAK_RCA_LABELS:
        return []

    guidance = []
    rerun = _rerun_guidance(plan=plan, report=report, blob=blob)
    if report.root_cause_text:
        guidance.append(f"Inspect the failure mechanism described by the RCA: {report.root_cause_text}")
    primary_path = _primary_candidate_path(repo_context)
    if primary_path:
        guidance.append(f"Review `{primary_path}` and the surrounding failure context before applying a fix.")
    if rerun:
        guidance.append(rerun)
    return _dedupe(guidance)


def _build_test_failure_guidance(
    report: RCAReport,
    plan: RemediationPlan,
    *,
    repo_context: Optional[RepoContext],
    label: str,
    blob: str,
    lowered: str,
) -> List[str]:
    guidance: List[str] = []
    actual_expected = _extract_assertion_pair(blob)
    assertion_location = _assertion_location(repo_context)
    primary_path = _primary_candidate_path(repo_context)
    rerun = _rerun_guidance(plan=plan, report=report, blob=blob)

    if _looks_like_name_mismatch(label=label, text=lowered, actual_expected=actual_expected):
        guidance.append(
            f"Check the failing assertion{_format_location(assertion_location)} and compare the expected symbol name with the implemented class or function name."
        )
        if actual_expected is not None:
            actual, expected = actual_expected
            guidance.append(
                f"Align the symbol casing or naming so the implementation resolves to `{expected}` instead of `{actual}`."
            )
        else:
            guidance.append(
                "Align the class or symbol naming convention with the expected casing and format used by the test."
            )
        guidance.append(_fixture_or_reference_guidance(repo_context, primary_path))
        if rerun:
            guidance.append(rerun)
        return _dedupe(guidance)

    if actual_expected is not None:
        actual, expected = actual_expected
        guidance.append(
            f"Inspect the failing assertion{_format_location(assertion_location)} and compare the actual value `{actual}` with the expected value `{expected}`."
        )
        guidance.append(
            "Update the producing implementation or the expected fixture only after confirming which side reflects the intended behavior."
        )
        if primary_path:
            guidance.append(f"Review related logic and fixtures referenced near `{primary_path}` before rerunning the test.")
        if rerun:
            guidance.append(rerun)
        return _dedupe(guidance)

    if _looks_like_typo_or_format_issue(label=label, text=lowered):
        guidance.append(
            f"Inspect the failing assertion{_format_location(assertion_location)} and identify the naming, spelling, or formatting mismatch."
        )
        if primary_path:
            guidance.append(f"Normalize the relevant symbol or output format in `{primary_path}` and any paired fixture or expectation file.")
        else:
            guidance.append("Normalize the relevant symbol or output format in the implementation and any paired fixture or expectation file.")
        if rerun:
            guidance.append(rerun)
        return _dedupe(guidance)

    if primary_path:
        guidance.append(f"Inspect `{primary_path}` and the related traceback or assertion site to confirm what value or behavior the test is checking.")
    else:
        guidance.append("Inspect the failing traceback or assertion site to confirm what value or behavior the test is checking.")
    guidance.append("Compare the current implementation output with the expected test fixture or assertion and adjust the code or expectation accordingly.")
    if rerun:
        guidance.append(rerun)
    return _dedupe(guidance)


def _extract_assertion_pair(text: str) -> Optional[tuple[str, str]]:
    match = re.search(r"AssertionError:\s+'([^']+)'\s*!=\s*'([^']+)'", text)
    if match:
        return match.group(1), match.group(2)
    return None


def _looks_like_name_mismatch(
    *,
    label: str,
    text: str,
    actual_expected: Optional[tuple[str, str]],
) -> bool:
    if any(token in label for token in ("class_name", "symbol_name", "name_mismatch", "casing", "naming")):
        return True
    if "are named" in text or "class name" in text or "incorrect class name casing" in text:
        return True
    if actual_expected is not None:
        actual, expected = actual_expected
        if actual.lower() == expected.lower() and actual != expected:
            return True
        if actual.endswith(("Extractor", "Error", "Exception")) and expected.endswith(("Extractor", "Error", "Exception")):
            return True
    return False


def _looks_like_typo_or_format_issue(*, label: str, text: str) -> bool:
    tokens = ("typo", "spelling", "format", "formatting", "naming", "casing")
    return any(token in label for token in tokens) or any(token in text for token in tokens)


def _fixture_or_reference_guidance(repo_context: Optional[RepoContext], primary_path: Optional[str]) -> str:
    candidates = [candidate.path for candidate in (repo_context.candidate_files if repo_context else [])]
    secondary = next((path for path in candidates if path != primary_path and ("test" in path or "result" in path)), None)
    if secondary:
        return f"Update any related expected-name references or fixtures in `{secondary}` if they still use the old symbol name."
    return "Check related fixtures, expectations, or test references that may still use the old symbol name."


def _rerun_guidance(plan: RemediationPlan, report: RCAReport, blob: str) -> str:
    if plan.commands:
        return f"Rerun `{plan.commands[0]}` after the change to confirm the failure is resolved."

    derived = _derive_rerun_command(blob)
    if derived:
        return f"Rerun `{derived}` after the change to confirm the failure is resolved."

    test_name = _extract_failing_test_name(report.key_lines)
    if test_name:
        return f"Rerun the failing test around `{test_name}` after the change to confirm the failure is resolved."

    return "Rerun the failing test target after the change to confirm the failure is resolved."


def _derive_rerun_command(blob: str) -> Optional[str]:
    if re.search(r"make:\s+\*\*\*\s+\[Makefile:[^\]]*: test\]", blob):
        return "make test"
    match = re.search(r"(^|\n)(pytest(?:\s+[^\n]+)?)", blob)
    if match:
        return match.group(2).strip()
    return None


def _extract_failing_test_name(lines: Sequence[LogLine]) -> Optional[str]:
    for line in lines:
        match = re.search(r"FAIL:\s+([^\s]+)", line.text)
        if match:
            return match.group(1)
        match = re.search(r"([A-Za-z0-9_./:-]+::[A-Za-z0-9_./:-]+)\s+FAILED", line.text)
        if match:
            return match.group(1)
    return None


def _assertion_location(repo_context: Optional[RepoContext]) -> Optional[str]:
    if repo_context is None:
        return None
    for candidate in repo_context.candidate_files:
        if candidate.line_hint:
            return f"`{candidate.path}:{candidate.line_hint}`"
    return _primary_candidate_path(repo_context)


def _primary_candidate_path(repo_context: Optional[RepoContext]) -> Optional[str]:
    if repo_context is None or not repo_context.candidate_files:
        return None
    for candidate in repo_context.candidate_files:
        if "/test" not in candidate.path and not candidate.path.startswith("test/"):
            return candidate.path
    return repo_context.candidate_files[0].path


def _format_location(location: Optional[str]) -> str:
    return f" in {location}" if location else ""


def _dedupe(items: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
