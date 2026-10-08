"""Schema linking / pruning: embedding retrieval + glossary keyword boost + join-path connectors."""
from __future__ import annotations
import re
from collections import deque
import numpy as np
import yaml
from ..utils.config import KEYWORDS_YAML
from .embed import get_embedder, _tokens


class SchemaLinker:
    def __init__(self, meta: dict, embedder=None, keywords_path=KEYWORDS_YAML):
        self.meta = meta
        self.emb = embedder or get_embedder()
        self.keywords = yaml.safe_load(open(keywords_path))
        self.names = list(meta)
        docs = [f"{t} {meta[t].get('_desc','')} " + " ".join(f"{c} {d}" for c, d in meta[t]["columns"].items())
                for t in self.names]
        self.doc_vecs = self.emb.encode(docs)
        self.graph = self._graph()

    def _graph(self):
        g = {t: set() for t in self.names}
        for t in self.names:
            for j in self.meta[t].get("_joins", []):
                found = re.findall(r"\b([a-z_]+)\.[a-z_]+", j.split("--")[0].split("(")[0])
                for a in found:
                    if a in g and a != t:
                        g[t].add(a); g[a].add(t)
        return g

    def _path(self, a, b):
        prev, q = {a: None}, deque([a])
        while q:
            x = q.popleft()
            if x == b:
                break
            for y in self.graph[x]:
                if y not in prev:
                    prev[y] = x; q.append(y)
        out, x = [], b
        while x is not None and x in prev:
            out.append(x); x = prev[x]
        return out

    def link(self, question: str, top_k: int = 3) -> list[str]:
        sims = self.doc_vecs @ self.emb.encode([question])[0]
        chosen = [self.names[i] for i in np.argsort(-sims)[:top_k]]
        for tok in _tokens(question) + question.lower().split():
            for t in self.keywords.get(tok.strip("?.,"), []):
                if t not in chosen:
                    chosen.append(t)
        base = list(chosen)
        for i, a in enumerate(base):                   # connector tables on join paths keep joins possible
            for b in base[i + 1:]:
                for t in self._path(a, b):
                    if t not in chosen:
                        chosen.append(t)
        if len(chosen) == 1:
            chosen += sorted(self.graph[chosen[0]])
        return [t for t in self.names if t in chosen]
