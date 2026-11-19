"""混合检索：向量语义 + 字面关键词，融合后 rerank。

为什么必须混合：
    纯向量召不回「HT-2026-0417」这种编号、专有名词，也召不回
    生僻技术术语（embedding 没见过）。
    纯字面召不回「例会」↔「会议」这种同义改写。

融合策略：RRF（Reciprocal Rank Fusion）——不看分数只看排名，
避免两路分数尺度不同（余弦 0-1 vs bigram 计数）直接相加的问题。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from ragscope.embedder import Embedder, cosine_scores
from ragscope.splitter import Chunk


@dataclass
class Hit:
    chunk: Chunk
    score: float
    source: str = ""      # vector / keyword / both

    @property
    def citation(self) -> str:
        return self.chunk.citation


def _bigrams(text: str) -> set[str]:
    grams = set()
    for tok in re.findall(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z0-9]{2,}", text or ""):
        if len(tok) <= 2:
            grams.add(tok.lower())
        else:
            for i in range(len(tok) - 1):
                grams.add(tok[i:i + 2].lower())
    return grams


class HybridRetriever:
    """建索引 + 检索。两路召回用 RRF 融合。"""

    def __init__(self, embedder: Embedder | None = None):
        self.embedder = embedder or Embedder()
        self.chunks: list[Chunk] = []
        self.matrix: np.ndarray | None = None

    def build(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        texts = [c.text for c in chunks]
        print(f"向量化 {len(texts)} 个 chunk（TF-IDF + SVD，本地）...")
        self.matrix = self.embedder.embed(texts)
        self.embedder.save()
        print(f"索引就绪：{len(self.chunks)} 个 chunk，维度 {self.matrix.shape[1]}")

    # ---------- 两路召回 ----------
    def _vector_hits(self, query: str, k: int) -> list[tuple[int, float]]:
        qv = np.array(self.embedder.embed_one(query), dtype=np.float32)
        scores = cosine_scores(self.matrix, qv)
        idx = np.argsort(-scores)[:k]
        return [(int(i), float(scores[i])) for i in idx]

    def _keyword_hits(self, query: str, k: int) -> list[tuple[int, float]]:
        qg = _bigrams(query)
        if not qg:
            return []
        scored = []
        for i, c in enumerate(self.chunks):
            cg = _bigrams(c.text + " " + c.heading)
            if not cg:
                continue
            overlap = len(qg & cg)
            if overlap:
                scored.append((i, overlap / (len(qg) ** 0.5)))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]

    # ---------- 融合 ----------
    @staticmethod
    def _rrf(rank_lists: list[list[tuple[int, float]]], k: int = 60) -> dict[int, float]:
        """Reciprocal Rank Fusion：只依赖排名，天然消除尺度差异。"""
        fused: dict[int, float] = {}
        for lst in rank_lists:
            for rank, (idx, _) in enumerate(lst):
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
        return fused

    def search(self, query: str, top_k: int = 3, pool: int = 10,
               rerank: bool = True) -> list[Hit]:
        vec = self._vector_hits(query, pool)
        kw = self._keyword_hits(query, pool)
        fused = self._rrf([vec, kw])
        ranked = sorted(fused.items(), key=lambda x: -x[1])[:pool]

        hits = []
        vec_set = {i for i, _ in vec}
        kw_set = {i for i, _ in kw}
        for idx, score in ranked:
            src = ("both" if idx in vec_set and idx in kw_set
                   else "vector" if idx in vec_set else "keyword")
            hits.append(Hit(chunk=self.chunks[idx], score=score, source=src))

        if rerank and len(hits) > top_k:
            hits = self._rerank(query, hits)
        return hits[:top_k]

    def _rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        """重排：用 embedding 相似度重新打分（比 RRF 排名更贴合语义）。

        真实项目里这里可以换成 cross-encoder 或 LLM 打分。
        选 embedding 重排是因为：本地、快、无需额外模型。
        """
        qv = np.array(self.embedder.embed_one(query), dtype=np.float32)
        for h in hits:
            hv = np.array(self.embedder.embed_one(h.chunk.text), dtype=np.float32)
            h.score = float(cosine_scores(hv.reshape(1, -1), qv)[0])
        hits.sort(key=lambda h: -h.score)
        return hits
