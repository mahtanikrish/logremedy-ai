from __future__ import annotations

import json
from typing import Any, Dict, List


def sentence_case(value: str) -> str:
    return value.replace("_", " ").strip().title()


def short_key_line(item: Dict[str, Any]) -> str:
    line_text = " ".join(str(item.get("text", "")).split())
    return f"Line {item.get('lineno', '?')}: {line_text or 'No text captured.'}"


def render_result_sections(result: Dict[str, Any], raw_log_text: str = "") -> Dict[str, Any]:
    rca = result["rca"]
    remediation = result["remediation"]
    verification = result["verification"]

    evidence = verification.get("evidence", {})
    evidence_lines: List[str] = []
    for key, value in evidence.items():
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value) if value else "None"
        elif isinstance(value, dict):
            rendered = ", ".join(f"{k}: {v}" for k, v in value.items()) if value else "None"
        else:
            rendered = str(value)
        evidence_lines.append(f"{sentence_case(str(key))}: {rendered}")

    return {
        "summary": {
            "failure_class": sentence_case(str(rca.get("failure_class", "unknown"))),
            "fix_type": sentence_case(str(remediation.get("fix_type", "unknown"))),
            "verification": sentence_case(str(verification.get("status", "unknown"))),
        },
        "rca": {
            "headline": sentence_case(str(rca.get("failure_class", "unknown"))),
            "sections": [
                {
                    "title": "Root Cause Summary",
                    "body": "Likely causes identified from the failed run.",
                    "bullets": rca.get("root_causes", []) or ["No root cause explanation returned."],
                },
                {
                    "title": "Supporting Log Lines",
                    "body": "Most relevant lines pulled from the failing log.",
                    "bullets": [short_key_line(item) for item in rca.get("key_lines", [])]
                    or ["No supporting lines were extracted."],
                },
            ],
        },
        "remediation": {
            "headline": f"{sentence_case(str(remediation.get('fix_type', 'unknown')))} fix",
            "sections": [
                {
                    "title": "Proposed Change",
                    "body": f"Risk level: {sentence_case(str(remediation.get('risk_level', 'unknown')))}",
                    "bullets": remediation.get("commands", []) or ["No concrete remediation commands were returned."],
                },
                {
                    "title": "Assumptions",
                    "body": "Conditions that need to hold for the proposed fix to be valid.",
                    "bullets": remediation.get("assumptions", []) or ["No assumptions were listed."],
                },
                {
                    "title": "Rollback Plan",
                    "body": "How to safely reverse the suggested change.",
                    "bullets": remediation.get("rollback", []) or ["No rollback steps were provided."],
                },
            ],
        },
        "verification": {
            "headline": sentence_case(str(verification.get("status", "unknown"))),
            "sections": [
                {
                    "title": "Verification Outcome",
                    "body": str(verification.get("reason", "No verification explanation returned.")),
                    "bullets": [],
                },
                {
                    "title": "Evidence",
                    "body": "Signals collected from the current verification stage.",
                    "bullets": evidence_lines or ["No verification evidence was returned."],
                },
            ],
        },
        "raw_log": raw_log_text or "No raw log captured for this run.",
        "json": json.dumps(result, indent=2),
    }


def empty_result_view() -> Dict[str, Any]:
    return {
        "headline": "No analysis yet",
        "sections": [
            {
                "title": "Ready for a run",
                "body": "Use the controls on the left, then run a synthetic or GitHub case to populate this report view.",
                "bullets": [
                    "RCA will explain what likely failed and why.",
                    "Remediation will summarise the proposed fix and assumptions.",
                    "Verification will show the current gate result and supporting evidence.",
                ],
            }
        ],
    }


def flatten_sections(payload: Dict[str, Any]) -> str:
    lines = [str(payload.get("headline", "")).strip(), ""]
    for section in payload.get("sections", []):
        lines.append(str(section.get("title", "")).strip())
        body = str(section.get("body", "")).strip()
        if body:
            lines.append(body)
        for bullet in section.get("bullets", []):
            lines.append(f"- {bullet}")
        lines.append("")
    return "\n".join(line for line in lines if line is not None).strip()
