from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Optional
import math
import re
from collections import Counter, defaultdict

@dataclass(frozen=True)
class Doc:
    doc_id: str
    title: str
    text: str
    source: str = "local"

def _tokenize(s: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_\-\.]+", s.lower())

class SimpleBM25:
    """Tiny BM25 implementation for prototyping lexical retrieval."""
    def __init__(self, docs: List[Doc]):
        self.docs = docs
        self.N = len(docs)
        self.avgdl = 0.0
        self.tf = []
        self.df = Counter()
        self.doc_len = []
        for d in docs:
            toks = _tokenize(d.title + " " + d.text)
            c = Counter(toks)
            self.tf.append(c)
            self.doc_len.append(len(toks))
            for t in c:
                self.df[t] += 1
        self.avgdl = sum(self.doc_len) / max(1, self.N)

    def score(self, query: str, k1: float = 1.2, b: float = 0.75) -> List[Tuple[float, Doc]]:
        q = _tokenize(query)
        scores: List[Tuple[float, Doc]] = []
        for i, d in enumerate(self.docs):
            s = 0.0
            dl = self.doc_len[i]
            for term in q:
                df = self.df.get(term, 0)
                if df == 0:
                    continue
                idf = math.log(1 + (self.N - df + 0.5) / (df + 0.5))
                tf = self.tf[i].get(term, 0)
                denom = tf + k1 * (1 - b + b * dl / self.avgdl)
                s += idf * (tf * (k1 + 1) / (denom + 1e-9))
            scores.append((s, d))
        scores.sort(key=lambda x: x[0], reverse=True)
        return scores

class KnowledgeBase:
    def __init__(self, docs: List[Doc]):
        self.docs = docs
        self.bm25 = SimpleBM25(docs)

    def retrieve(self, query: str, top_k: int = 5) -> List[Doc]:
        scored = self.bm25.score(query)
        return [d for s, d in scored[:top_k] if s > 0]
