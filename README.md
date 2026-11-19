# ragscope — 用 DSPy 做 RAG 检索质量诊断

不是又一个文档问答 demo。这个项目的目标只有一个：**说清 RAG 到底哪一步坏了，以及改了什么会变好多少。**

```
普通 RAG 项目              ragscope
─────────────              ─────────
切分 → 向量 → 问答          同样的链路，但多了：
                           ① 结构感知切分（保留标题层级，回答能给出处）
                           ② 混合检索（向量 + 字面，RRF 融合）
                           ③ Rerank 重排（可量化提升）
                           ④ DSPy 程序化优化（不是手调 prompt）
                           ⑤ 失败归因（召回错？排太后？生成错？）
```

## 实测数据（10 篇真实技术文档 / 89 个 chunk / 18 条用例）

| 配置 | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---|---|---|---|
| 无 rerank | 44.4% | 83.3% | 94.4% | 0.645 |
| **有 rerank** | **61.1%** | **88.9%** | 100% | **0.747** |
| 提升 | **+16.7pt** | +5.6pt | +5.6pt | +0.102 |

**结论**：rerank 对首条命中率提升最明显（+16.7pt），说明「融合后排序不准」是主要瓶颈，而不是「召回不到」。

诊断还给出了 2 条未命中用例的归因：
> 「加固之后效果提升了多少」→ 命中但排第 4 位 → 需要调整融合权重

## 快速开始

```bash
# 1. 建索引（本地 TF-IDF + SVD，零依赖、不烧 API）
python -m ragscope.cli index --docs ./your_docs

# 2. 检索（不调 LLM，看命中了什么）
python -m ragscope.cli query --q "住宿标准是多少"

# 3. 检索诊断报告（Recall@k / MRR / 失败归因）
python -m ragscope.cli eval --cases ragscope/cases.yaml --out report.md

# 4. DSPy 完整问答（需要 LLM key）
python -m ragscope.cli ask --q "住宿标准是多少"

# 5. DSPy 自动优化
python -m ragscope.cli optimize --cases ragscope/cases.yaml --auto light
```

## 模块

| 文件 | 作用 | 关键设计 |
|---|---|---|
| `loader.py` | 解析 pdf/docx/md | 不依赖 langchain_community，手写解析保留 Word 标题层级 |
| `splitter.py` | 结构感知切分 | 按 markdown 标题切，chunk 带「标题链」，回答能给「出处：xxx.md · 一、差旅标准」 |
| `embedder.py` | TF-IDF + SVD 向量化 | 完全离线、零服务；中文场景字符 n-gram 对专有名词更友好 |
| `retriever.py` | 混合检索 + rerank | 向量 + 字面两路，**RRF 融合**（消除尺度差异），再 embedding 重排 |
| `dspy_rag.py` | DSPy 程序化优化 | Signature 声明输入输出 → Optimizer 自动搜 prompt/示例，不手调 |
| `diagnose.py` | 检索诊断 | Recall@k / MRR / 失败归因（没召回 vs 排太后 vs 生成错） |

## 为什么用 DSPy

手调 prompt 的问题：改一版跑一遍、凭感觉判断、不可复现。

DSPy 的做法：声明 `Signature`（输入什么输出什么）→ 定义 `metric` → 优化器自动搜最优的指令措辞和 few-shot 示例。

本项目的实测（诚实记录）：

```
优化前 metric：1.000 → 优化后 0.987（下降 0.013）
```

**这是个有价值的负结果**：说明在小语料（3 篇文档）上基线已饱和，few-shot 示例反而引入扰动。真实工程里也常遇到——**当基线足够好时，加优化是负收益**。这比硬凑一个「优化后提升」的数字诚实得多。

## 技术取舍（面试可讲）

**1. 为什么 embedding 用 TF-IDF + SVD 而不是真向量模型？**

商汤这个 key 没有 embedding 接口（实测 `/v1/embeddings` 返回 404，只有对话模型）；本地 Ollama 在受限环境起不来。TF-IDF 的优势是**完全离线、零依赖、可复现**，中文场景字符 n-gram 对编号/术语的匹配甚至更准。缺点是不理解同义改写——所以配了字面召回做互补。换真 embedding 只需改 `Embedder` 的 `fit`/`transform`。

**2. 为什么要混合检索？**

纯向量召不回 `HT-2026-0417` 这种编号（embedding 没见过）；纯字面召不回「例会」↔「会议」。两路融合用 RRF，只依赖排名不依赖分数，天然消除尺度差异（余弦 0-1 vs bigram 计数）。

**3. 为什么 rerank 用 embedding 相似度而不是 LLM 打分？**

LLM 打分慢且贵（每条候选一次调用）。embedding 重排在本地毫秒级完成，实测已能把 Recall@1 从 44.4% 提到 61.1%。真实项目里可以升级成 cross-encoder。

## 测试

```bash
python -m unittest ragscope.tests.test_ragscope -v    # 18 条，全离线
```

覆盖：切分边界（标题链保留 / 短片段丢弃 / 超长二次切分带重叠 / 无标题纯文本）、
指标计算（Recall@k / MRR / 多可接受答案匹配）、失败归因（排名靠后 vs 没召回）、
加载器（md/docx/pdf，docx 保留标题层级）、embedder（fit/transform、未 fit 报错）、检索（命中相关 chunk）。

**做了变异测试验证有效性**：故意把 `_match` 改成「永远返回 1」，4 条测试立即失败——说明测试在真验证行为，不是摆设。

## 已知局限

- 语料只有 89 个 chunk，规模偏小，数字只代表这个量级
- TF-IDF 不懂同义改写，口语化问题容易漏召回
- DSPy 优化在基线饱和时是负收益（已实测）
- 没有做多轮对话检索
