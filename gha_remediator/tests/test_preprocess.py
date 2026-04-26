from gha_remediator.types import LogLine
from gha_remediator.preprocess import (
    _get_token_encoding,
    approx_tokens,
    key_log_filter,
    key_log_expand,
    raw_tail_select,
    token_overflow_prune,
    PreprocessConfig,
)


def _make_lines(texts):
    """Turn a list of strings into 1-indexed LogLine objects."""
    return [LogLine(i + 1, t) for i, t in enumerate(texts)]


def test_filter_keeps_keyword_lines():
    lines = _make_lines([
        "Setting up environment",
        "ModuleNotFoundError: No module named 'boto3'",
        "Installing dependencies",
        "error: build step failed",
        "Uploading artifacts",
    ])
    result = key_log_filter(lines)
    texts = [l.text for l in result]
    assert any("ModuleNotFoundError" in t for t in texts)
    assert any("error: build step failed" in t for t in texts)

def test_filter_excludes_background_only_lines():
    lines = _make_lines([
        "Setting up environment",
        "Installing dependencies",
        "Uploading artifacts",
    ])
    result = key_log_filter(lines)
    assert isinstance(result, list)

def test_filter_deduplicates():
    lines = _make_lines(["error: something failed"] * 3)
    result = key_log_filter(lines)
    line_nos = [l.lineno for l in result]
    assert len(line_nos) == len(set(line_nos))

def test_filter_excludes_success_template_lines():
    lines = _make_lines([
        "error: build failed",
        "Run actions/checkout@v3",
    ])
    from gha_remediator.logs import build_success_templates
    success_templates = build_success_templates(["Run actions/checkout@v3\n"])
    result = key_log_filter(lines, success_templates=success_templates)
    texts = [l.text for l in result]
    assert not any("Run actions/checkout" in t for t in texts)
    assert any("error: build failed" in t for t in texts)


def test_expand_produces_block_around_key_line():
    lines = _make_lines(["line"] * 100)
    key = [LogLine(50, "error: something failed")]
    cfg = PreprocessConfig(before=5, after=10)
    blocks = key_log_expand(lines, key, cfg=cfg)
    assert len(blocks) == 1
    assert blocks[0].start == 45
    assert blocks[0].end == 60

def test_expand_clamps_at_boundaries():
    lines = _make_lines(["line"] * 10)
    key = [LogLine(2, "error")]
    cfg = PreprocessConfig(before=10, after=10)
    blocks = key_log_expand(lines, key, cfg=cfg)
    assert blocks[0].start >= 1
    assert blocks[0].end <= 10

def test_expand_merges_overlapping_blocks():
    lines = _make_lines(["line"] * 100)
    keys = [LogLine(20, "error A"), LogLine(25, "error B")]
    cfg = PreprocessConfig(before=5, after=5)
    blocks = key_log_expand(lines, keys, cfg=cfg)
    assert len(blocks) == 1

def test_expand_empty_key_lines():
    lines = _make_lines(["line"] * 10)
    blocks = key_log_expand(lines, [])
    assert blocks == []


def test_prune_keeps_blocks_within_budget():
    lines = _make_lines(["x"] * 200)
    from gha_remediator.preprocess import key_log_expand
    key = [LogLine(100, "error: fatal failure")]
    blocks = key_log_expand(lines, key)
    cfg = PreprocessConfig(token_budget=100)
    pruned = token_overflow_prune(blocks, key, cfg=cfg)
    total_chars = sum(len(b.to_text()) for b in pruned)
    assert total_chars <= 400 + 50  # small tolerance for block header text

def test_prune_empty_blocks():
    result = token_overflow_prune([], [])
    assert result == []

def test_prune_preserves_chronological_order():
    lines = _make_lines(["x"] * 200)
    keys = [LogLine(50, "error A"), LogLine(150, "error B")]
    blocks = key_log_expand(lines, keys, cfg=PreprocessConfig(before=5, after=5))
    pruned = token_overflow_prune(blocks, keys)
    starts = [b.start for b in pruned]
    assert starts == sorted(starts)


def test_prune_trims_oversized_single_block_instead_of_dropping_it():
    lines = _make_lines([f"line {i} " + ("x" * 80) for i in range(1, 31)])
    key = [LogLine(30, "error: transitive_update_not_possible " + ("y" * 80))]
    blocks = key_log_expand(lines, key, cfg=PreprocessConfig(before=29, after=0))

    pruned = token_overflow_prune(blocks, key, cfg=PreprocessConfig(token_budget=60))

    assert len(pruned) == 1
    assert pruned[0].lines
    assert pruned[0].end == 30
    total = approx_tokens(pruned[0].to_text())
    assert total <= 60


def test_raw_tail_select_keeps_tail_within_budget():
    lines = _make_lines([f"line {i}" for i in range(1, 101)])
    cfg = PreprocessConfig(token_budget=25)
    selected = raw_tail_select(lines, cfg=cfg)
    assert selected
    assert selected[-1].lineno == 100
    total = sum(approx_tokens(line.text) for line in selected)
    assert total <= cfg.token_budget


def test_approx_tokens_unknown_model_uses_fallback(monkeypatch):
    _get_token_encoding.cache_clear()
    calls = []

    class _Encoding:
        def encode_ordinary(self, text):
            return list(range(len(text.split())))

    def fake_encoding_for_model(model):
        raise KeyError(model)

    def fake_get_encoding(name):
        calls.append(name)
        if name == "o200k_base":
            return _Encoding()
        raise KeyError(name)

    monkeypatch.setattr("gha_remediator.preprocess.tiktoken.encoding_for_model", fake_encoding_for_model)
    monkeypatch.setattr("gha_remediator.preprocess.tiktoken.get_encoding", fake_get_encoding)

    assert approx_tokens("alpha beta gamma", model="unknown/model") == 3
    assert calls == ["o200k_base"]
    _get_token_encoding.cache_clear()


def test_approx_tokens_prefers_model_suffix(monkeypatch):
    _get_token_encoding.cache_clear()
    seen = []

    class _Encoding:
        def encode_ordinary(self, text):
            return [text]

    def fake_encoding_for_model(model):
        seen.append(model)
        if model == "gpt-5-mini":
            return _Encoding()
        raise KeyError(model)

    monkeypatch.setattr("gha_remediator.preprocess.tiktoken.encoding_for_model", fake_encoding_for_model)

    assert approx_tokens("content", model="openai/gpt-5-mini") == 1
    assert seen == ["openai/gpt-5-mini", "gpt-5-mini"]
    _get_token_encoding.cache_clear()


def test_approx_tokens_falls_back_to_heuristic_when_encoding_unavailable(monkeypatch):
    _get_token_encoding.cache_clear()

    def fake_encoding_for_model(model):
        raise RuntimeError(f"cannot load {model}")

    def fake_get_encoding(name):
        raise RuntimeError(f"cannot load {name}")

    monkeypatch.setattr("gha_remediator.preprocess.tiktoken.encoding_for_model", fake_encoding_for_model)
    monkeypatch.setattr("gha_remediator.preprocess.tiktoken.get_encoding", fake_get_encoding)

    assert approx_tokens("abcdefghij", model="gpt-4o-mini") == 3
    _get_token_encoding.cache_clear()
