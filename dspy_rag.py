"""DSPy 层：把 RAG 的检索+生成定义成可优化程序。

和「手调 prompt」的区别：
    手调：改提示词 → 跑一遍 → 感觉好点 → 再改（不可复现，靠直觉）
    DSPy：定义 Signature + metric → 优化器自动搜最优 prompt/策略组合 → 有指标对比

DSPy 的三个核心概念在本文件里的体现：
    Signature  声明「输入什么、输出什么」（不写 prompt）
    Module     声明「怎么组装」（Retrieve → Generate）
    Optimizer  用训练集自动调优（BootstrapFewShot / MIPRO）

优化能改什么：
    - 生成阶段的指令措辞
    - few-shot 示例选哪几条
    - 检索条数 top_k（枚举进优化空间）

注意：优化需要跑几十次 LLM 调用，所以样本要少（10-20 条），
      metric 要便宜（用关键词命中/引用命中，不调 LLM 判分）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import dspy

from ragscope.retriever import HybridRetriever


# ============================================================ 1. 配置 LLM


def configure_lm(model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None) -> str:
    """把 DSPy 接到 OpenAI 兼容端点（商汤 / DeepSeek / OpenAI 都行）。"""
    key = api_key or os.getenv("LLM_API_KEY", "")
    if not key:
        raise RuntimeError("需要 LLM_API_KEY（.env 里配置）")
    name = model or os.getenv("LLM_MODEL", "sensenova-6.8-flash-lite")
    url = base_url or os.getenv("LLM_BASE_URL", "https://token.sensenova.cn/v1")
    lm = dspy.LM(f"openai/{name}", api_key=key, api_base=url,
                 temperature=0, max_tokens=800)
    dspy.configure(lm=lm)
    return f"{name} @ {url}"


# ============================================================ 2. Signature


class RAGAnswer(dspy.Signature):
    """基于检索到的资料回答问题，必须引用出处。

    只声明字段，不写 prompt —— 具体措辞交给优化器去搜。
    """
    context: str = dspy.InputField(desc="检索到的资料片段，每条带出处编号")
    question: str = dspy.InputField(desc="用户问题")
    answer: str = dspy.OutputField(desc="基于资料的回答，句末附 [出处编号]")
    citations: str = dspy.OutputField(desc="引用的出处编号，逗号分隔，如 1,3")


class QueryRewrite(dspy.Signature):
    """把口语化问题改写成更适合检索的查询。

    这是 RAG 里最容易被忽略但影响最大的一步：
    「住宿费能报多少」直接去检索会命中率低，
    改写成「差旅 住宿标准 报销上限」命中率高得多。
    """
    question: str = dspy.InputField(desc="用户原始问法")
    keywords: str = dspy.OutputField(desc="检索用关键词，空格分隔，5-12 个词")


# ============================================================ 3. Module


class RAGModule(dspy.Module):
    """RAG 流水线：改写查询 → 混合检索 → 生成带出处的回答。

    DSPy 的价值在这里：rewrite 和 answer 两个 Signature 的指令、
    few-shot 示例都能被优化器自动调，不是我手写死的。
    """

    def __init__(self, retriever: HybridRetriever, top_k: int = 3,
                 use_rewrite: bool = True):
        super().__init__()
        self.retriever = retriever
        self.top_k = top_k
        self.use_rewrite = use_rewrite
        self.rewrite = dspy.Predict(QueryRewrite)
        self.answer = dspy.ChainOfThought(RAGAnswer)

    def forward(self, question: str):
        query = question
        if self.use_rewrite:
            try:
                rw = self.rewrite(question=question)
                if (rw.keywords or "").strip():
                    query = f"{question} {(rw.keywords or '').strip()}"
            except Exception:  # noqa: BLE001
                pass  # 改写失败就用原问题，不阻塞

        hits = self.retriever.search(query, top_k=self.top_k)
        context = "\n".join(
            f"[{i+1}] ({h.citation})\n{h.chunk.text[:600]}"
            for i, h in enumerate(hits))

        pred = self.answer(context=context, question=question)
        return dspy.Prediction(
            answer=pred.answer,
            citations=pred.citations,
            context=context,
            hits=hits,
            query_used=query,
        )


# ============================================================ 4. Metric


def citation_metric(example, pred, trace=None) -> float:
    """评估指标：答案是否引用了正确出处 + 是否答对关键词。

    刻意不调 LLM 判分（太慢太贵），用两个便宜但有效的信号：
        1. 引用命中：预测的 citation 里有没有 ground truth 的文档/标题
        2. 内容命中：答案里有没有期望的关键词
    这是「用便宜指标跑优化」的工程取舍。
    """
    score = 0.0
    expect_cit = (getattr(example, "expect_citation", "") or "").strip()
    if expect_cit:
        got = (getattr(pred, "citations", "") or "") + \
              " ".join(h.citation for h in getattr(pred, "hits", []))
        if any(part.strip() and part.strip() in got
               for part in expect_cit.split("|")):
            score += 0.6

    expect_kw = (getattr(example, "expect_keywords", "") or "").strip()
    if expect_kw:
        ans = (getattr(pred, "answer", "") or "")
        hits = sum(1 for kw in expect_kw.split("|") if kw.strip() and kw in ans)
        total = max(1, len([k for k in expect_kw.split("|") if k.strip()]))
        score += 0.4 * (hits / total)
    return score


# ============================================================ 5. 优化器


def build_trainset(pairs: list[dict]) -> list:
    """把 [{question, expect_citation, expect_keywords}] 转成 DSPy Example。"""
    return [
        dspy.Example(
            question=p["question"],
            expect_citation=p.get("expect_citation", ""),
            expect_keywords=p.get("expect_keywords", ""),
        ).with_inputs("question")
        for p in pairs
    ]


def optimize(module: RAGModule, trainset: list, metric=citation_metric,
             auto: str = "light") -> RAGModule:
    """用 DSPy 优化器自动调 prompt / few-shot。

    auto:
        light  BootstrapFewShot（快，几十次调用）
        medium MIPROv2（更强，上百次调用，费额度）
    """
    if auto == "light":
        opt = dspy.BootstrapFewShot(metric=metric, max_bootstrapped_demos=3,
                                    max_labeled_demos=3)
    else:
        opt = dspy.MIPROv2(metric=metric, auto="light")
    return opt.compile(module, trainset=trainset)


@dataclass
class OptimizeResult:
    before: float
    after: float
    n_train: int

    def summary(self) -> str:
        delta = self.after - self.before
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        return (f"优化前 {self.before:.3f} → 优化后 {self.after:.3f} "
                f"{arrow}{abs(delta):.3f}（{self.n_train} 条训练样本）")
