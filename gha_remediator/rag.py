from __future__ import annotations

from dataclasses import dataclass
from typing import List
import re

from rank_bm25 import BM25Okapi

@dataclass(frozen=True)
class Doc:
    doc_id: str
    title: str
    text: str
    source: str = "local"

def _tokenize(s: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_\-\.]+", s.lower())

class KnowledgeBase:
    def __init__(self, docs: List[Doc]):
        self.docs = docs
        self._corpus_tokens = [_tokenize(d.title + " " + d.text) for d in docs]
        self.bm25 = BM25Okapi(self._corpus_tokens) if self._corpus_tokens else None

    def retrieve(self, query: str, top_k: int = 5) -> List[Doc]:
        if self.bm25 is None:
            return []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        scores = self.bm25.get_scores(query_tokens)
        scored = sorted(zip(scores, self.docs), key=lambda item: item[0], reverse=True)
        return [doc for score, doc in scored[:top_k] if score > 0]
