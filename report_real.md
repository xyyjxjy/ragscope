# 检索诊断 · ragscope\cases.yaml

- 用例：18 条
- Recall@1：61.1%
- Recall@3：88.9%
- Recall@5：100.0%
- MRR：0.747
- 未命中：2 条

## 失败归因

| 问题 | 期望出处 | 实际召回 (前3) | 归因 |
|---|---|---|---|
| 加固之后效果提升了多少 | results.md | pitfalls.md · 被打断了（Ctrl-, design.md · 核心设计 > 4. 为什, autoscan.md · AgentProbe | 命中但排在第 4 位 → 需要 rerank 或调整融合权重 |
| 密钥泄露是怎么处理的 | README|pitfalls.md | design.md · 核心设计 > 1. ca, design.md · 核心设计, autoscan.md · AgentProbe | 命中但排在第 5 位 → 需要 rerank 或调整融合权重 |