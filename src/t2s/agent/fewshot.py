"""Few-shot selection: static (first k hand-picked) or retrieved (top-k most similar)."""
from __future__ import annotations
import json
import numpy as np
from ..utils.config import FEWSHOT_POOL
from .embed import get_embedder


class FewShot:
    def __init__(self, path=FEWSHOT_POOL, embedder=None, n_static: int = 8):
        self.pool = [json.loads(l) for l in open(path) if l.strip()]
        self.emb = embedder or get_embedder()
        self.vecs = self.emb.encode([p["question"] for p in self.pool])
        self.n_static = n_static

    def select(self, question: str, k: int, mode: str = "retrieved") -> list[dict]:
        if k <= 0:
            return []
        if mode == "static":
            statics = [p for p in self.pool if p.get("static")] or self.pool
            return statics[:k]
        sims = self.vecs @ self.emb.encode([question])[0]
        return [self.pool[i] for i in np.argsort(-sims)[:k]]
