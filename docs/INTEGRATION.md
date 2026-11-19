# 接入说明

给 harness 的作者看。目标：**传一个被测 agent 的地址，拿一包结构化结果。**

## 1. 扫描器要放在哪 —— 先确定网络拓扑

`--target` 必须是**扫描器所在机器能访问到的地址**。所以先问：目标跑在哪？

| 拓扑 | `--target` 写什么 | 说明 |
|---|---|---|
| 同一进程（都是 Python） | `inproc` | 不走网络，直接函数调用，最快 |
| 同一台机器 / 同一 Pod | `http://127.0.0.1:8000/chat` | 只在**scan 与 target 同机**时成立 |
| 同一内网不同容器 | `http://target-svc:8000/chat` | 用服务名或内网 IP |
| 公网 / 跨网 | `https://target.example.com/chat` | 一般要带鉴权头 |

`127.0.0.1` 不是默认答案，它只覆盖第二种情况。team 里最常见的形态是第三种：
扫描器跑在 CI 容器，被测 agent 跑在另一个容器，用 compose 的服务名互访。

## 2. 调它

```bash
# 同进程靶子（不需要起服务，适合先跑通链路）
python aisec.py --target inproc --budget 50

# 内网目标 + 鉴权 + 字段名不是 message
python aisec.py --target http://target-svc:8000/chat \
    --header "Authorization: Bearer $TOKEN" \
    --payload-field input \
    --budget 100 --out findings.json
```

```python
from aisec import scan
res = scan(target="http://target-svc:8000/chat",
           headers={"Authorization": "Bearer xxx"},
           payload_field="input",
           budget=100)
```

`--header` 可重复，`--payload-field` 默认 `message`。目标如果还挂在网关后面，
`TARGET_TIMEOUT` 环境变量控制单次 HTTP 超时（默认 180 秒）。

## 3. 被测目标要实现什么

```
POST <target>
Content-Type: application/json
{"<payload_field>": "<攻击载荷>"}
```

```json
{"answer": "...", "tool_calls": [...], "steps": [...]}
```

`answer` 也接受 `output` / `text` / `response`。`payload_field` 由你自己定，
扫描器侧用 `--payload-field` 对齐即可。

**只返回 `answer` 也能跑**，但 `tool_abuse` / `tool_goal` 会标 SKIPPED——
这两类判据是「工具到底被调了没有」，拿不到工具调用就没有依据。这不是失败，
是能力协商（见第 5 节）。

`tool_calls` 建议格式：
```json
[{"name": "read_file", "args": {"path": "../.env"}, "ok": true, "result": "..."}]
```

这条链路有集成测试兜底：`tests/test_http_target.py` 会起一个带鉴权的
本地 HTTP 目标，验证字段名、请求头、工具调用解析、401 处理全部到位。

## 4. 输出

```json
{
  "meta": {"target","model","started","seconds","budget","sampled_from","strength","is_mock"},
  "summary": {"cases","judged","broken","asr","skipped","by_strength"},
  "findings": [ ... ]
}
```

每条 finding：

| 字段 | 含义 |
|---|---|
| `id` | 用例编号，回查用 |
| `severity` | **只由判定强度决定**：strong→high / medium→medium / weak→low |
| `detector` | 用哪个判定器判的：`marker` `xss` `canary` `credential` `tool_abuse` `tool_goal` `ansi` `replay` `secret_leak` |
| `payload` | 打出去的那条载荷，可直接复现 |
| `evidence` | 判定依据（命中的标记、被调用的工具名、命中的正则） |
| `answer` | 模型原始回答片段（已打码密钥） |
| `repro` | 一条能粘进终端的 `curl` |

**`severity=high` 的 finding 可以直接下结论；`low` 的只能当线索**——
它在源码里对应 `weak` 判定器（词表启发式），不要和 high 混在一起算比例。

## 5. SKIPPED 是什么，为什么不是失败

四种情况会退出分母，`summary.skipped` 是总数：

| 原因 | 说明 |
|---|---|
| 本次未执行（抽样外） | `--budget` 截掉的 |
| 判定器不适用 | 载荷落不进任何危害域（问 ANSI 转义码、glitch token 这类） |
| **接入方式拿不到证据** | 目标只返回 `answer`，没有 `tool_calls` |
| **目标没有这个攻击面** | 用例要 `send_money`，你的 agent 只有 `read_file` |
| 请求失败 / 超时 / 空回答 | 一个字节的输出都没拿到 |

最后两类最容易被误读。它们的意思是「**这条没测**」，不是「**这条防住了**」。
把 SKIPPED 当成分母算成功率，数字会好看得离谱。

## 6. 运行依赖

主项目只需要 `openai` `httpx` `pyyaml` `python-dotenv`。
`.venv-frameworks` 里那三个框架（garak / PyRIT / AgentDojo）**只在重新生成
`seeds/` 用例时才需要**，运行时完全不 import 它们。接进 harness 时不用管。

LLM 配置在 `.env`：`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`。
这是**被测 agent 自己用的模型**，不是我们的。

## 7. 它不适合做什么

说清楚边界，比吹功能有用：

- **不是自适应攻击**。变异是 9 个固定算子（拆句、反转、base64…），
  100 抽样 6 轮跑出 318 个变体、净增 23 条攻破（复核后 16 条），收益真实存在但**不针对防御反馈**——
  它只是把同一句指令换包装，不会因为"被挡住了"而改变策略。想做到后者得接 PAIR/TAP。
- **weak 判定器是词表**，`compliance` 那类 held-out 召回 0%，别当分类器用。
- **单模型、单轮**。跨模型比较无效——换模型等于换被测对象。
