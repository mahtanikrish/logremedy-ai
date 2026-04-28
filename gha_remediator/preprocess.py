from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional, Tuple, Iterable

import tiktoken

from .types import LogLine, LogBlock
from .logs import line_matches_success_template

DEFAULT_KEYWORDS = [
    "fatal", "fail", "panic", "error", "exit", "kill", "no such file",
    "err:", "err!", "failures:", "missing", "exception", "cannot",
    "modulenotfounderror", "traceback", "assertionerror", "permission denied",
]
FALLBACK_TOKEN_ENCODINGS = ("o200k_base", "cl100k_base")

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

# This algorithm is derived from the research done in LogSage[17] 
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


def _approximate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def _encoding_model_candidates(model: Optional[str]) -> Iterable[str]:
    if not model:
        return ()
    candidates = [model]
    if "/" in model:
        suffix = model.rsplit("/", 1)[-1]
        if suffix not in candidates:
            candidates.append(suffix)
    return tuple(candidates)


@lru_cache(maxsize=16)
def _get_token_encoding(model: Optional[str]) -> Optional[tiktoken.Encoding]:
    for candidate in _encoding_model_candidates(model):
        try:
            return tiktoken.encoding_for_model(candidate)
        except KeyError:
            continue
        except Exception:
            break
    for encoding_name in FALLBACK_TOKEN_ENCODINGS:
        try:
            return tiktoken.get_encoding(encoding_name)
        except KeyError:
            continue
        except Exception:
            continue
    return None


def approx_tokens(text: str, model: Optional[str] = None) -> int:
    if not text:
        return 0
    encoding = _get_token_encoding(model)
    if encoding is None:
        return _approximate_tokens(text)
    return len(encoding.encode_ordinary(text))


def raw_tail_select(lines: List[LogLine], cfg: PreprocessConfig = PreprocessConfig(), model: Optional[str] = None) -> List[LogLine]:
    if not lines:
        return []

    selected: List[LogLine] = []
    used = 0
    for line in reversed(lines):
        line_tokens = approx_tokens(line.text, model=model)
        if selected and used + line_tokens > cfg.token_budget:
            break
        selected.append(line)
        used += line_tokens

    selected.reverse()
    return selected


def token_overflow_prune( blocks: List[LogBlock], key_lines: List[LogLine], cfg: PreprocessConfig = PreprocessConfig(), model: Optional[str] = None,) -> List[LogBlock]:
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
        t = approx_tokens(b.to_text(), model=model)
        if used + t <= cfg.token_budget:
            picked.append(b)
            used += t

    if not picked and ranked:
        trimmed = _trim_block_to_budget(ranked[0], cfg=cfg, model=model)
        if trimmed.lines:
            return [trimmed]

    picked.sort(key=lambda b: b.start)
    return picked


def _trim_block_to_budget(block: LogBlock, cfg: PreprocessConfig, model: Optional[str] = None) -> LogBlock:
    if approx_tokens(block.to_text(), model=model) <= cfg.token_budget:
        return block

    selected: List[LogLine] = []
    used = 0
    for line in reversed(block.lines):
        rendered = f"{line.lineno}: {line.text}"
        line_tokens = approx_tokens(rendered, model=model)
        if selected and used + line_tokens > cfg.token_budget:
            break
        selected.append(line)
        used += line_tokens

    if not selected and block.lines:
        selected = [block.lines[-1]]

    selected.reverse()
    if not selected:
        return LogBlock(start=block.start, end=block.end, lines=[], weight_density=block.weight_density)

    return LogBlock(
        start=selected[0].lineno,
        end=selected[-1].lineno,
        lines=selected,
        weight_density=block.weight_density,
    )
