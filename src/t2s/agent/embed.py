"""Embedders. Default: dependency-free hashing bag-of-words (deterministic, CPU-only).
Optional: BAAI/bge-small-en-v1.5 via sentence-transformers (`pip install .[embed]`, T2S_EMBEDDER=bge)."""
from __future__ import annotations
import os, re, zlib
import numpy as np

_STOP = {"the", "a", "an", "of", "in", "on", "for", "to", "by", "and", "is", "are", "was", "were", "what", "how",
         "many", "much", "which", "who", "with", "per", "each", "all", "do", "does", "did", "our", "we", "me", "show"}


def _tokens(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower().replace("_", " "))
    out = []
    for t in toks:
        if t in _STOP:
            continue
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


class HashingEmbedder:
    def __init__(self, dim: int = 1024):
        self.dim = dim

    def encode(self, texts: list[str]) -> np.ndarray:
        M = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = _tokens(t)
            feats = toks + [a + "_" + b for a, b in zip(toks, toks[1:])]
            for f in feats:
                M[i, zlib.crc32(f.encode()) % self.dim] += 1.0
            n = np.linalg.norm(M[i])
            if n:
                M[i] /= n
        return M


class BGEEmbedder:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.m = SentenceTransformer("BAAI/bge-small-en-v1.5")

    def encode(self, texts):
        return np.asarray(self.m.encode(texts, normalize_embeddings=True), dtype=np.float32)


def get_embedder():
    if os.environ.get("T2S_EMBEDDER") == "bge":
        return BGEEmbedder()
    return HashingEmbedder()
