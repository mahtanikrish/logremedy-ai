from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple, Iterable

from .types import LogLine, LogBlock
from .logs import line_matches_success_template

DEFAULT_KEYWORDS = [
    "fatal", "fail", "panic", "error", "exit", "kill", "no such file",
    "err:", "err!", "failures:", "missing", "exception", "cannot",
    "modulenotfounderror", "traceback", "assertionerror", "permission denied",
]

@dataclass(frozen=True)
class PreprocessConfig:
    before: int = 10
    after: int = 40
    tail_lines: int = 200
    token_budget: int = 22000
    sparse_gap: int = 50
    high_weight: int = 10
    max_weight: int = 100

def _keyword_hit(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)

def key_log_filter(lines: List[LogLine], keywords: List[str] = DEFAULT_KEYWORDS, success_templates: Optional[set[str]] = None, cfg: PreprocessConfig = PreprocessConfig(),) -> List[LogLine]:

    # Select candidate lines using success-template filtering, keywords, and tail bias
    n = len(lines)
    tail_start = max(1, n - cfg.tail_lines + 1)

    candidates: List[LogLine] = []
    for ll in lines:
        if success_templates is not None and line_matches_success_template(ll.text, success_templates):
            continue

        if _keyword_hit(ll.text, keywords) or ll.lineno >= tail_start:
            candidates.append(ll)

    seen = set()
    out: List[LogLine] = []
    for c in candidates:
        if c.lineno in seen:
            continue
        seen.add(c.lineno)
        out.append(c)
    return out

def key_log_expand(lines: List[LogLine], key_lines: List[LogLine], cfg: PreprocessConfig = PreprocessConfig(),) -> List[LogBlock]:
    # Asymmetric context expansion around key lines and merge overlaps
    if not key_lines:
        return []

    n = len(lines)
    ranges: List[Tuple[int,int]] = []
    for k in key_lines:
        start = max(1, k.lineno - cfg.before)
        end = min(n, k.lineno + cfg.after)
        ranges.append((start, end))

    ranges.sort()
    merged: List[Tuple[int,int]] = []
    cur_s, cur_e = ranges[0]
    for s,e in ranges[1:]:
        if s <= cur_e + 1:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s,e
    merged.append((cur_s, cur_e))

    blocks: List[LogBlock] = []
    for s,e in merged:
        blk_lines = [lines[i-1] for i in range(s, e+1)]
        blocks.append(LogBlock(start=s, end=e, lines=blk_lines))
    return blocks

def _approx_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))

def token_overflow_prune(blocks: List[LogBlock], key_lines: List[LogLine], cfg: PreprocessConfig = PreprocessConfig(),) -> List[LogBlock]:
    
    # Rank blocks by weighted signal density and prune to token budget
    if not blocks:
        return []

    key_set = {k.lineno for k in key_lines}

    def line_weight(ll: LogLine) -> int:
        t = ll.text.lower()
        w = 0
        if ll.lineno in key_set:
            w += cfg.high_weight
        if "--- fail" in t or "failures:" in t or "traceback" in t:
            w = max(w, cfg.max_weight)
        if any(k in t for k in DEFAULT_KEYWORDS):
            w += 5
        if ll.text.strip().startswith("#"):
            w += 3
        return w

    ranked: List[LogBlock] = []
    for b in blocks:
        total_w = sum(line_weight(ll) for ll in b.lines)
        length = max(1, (b.end - b.start + 1))
        density = total_w / length
        ranked.append(LogBlock(b.start, b.end, b.lines, weight_density=density))

    ranked.sort(key=lambda b: b.weight_density, reverse=True)

    picked: List[LogBlock] = []
    used = 0
    for b in ranked:
        t = _approx_tokens(b.to_text())
        if used + t <= cfg.token_budget:
            picked.append(b)
            used += t

    picked.sort(key=lambda b: b.start)
    return picked
