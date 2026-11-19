"""向量化：TF-IDF + SVD 本地实现（零依赖、零服务、完全离线）。

为什么不用 embedding API / 本地 embedding 模型：
    1. 商汤这个 key 没有 embedding 接口（实测 404，只有对话模型）
    2. 本地 Ollama 在受限环境里启动不了
    3. RAG 建索引要编码几百个 chunk，API 调用慢且费额度

TF-IDF + SVD 的优势（面试可讲）：
    - 完全离线，clone 下来就能跑，不依赖任何外部服务
    - 中文场景下字面匹配（字符 n-gram）往往比语义向量更准，
      因为专有名词、编号、术语的『形状』比『语义』更重要
    - 缺点：不理解同义改写（「例会」vs「会议」）——所以配了混合检索补字面

换真 embedding 时只改 Embedder.fit/transform 两个方法即可。
"""

from __future__ import annotations

import hashlib
import os
import pickle
import re

import numpy as np


def _norm(text: str) -> str:
    """归一化：去空格、统一小写，中文按字符保留。"""
    return re.sub(r"\s+", "", text or "").lower()


class Embedder:
    """TF-IDF + SVD 向量化器。

    用法：
        emb = Embedder()
        emb.fit(all_chunk_texts)          # 建词表
        vectors = emb.transform(texts)    # 编码（可以是新的 query）
    """

    def __init__(self, n_components: int = 128):
        self.n_components = n_components
        self.vec = None          # TfidfVectorizer
        self.svd = None          # TruncatedSVD
        self.fitted = False

    def health(self) -> tuple[bool, str]:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: F401
            return True, "sklearn 可用（TF-IDF + SVD 本地模式）"
        except ImportError as e:
            return False, f"需要 scikit-learn：{e}"

    def fit(self, texts: list[str]) -> "Embedder":
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        corpus = [_norm(t) for t in texts]
        # 字符 n-gram：中文不分词也能抓字面特征，且对专有名词友好
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4),
                                   max_features=20000, min_df=1)
        tfidf = self.vec.fit_transform(corpus)
        n_comp = min(self.n_components, max(2, tfidf.shape[1] - 1))
        self.svd = TruncatedSVD(n_components=n_comp, random_state=42)
        self.svd.fit(tfidf)
        self.fitted = True
        return self

    def transform(self, texts: list[str]) -> np.ndarray:
        if not self.fitted:
            raise RuntimeError("先调用 fit()")
        tfidf = self.vec.transform([_norm(t) for t in texts])
        return self.svd.transform(tfidf).astype(np.float32)

    # 兼容旧接口
    def embed(self, texts: list[str], batch_log: bool = True) -> np.ndarray:
        if not self.fitted:
            self.fit(texts)
        return self.transform(texts)

    def embed_one(self, text: str) -> list[float]:
        return self.transform([text])[0].tolist()

    def save(self, path: str | None = None) -> None:
        p = path or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 ".embedder.pkl")
        with open(p, "wb") as f:
            pickle.dump({"vec": self.vec, "svd": self.svd,
                         "n": self.n_components}, f)

    def load(self, path: str | None = None) -> bool:
        p = path or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 ".embedder.pkl")
        if not os.path.exists(p):
            return False
        with open(p, "rb") as f:
            d = pickle.load(f)
        self.vec, self.svd, self.n_components = d["vec"], d["svd"], d["n"]
        self.fitted = True
        return True

    def close(self) -> None:
        pass


def cosine_scores(matrix: np.ndarray, query_vec: np.ndarray) -> np.ndarray:
    """批量余弦相似度。"""
    m = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
    q = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    return m @ q
