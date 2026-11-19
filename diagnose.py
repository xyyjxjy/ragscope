"""诊断：RAG 答不好时，到底是哪一步坏了？

这是本项目相对「普通 RAG demo」的核心差异。
普通 demo 只告诉你答案，这里告诉你**失败归因**：

    检索失败（Recall@k 就错了）→ 改切分策略 / 换 embedding / 加混合检索
    检索对但生成错          → 改 prompt / 换模型 / 上下文太长被截断
    引用错但答案对          → citation 提取有问题

配合 DSPy 优化，可以量化「改了之后好了多少」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ragscope.retriever import HybridRetriever


@dataclass
class QueryResult:
    question: str
    expect_citation: str
    retrieved: list[str]             # 召回的 citation 列表（按排名）
    recall_at_k: dict[int, float]    # {1: 0/1, 3: 0/1, 5: 0/1}
    mrr: float
    answer: str = ""
    failure: str = ""                # 归因

    @property
    def hit(self) -> bool:
        return self.recall_at_k.get(3, 0.0) > 0


def _match(expect: str, citations: list[str]) -> int:
    """期望出处出现在第几位（1-based），0 = 没出现。

    expect 支持用 | 分隔多个可接受答案。
    """
    if not expect:
        return 0
    wants = [w.strip() for w in expect.split("|") if w.strip()]
    for rank, c in enumerate(citations, 1):
        if any(w in c for w in wants):
            return rank
    return 0


def diagnose_retrieval(retriever: HybridRetriever,
                       cases: list[dict], k_max: int = 5,
                       rerank: bool = True) -> list[QueryResult]:
    """只测检索层：召回率@k + MRR。不调 LLM，所以快且免费。"""
    results = []
    for case in cases:
        q = case["question"]
        expect = case.get("expect_citation", "")
        hits = retriever.search(q, top_k=k_max, rerank=rerank)
        cits = [h.citation for h in hits]
        rank = _match(expect, cits)

        recall = {k: (1.0 if rank and rank <= k else 0.0)
                  for k in (1, 3, 5) if k <= k_max}
        mrr = 1.0 / rank if rank else 0.0

        failure = ""
        if not expect:
            failure = "未标注期望出处，跳过诊断"
        elif rank == 0:
            failure = "检索完全没命中 → 切分粒度或 embedding 不适配"
        elif rank > 3:
            failure = f"命中但排在第 {rank} 位 → 需要 rerank 或调整融合权重"

        results.append(QueryResult(
            question=q, expect_citation=expect, retrieved=cits,
            recall_at_k=recall, mrr=mrr, failure=failure))
    return results


def aggregate(results: list[QueryResult]) -> dict:
    """汇总指标。"""
    n = len(results) or 1
    agg = {"n": len(results)}
    for k in (1, 3, 5):
        vals = [r.recall_at_k.get(k, 0.0) for r in results if k in r.recall_at_k]
        if vals:
            agg[f"recall@{k}"] = round(sum(vals) / len(vals) * 100, 1)
    agg["mrr"] = round(sum(r.mrr for r in results) / n, 3)
    agg["miss"] = sum(1 for r in results if not r.hit)
    return agg


def render_report(results: list[QueryResult], agg: dict,
                  title: str = "RAG 检索诊断报告") -> str:
    lines = [f"# {title}", "",
             f"- 用例：{agg['n']} 条",
             f"- Recall@1：{agg.get('recall@1', 0)}%",
             f"- Recall@3：{agg.get('recall@3', 0)}%",
             f"- Recall@5：{agg.get('recall@5', 0)}%",
             f"- MRR：{agg['mrr']}",
             f"- 未命中：{agg['miss']} 条",
             ""]
    bad = [r for r in results if not r.hit]
    if bad:
        lines += ["## 失败归因", "",
                  "| 问题 | 期望出处 | 实际召回 (前3) | 归因 |",
                  "|---|---|---|---|"]
        for r in bad[:15]:
            lines.append(
                f"| {r.question[:30]} | {r.expect_citation[:24]} | "
                f"{', '.join(c[:24] for c in r.retrieved[:3])} | {r.failure} |")
    else:
        lines += ["全部命中 ✓"]
    return "\n".join(lines)
