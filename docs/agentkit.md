# agentkit

从 AgentProbe 抽象出的**可复用 LLM Agent 开发框架**。

一句话：用统一的工具注册、trace 可观测、双编排实现和自带评测，把"写 agent"变成搭积木。AgentProbe 是它的第一个应用（安全测评）。

---

## 三层核心

```
┌─────────────────────────────────────────┐
│  EvalHarness      自带评测（你的差异点） │
├─────────────────────────────────────────┤
│  AgentRunner      ReAct / LangChain 双实现│
├─────────────────────────────────────────┤
│  ToolRegistry     工具 + schema + 权限钩子│
│  TraceStore       结构化 trace + 回放    │
└─────────────────────────────────────────┘
```

| 组件 | 作用 | 对应 JD 关键词 |
|---|---|---|
| `ToolRegistry` | 工具注册、参数校验、权限 guard、调用日志 | Function Calling、工具编排 |
| `Trace` / `TraceStore` | 每步决策、工具调用、耗时、回放 | 可观测、trace 分析 |
| `ReActRunner` | 手写循环（JSON 动作协议，兼容所有模型） | Agent 编排 |
| `LangChainRunner` | LangChain 1.x `create_agent`（原生 tool_calls） | LLM 框架 |
| `EvalHarness` | 断言 + 分层统计 + 报告 | 效果评测 |

---

## 30 秒上手（离线，无需 key）

```python
from agentkit import ToolRegistry, ReActRunner, Trace

tools = ToolRegistry()
tools.register(ToolSpec("lookup", "查资料", {"q": "str"},
                        lambda q: f"资料：{q}"))

# 假 LLM：真实场景换成 llm_client.chat 或 ChatOpenAI
llm = lambda messages: '{"final":"你好，我能查资料"}'
runner = ReActRunner(tools, llm, max_steps=4)
trace = runner.run("你好")
print(trace.answer, trace.to_dict())
```

跑测试：`python -m unittest tests.test_agentkit -v`（8 条，全离线）

## 真 LLM 演示（原生 function calling）

配好 `.env` 后（商汤/OpenAI 兼容端点，需支持 tool_calls）：

```bash
python -m agentkit.demo        # 命令行演示
python -m agentkit.ui          # Web UI：http://127.0.0.1:8300
```

## Web UI（可观测可视化）

```
python -m agentkit.ui
```

浏览器打开 `http://127.0.0.1:8300`：**左边聊天，右边 Trace 面板**实时显示 agent 的每一步决策、工具调用与结果。配了 key 用真 LLM（原生 function calling），没配 key 自动降级成离线假 LLM，保证可演示。

面试时可直接展示："模型第一次检索没命中，自己改写了查询词重试"——这是真 agent 的自适应行为。

实测会话（sensenova-6.8-flash-lite）：

```
输入: 跨省出差住宿标准是多少？
工具调用:
  1. search_docs("跨省出差住宿标准")      → 未命中
  2. search_docs("出差住宿费标准")        → 未命中
  3. search_docs("差旅费管理办法 住宿")   → 命中：450/600 元
回答: 一般城市 450 元/晚，一线城市 600 元/晚
步数 7 | 耗时 8.8s
```

**关键点**：模型在第一次检索失败后**自动改写查询词重试**——这是原生 function calling 的自适应行为，不是规则流水线能做到的。tool_calls 参数 schema 由 `ToolSpec` 显式构造 pydantic 模型导出（踩过的坑：靠 `**kw` 推断会让参数全塞进 `kw` 字段，导致模型无限重试）。

---

## 设计取舍（面试可讲）

**1. 为什么要两套 Runner？**

手写 ReAct 用 JSON 文本协议，任何模型（包括不支持 tool_calls 的 7B）都能跑；LangChain 用原生 tool_calls，更规范但依赖框架支持。

两套共享 `ToolRegistry` + `TraceStore`，输出统一 `Trace`，所以能在同一个 `EvalHarness` 下横向对比。实测：**同样载荷、同样防御，手写 ASR 12.5% vs LangChain 37.5%（p=0.0005）**——证明"编排实现本身是变量"。

**2. 可观测为什么是一等公民？**

`Trace` 记录每步 assistant 输出、每次工具调用的 name/args/结果、`finish_reason`、耗时。agent 出错时，`TraceStore.replay()` 能定位"哪一步开始错"——这正是企业落地 agent 时最缺的能力。

**3. 评测为什么内置？**

`EvalHarness` 直接复用判定器方法论：断言注册 + 强度分层（strong/medium/weak 禁止混算）+ 可复现报告。别的 agent 框架不带评测，这是 agentkit 从安全测评基因里带来的差异。

**4. 权限 guard 怎么用？**

```python
def path_guard(args):
    return "拒绝：路径越界" if ".." in args.get("path", "") else None

tools.register(ToolSpec("read_file", "读文件", {"path": "str"},
                        read_fn, guard=path_guard))
```
guard 返回非 None 即拒绝，调用仍记进 trace——安全策略可观测。

---

## 双视角描述（同一框架，两种讲法）

### 投 AI 开发岗

> 从零设计并实现可复用 LLM Agent 开发框架 agentkit：ToolRegistry（Function Calling schema + 参数校验 + 权限钩子）、TraceStore（结构化 trace + 回放）、AgentRunner（手写 ReAct + LangChain 1.x 双实现）、EvalHarness（断言 + 分层评测）。全部离线可跑，8 条单测覆盖。

### 投 AI 安全岗

> 将提示注入测评框架抽象为 agentkit，统一 ToolRegistry 与 TraceStore 作为可观测底座；在手写 ReAct 与 LangChain 双编排上跑同一评测集，量化"编排实现影响防御有效性"（12.5% vs 37.5%，p=0.0005）。

### 投安全开发岗

> 实现带权限钩子与调用审计的工具注册表：参数校验、路径穿越拦截、收件人白名单，所有调用写入 trace 可回放；配套分层断言与回归测试（88 条）。

---

## 项目关系

```
agentkit（框架）
   └── AgentProbe（应用：安全测评）  —— 2249 用例 / 12 判定器 / ASR×FRR
   └── 任意 agent（应用：你自己搭）  —— 换 Runner 即可复用工具与评测
```

同一套框架，既能造 agent，也能测 agent。这是这个重构的核心价值。
