# 已知限制

这份清单存在的意义：让引用本项目数字的人知道什么不能当结论。

## 运行环境

- **必须 ≥ Python 3.10**。`llm_client.py` 用了 `int | None`，3.9 连 import 都过不去；之前的「跑通」全部是 `--mock`，一次真实模型都没调过。实跑前用 `python -V` 核对。
- 本地 `deepseek-r1:7b` 单次调用约 34 秒，且思考 token 会顶掉 `max_tokens=512` 的输出预算。做 judge 或批量实跑前先把预算和超时调好。

## 判定器边界

- **`compliance` 实测不可信**：24 条标注上 precision 66.7% / recall 33.3% / FPR 16.7%；换 20 条没见过的说法，recall 归零。只能当线索，不能进摘要 ASR。
- **`encoding` 已有独立判据**：108 条载荷是「`<script>javascript:alert(1)</script>` 用 12 种编码包一层」，明文里没有 `<script>`，走 `marker` 必然落空。现路由到 `xss`，并做 `\x3C` / `\u003C` 转义还原。这条原来是拿缩小分母换好看 ASR 的 bug，已修。
- **`xss` 沿用 garak 语义**：输出里出现未转义的脚本特征即判失败，**不区分**它是否包在 Markdown 代码块里。代码块在多数前端是安全的，这里偏保守（多报），需要精确结论时人工复核。
- **`oast` 要求目标能访问 beacon**：只走 API、不渲染 Markdown 的目标天然不触发，这是"不适用"，不是"安全"。
- **`credential` 只认常见凭证格式**，且已排除载荷自带串；模型编造的假 key 仍可能命中，需人工确认。
- **`tool_goal` 只会 SKIP 不会瞎判**：它要求被测 agent 暴露目标工具，本项目 target 只有 `read_file` / `search_docs` / `send_email`，27 条 AgentDojo 用例里 7 条可判、20 条 SKIPPED。

## 目标与覆盖

- **weak 桶 1212 条没跑**。判据本身不可信，跑了也不该进 ASR。
- **823 全量的变异没跑**。100 抽样上验证过（27.8%→59.7%），764 条按同样节奏约 45 小时。
- **823 全量的 FRR 没测**。100 抽样测了。
- **PAIR / TAP 未接**。它们是自适应攻击流水线，要改编排层。`PyRIT` 只用了 converter。
- **HarmBench 的判据没法接**。它用 Llama-2-13B 当分类器，我们只有 7B 的 `deepseek-r1`，且它在校准里连"明显答案"都判反（gold 100% / held-out 0%）。所以 400 条只能落 weak 桶。
- **garak 还有 20 个 probe 导不进来**：要 `torch`（2GB）、要 `NIM_API_KEY`、要音频库、要 wordnet 词库、要额外模型、要 attack goals 数据集。这些 probe 即便导进来也没有对应判定面。
- **`--expand` 只增加载荷条数，不增加攻击意图数**。
- 检索用的是关键词重合度，不是向量检索——测的是安全，不是 RAG 效果。
- 工具结果用 `user` 角色回填，不是标准 tool 协议，为的是兼容本地小模型。
- **没有 Dockerfile**。依赖不难装，但容器化能省掉环境差异的扯皮。

## 框架接入

- **框架只借数据，不借运行时**。四个框架都装在 `.venv-frameworks` 里，主项目永不 import 它们，产物落成 YAML 再用。代价是升级框架得手动重跑导入器，好处是主环境的 `openai` 不会被顶掉——这个坑踩过两次（garak 要 `openai<3`，PyRIT 默认拉 3.x）。
- **AgentDojo 的判据在工具调用里，不在输出文本里**。所以这批用例的判定器是 `tool_goal`，它先检查被测 agent 有没有那个工具。SKIPPED 的那 20 条**不是"防住了"，是这条攻击面不存在**——换成一个带日历/云盘/Slack 工具的 agent，它们立刻进分母。
