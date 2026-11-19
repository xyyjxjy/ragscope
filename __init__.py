"""ragscope — 用 DSPy 做 RAG 检索质量诊断。

和普通 RAG 项目的区别：
    普通：文档 → 切分 → 向量 → 问答（教程能抄）
    这里：同样的链路，但多了「诊断 + 程序化优化」

DSPy 在这里的价值：
    不是手调 prompt，而是定义 metric 让优化器自动搜出更好的
    检索策略 + 提示组合。这才是 2026 年做 RAG 的正确姿势。

模块：
    loader     解析 pdf/docx/md → Document
    splitter   结构感知切分（保留标题层级）
    embedder   nomic-embed-text 向量化 + 磁盘缓存
    retriever  混合检索（向量 + 字面）+ rerank
    dspy_rag   DSPy Signature / Module / 优化器
    diagnose   召回率@k / MRR / 失败归因
    cli        命令行入口
"""
