from __future__ import annotations

import re
from typing import List, Iterable, Optional
from .types import LogLine

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)

def read_log_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

def to_lines(text: str) -> List[LogLine]:
    lines: List[LogLine] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        lines.append(LogLine(i, strip_ansi(raw.rstrip("\n"))))
    return lines

def normalize_for_template(line: str) -> str:
    """Normalize a log line for rough template matching

    Replace common variable substrings (hashes, numbers, file paths) with placeholders.
    This is a lightweight stand-in for full Drain-style template mining.
    """
    s = line
    s = re.sub(r"0x[0-9a-fA-F]+", "<HEX>", s)
    s = re.sub(r"\b\d+\b", "<NUM>", s)
    s = re.sub(r"[A-Fa-f0-9]{7,}", "<HASH>", s)  # commit IDs, digests
    s = re.sub(r"(/[^\s]+)+", "<PATH>", s)
    s = re.sub(r"\bhttps?://\S+", "<URL>", s)
    return s

def build_success_templates(success_logs: Iterable[str]) -> set[str]:
    templates: set[str] = set()
    for txt in success_logs:
        for line in txt.splitlines():
            line = strip_ansi(line).strip()
            if not line:
                continue
            templates.add(normalize_for_template(line))
    return templates

def line_matches_success_template(line: str, templates: set[str]) -> bool:
    return normalize_for_template(line.strip()) in templates
