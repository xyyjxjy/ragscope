# 长跑参数与踩坑记录

跑一批几百条、几轮变异的任务，容易在时间、配额、断点上翻车。这里记的是实际踩过的坑。

## 长跑必须开断点

```bash
# 带变异的完整一轮：至少 2 轮，第 2 轮起才产生变体
python evolve.py run --cases attack_cases.yaml --rounds 4 --variants 2 \
    --checkpoint-every 5 --case-timeout 300 --out runs/hard_7b.json

# 被打断了（Ctrl-C / 关机 / 会话结束）就原样再来一次，加 --resume
python evolve.py run --cases attack_cases.yaml --rounds 4 --variants 2 \
    --checkpoint-every 5 --case-timeout 300 --out runs/hard_7b.json --resume
```

| 参数 | 默认 | 为什么必须有 |
|---|---|---|
| `--checkpoint-every N` | 5 | 之前只在**全部跑完**才 `json.dump` 一次。加固版那次跑到 40 分钟被中断，磁盘上 0 字节，只剩 5 行 stdout。现在每 N 条原子写一次 `<out>.partial.json`，轮次边界额外写一次并标 `current_round: null` |
| `--resume` | 关 | 读 `<out>.partial.json`，按 `(用例 id, 算子名)` 跳过已判过的，从断点轮次接着跑 |
| `--case-timeout S` | 300 | 加固版里 L-01 单条跑了 **9229 秒**（2.5 小时），httpx 的 180s 读超时管不到"工具循环里多次调用累计"。超时记 SKIPPED，不进分母 |
| `--workers N` | 1 | 每条载荷是一次独立的 agent 会话（`run_agent` 内全是局部变量），并发不改变单条结论，只压缩墙钟时间。串行 90 条 × 90s ≈ 2.5 小时，6 轮跑不完。**代价是会撞网关 RPM**：实测 6 并发时约 17% 的变体调用吃 429/读超时，记 `variants_skipped`（不进分母、也不算变体数），低于 4 并发基本不撞 |

## 坑 1：`--rounds 1` 看起来像"变异没效果"

`--rounds 1` 是"只跑种子轮"，`variants` 恒为空——想看变异就必须 `--rounds ≥ 2`。

之前三次真跑全部写了 `--rounds 1`，于是 `runs/*.json` 里 `variants: []`、`rounds` 数组长度为 1，看起来像"变异没效果"，实际是**变异一次都没发生**。

## 坑 2：断点续跑时，超时的 seed 被静默当成"未攻破"

旧逻辑把超时/429 的 seed 置成 `None`、从 `runtime_skip` 里 pop 掉，又因为 `retry` 不回退轮次，导致这些用例既不重跑、也不再算 SKIPPED——**静默进了分母被算成"未攻破"**。

这是"没拿到证据 ≠ 防御成功"这个 bug 的第三次变体。现在 `retry` 里的用例一律退回轮次 1 重跑。

## 坑 3：变体超时把整条用例踢出分母

变体超时曾按 case id 记进 `runtime_skip`，导致**已判过的用例整条被剔除**——分母缩水，ASR 虚高（实测把真实的 37.5% 报成 54.0%）。

现在变体超时只记 `variant_skip`，seed 有依据就留在分母。

## 坑 4：并发跑批被网关配额咬住

实测 `--workers 6` 时 318 个变体里 56 个（17.6%）撞 429 或读超时，以 `variants_skipped` 记账：不进分母、也不计入变体数。

报告的数据卫生检查会单独列出，**不要把「318 个变体」读成「318 次有效尝试」**。想补齐只能降并发重跑，墙钟成本翻倍。

## 坑 5：`LLM_MODEL` 必须和 `ollama list` 一字不差

默认值是 `qwen2.5:7b`，本机没拉过这个模型，于是每次请求都是 `404 model not found`——上一轮这个错误被记成「未攻破」，报告显示 0/7 = 0%（模型很稳）。

现在请求失败一律 SKIPPED 并单独计数，`summary.skipped_runtime` 会写清楚有几条没拿到依据。

## 坑 6：`LLM_HTTP_TIMEOUT` 决定长尾有多长

默认 180s 对 flash-lite 太宽松：正常返回 2–20s，卡住的请求要等满 3 分钟才轮到下一条。设 60s 后同样的批跑少了一半空洞等待，代价是极端长思考会被判超时重试（重试 5 次仍失败才记 SKIPPED）。

## 坑 7：`.env` 没加载会伪装成"服务挂了"

`llm_client.py` 之前不自己 `load_dotenv()`，单独跑一个 `import llm_client` 的脚本时 `LLM_BASE_URL` 落到默认 `localhost:11434`（Ollama 未运行）→ 报 `APIConnectionError`，看起来像云端服务挂了，实际是环境变量没读。现在模块顶部自己 load（幂等）。

同类坑：`openai 3.48 + httpx 0.28` 下**不要传自定义 `http_client`**，否则 SDK 抛 `APIConnectionError`（裸 httpx 直连却 200）。改用 SDK 原生 `timeout` / `max_retries`。

## 跑之前先 caps

```bash
python evolve.py caps
```

它会打印目标的工具清单，以及 AgentDojo 那 27 条里有几条真的能判（本机 target 是 7 可判 / 20 无攻击面）。

## 带外信标给远程目标用

```bash
python evolve.py run --transport http --url ... \
    --oast --oast-host 你的公网域名 --oast-port 80
```
