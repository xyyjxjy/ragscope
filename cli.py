"""命令行入口。

用法：
    python -m ragscope.cli index  --docs ./docs_dir            # 建索引
    python -m ragscope.cli query  --q "住宿标准是多少"          # 检索（不调 LLM）
    python -m ragscope.cli eval   --cases cases.yaml           # 检索诊断报告
    python -m ragscope.cli ask    --q "住宿标准是多少"          # DSPy 完整问答
    python -m ragscope.cli optimize --cases cases.yaml         # DSPy 自动优化
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from ragscope.diagnose import aggregate, diagnose_retrieval, render_report
from ragscope.embedder import Embedder
from ragscope.loader import load_dir
from ragscope.retriever import HybridRetriever
from ragscope.splitter import split_all

# key 放在 agentprobe/.env（那边是主项目），先读本地再读那边
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(os.path.dirname(_HERE), "agentprobe", ".env"),
           os.path.join(_HERE, ".env"),
           os.path.join(os.getcwd(), ".env")):
    if os.path.exists(_p):
        load_dotenv(_p)
        break

INDEX_DIR = os.path.join(_HERE, ".index")


def _save_index(retriever: HybridRetriever) -> None:
    os.makedirs(INDEX_DIR, exist_ok=True)
    with open(os.path.join(INDEX_DIR, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump([{"chunk_id": c.chunk_id, "text": c.text, "doc_id": c.doc_id,
                    "heading": c.heading, "level": c.level, "meta": c.meta}
                   for c in retriever.chunks], f, ensure_ascii=False)


def _load_index() -> HybridRetriever | None:
    p = os.path.join(INDEX_DIR, "chunks.json")
    if not os.path.exists(p):
        return None
    from ragscope.splitter import Chunk
    with open(p, encoding="utf-8") as f:
        raw = json.load(f)
    chunks = [Chunk(**r) for r in raw]
    r = HybridRetriever()
    print(f"从缓存加载索引：{len(chunks)} 个 chunk")
    r.build(chunks)
    return r


def cmd_index(args) -> None:
    ok, msg = Embedder().health()
    if not ok:
        print(f"❌ {msg}")
        sys.exit(1)
    print(f"加载 {args.docs} ...")
    docs = load_dir(args.docs)
    print(f"解析出 {len(docs)} 篇文档")
    chunks = split_all(docs)
    print(f"切分成 {len(chunks)} 个 chunk")
    r = HybridRetriever()
    r.build(chunks)
    _save_index(r)
    print("索引已保存")


def cmd_query(args) -> None:
    r = _load_index()
    if not r:
        print("没有索引，先跑 index")
        sys.exit(1)
    hits = r.search(args.q, top_k=args.top_k)
    print(f"\n问题：{args.q}\n")
    for i, h in enumerate(hits, 1):
        print(f"[{i}] score={h.score:.4f} source={h.source}")
        print(f"    出处：{h.citation}")
        print(f"    内容：{h.chunk.text[:160].replace(chr(10), ' ')}...\n")


def _load_cases(path: str) -> list[dict]:
    import yaml
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    return d["cases"] if isinstance(d, dict) else d


def cmd_eval(args) -> None:
    r = _load_index()
    if not r:
        print("没有索引，先跑 index")
        sys.exit(1)
    cases = _load_cases(args.cases)
    print(f"评估 {len(cases)} 条用例（只测检索，不调 LLM）...")
    results = diagnose_retrieval(r, cases, rerank=not args.no_rerank)
    agg = aggregate(results)
    report = render_report(results, agg, title=f"检索诊断 · {args.cases}")
    print("\n" + report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n报告已写入 {args.out}")


def cmd_ask(args) -> None:
    from ragscope.dspy_rag import RAGModule, configure_lm
    r = _load_index()
    if not r:
        print("没有索引，先跑 index")
        sys.exit(1)
    print("配置 LLM：", configure_lm())
    mod = RAGModule(r, top_k=args.top_k)
    pred = mod(question=args.q)
    print(f"\n问题：{args.q}")
    print(f"检索查询：{pred.query_used}")
    print(f"\n回答：{pred.answer}")
    print(f"\n引用：{pred.citations}")
    print("\n召回：")
    for i, h in enumerate(pred.hits, 1):
        print(f"  [{i}] {h.citation}  (score={h.score:.4f})")


def cmd_optimize(args) -> None:
    from ragscope.dspy_rag import (RAGModule, build_trainset, configure_lm,
                                    citation_metric, optimize, OptimizeResult)
    r = _load_index()
    if not r:
        print("没有索引，先跑 index")
        sys.exit(1)
    print("配置 LLM：", configure_lm())
    cases = _load_cases(args.cases)
    trainset = build_trainset(cases)
    print(f"训练样本 {len(trainset)} 条")

    mod = RAGModule(r, top_k=3)
    before = sum(citation_metric(ex, mod(question=ex.question))
                 for ex in trainset) / len(trainset)
    print(f"优化前 metric：{before:.3f}")

    print(f"开始 DSPy 优化（{args.auto}）...")
    compiled = optimize(mod, trainset, metric=citation_metric, auto=args.auto)

    after = sum(citation_metric(ex, compiled(question=ex.question))
                for ex in trainset) / len(trainset)
    res = OptimizeResult(before=before, after=after, n_train=len(trainset))
    print("\n" + res.summary())
    if args.save:
        compiled.save(args.save)
        print(f"优化后的 module 已保存到 {args.save}")


def main() -> None:
    ap = argparse.ArgumentParser(description="ragscope — DSPy RAG 诊断")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index", help="建索引")
    p.add_argument("--docs", required=True)
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("query", help="检索（不调 LLM）")
    p.add_argument("--q", required=True)
    p.add_argument("--top-k", type=int, default=3)
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("eval", help="检索诊断报告")
    p.add_argument("--cases", required=True)
    p.add_argument("--out", default="")
    p.add_argument("--no-rerank", action="store_true")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("ask", help="DSPy 完整问答")
    p.add_argument("--q", required=True)
    p.add_argument("--top-k", type=int, default=3)
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("optimize", help="DSPy 自动优化")
    p.add_argument("--cases", required=True)
    p.add_argument("--auto", default="light", choices=["light", "medium"])
    p.add_argument("--save", default="")
    p.set_defaults(func=cmd_optimize)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
