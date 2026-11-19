# AgentProbe

> Apache-2.0 · [LICENSE](LICENSE) · 第三方数据出处见 [NOTICE](NOTICE)

面向 LLM 智能体的提示注入自动化测评工具：批量投递载荷 → 自动判定是否打穿 → 跑变异 → 输出加固前后对比的报告。

> ⚠️ **只测你自己部署的智能体。** 仓库里的 `target/` 是为测试而写的脆弱样本，不对任何真实业务系统发请求。使用边界见文末。
> 禁止一切违法违规行为！！！

---

## 30 秒上手

```bash
pip install -r requirements.txt
cp .env.example .env          # 然后填一个模型配置
python run_once.py list       # 看有哪些用例
python run_once.py run D-01   # 跑第一条
```

推荐本地 Ollama（免费、不限量）：

```bash
ollama pull qwen2.5:7b
```

`.env` 填：

```
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:7b
```

## 常用命令

| 目的 | 命令 |
|---|---|
| 看目标能判什么（工具清单 / 可判条数） | `python evolve.py caps` |
| 测仓库自带靶子（脆弱版） | `python evolve.py run --transport in_process` |
| 测加固版 | `python evolve.py run --transport in_process --hard` |
| 测远程智能体 | `python evolve.py run --transport http --url http://你的地址/chat` |
| 干跑验证闭环（不调模型） | `python evolve.py run --mock` |
| 带变异的完整跑 | `python evolve.py run --rounds 4 --variants 2 --checkpoint-every 5 --out runs/x.json` |
| 中断后续跑 | 同一条命令加 `--resume` |
| 生成报告 | `python report.py` → `REPORT.md` |
| 剔除「拒答时引用载荷」的假攻破 | `python rescore.py --run runs/x.json --write` |
| 单测 | `python -m unittest tests.test_detectors` |

长跑参数（`--checkpoint-every` / `--resume` / `--case-timeout` / `--workers`）怎么选，见 [docs/pitfalls.md](docs/pitfalls.md)。

## 它输出什么

```bash
python evolve.py run --cases seeds/garak_cases.yaml --rounds 1 --strength strong --out runs/xxx.json
python report.py
```

得到 `REPORT.md`：每次运行一行，含模型、判定数、ASR、变体数、请求失败数，并自动标出「干跑」「样本 < 30」「旧格式」这类不能引用的记录。示例见仓库根目录的 [REPORT.md](REPORT.md)。

`runs/` 下有两种产物，**不能混着引用**：`real_*.json` 是真模型真请求，`mock/*.json` 是桩件只能验证流程。

## 接自己的智能体

`transport.py` 是唯一需要动的地方，四种接入已就绪：

```bash
python evolve.py run --transport in_process          # 同进程（本仓库 target/）
python evolve.py run --transport http --url ...      # 远程 HTTP
python evolve.py run --transport mock                # 桩件
```

远程目标期望的响应体（字段名宽容匹配）：

```json
{"answer": "...", "tool_calls": [...], "steps": [...]}
```

只返回 `answer` 的会自动降级成 `blackbox`——这时 `tool_abuse` 类用例标 SKIPPED，**判不了的样本不进分母**。带外信标给能出网的目标用：

```bash
python evolve.py run --transport http --url ... --oast --oast-host 你的域名 --oast-port 80
```

想把测评器当库调（`aisec.scan(target, budget)`），见 [INTEGRATION.md](INTEGRATION.md)。

## 目录结构

```
agentprobe/
├── detectors.py       # 12 个判定器，按 strong/medium/weak 分层
├── transport.py       # 被测对象接入层（in_process / http / blackbox / mock）
├── evolve.py          # 编排：跑 → 判 → 变异 → 再跑 → 收敛
├── mutator.py         # 载荷变异器（9 个规则算子 + 可选模型变异）
├── report.py          # runs/*.json → REPORT.md（含数据卫生检查）
├── rescore.py         # 离线复核，旁路不改原始数据
├── frr.py             # 误拒率（FRR）测量
├── calibrate.py       # 弱判定器校准闭环
├── oast.py            # 带外信标接收端
├── importers/         # garak / PyRIT / AgentDojo / HarmBench 接入
├── seeds/             # 导入产出的载荷集
├── runs/              # 运行产物（real_*.json 入库，mock/ 不入库）
├── tests/             # 80 条单元测试
├── targets/           # 对照组：LangChain 版智能体
└── target/            # 被测靶子（故意脆弱）
```

## 文档

| 文档 | 讲什么 |
|---|---|
| [docs/design.md](docs/design.md) | canary token、12 个判定器、为什么「判定比攻击难」、刻意留的脆弱点 |
| [docs/results.md](docs/results.md) | 所有实测数字：ASR×FRR 三目标对照、变异收益、显著性检验 |
| [docs/pitfalls.md](docs/pitfalls.md) | 长跑参数、断点续跑、并发与限流、踩过的坑 |
| [docs/known-issues.md](docs/known-issues.md) | 已知限制、不适用的场景、判定器边界 |
| [docs/ci.md](docs/ci.md) | CI 检查了什么 |
| [frr_report.md](frr_report.md) | FRR 测量完整报告 |
| [INTEGRATION.md](INTEGRATION.md) | 作为库接入（固定 schema） |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 怎么加判定器、怎么加用例 |
| [SECURITY.md](SECURITY.md) | 安全策略与漏洞报告渠道 |

## 联系与贡献

| 想做什么 | 去哪 |
|---|---|
| 提问题、报 bug、给建议 | [GitHub Issues](https://github.com/xyyjxjy/agentrobe/issues) |
| 提交代码 / 加判定器 | 先读 [CONTRIBUTING.md](CONTRIBUTING.md) |
| **报告安全漏洞** | **不要开 public issue** → 仓库页 `Security` → `Report a vulnerability`（私密，只有维护者可见） |
| 许可与数据再分发 | 见 [NOTICE](NOTICE) |

不需要邮箱：Issue 和私密漏洞报告都能直接找到我。漏洞报告请附**可复现命令**；涉及密钥时只说位置，不要贴内容。

## 使用边界

- ✅ 测**你自己部署**的智能体（本地、自有服务器、自建靶场）；测**书面授权**的系统；教学与研究
- ❌ 测不属于你的线上智能体/服务；未授权访问、数据窃取、服务干扰；把变异载荷用于真实攻击
- 本工具按 **"AS IS"** 提供，**使用者自负全部后果**，作者与贡献者不承担任何责任
- 你所在地区若限制此类工具，请不要使用

## 许可

Apache-2.0（含专利授权与商标条款）。第三方数据的出处与再分发依据见 [NOTICE](NOTICE)——其中 **HarmBench 条款限制再分发，其派生数据不入库**，clone 下来是没有的，需自行 `python importers/harmbench.py --download`。
