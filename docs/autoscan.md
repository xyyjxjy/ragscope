# AgentProbe AutoScan — 一键式自动化测评平台

把 AgentProbe 引擎包装成平台：**给一个目标 URL，自动跑完全流程，出报告 + 加固建议**。

## 一键演示（clone 下来就能跑）

```bash
python -m autoscan.server          # http://127.0.0.1:8400
```

浏览器打开 → 点「用内置靶子演示」。平台会：

```
① 探测  → 内置靶子声明能返回 answer + tool_calls
② 选型  → 自动选 strong 判定器（marker/xss/tool_abuse 等）
③ 测评  → 调 evolve.py：72 条载荷 + 变异 + 收敛（1 轮 ≈ 1 分钟）
④ 建议  → 按攻破判定器反推该补什么防御，分 P0/P1/P2
⑤ 报告  → ASR + 分层统计 + 逐条加固建议
```

实测结果：72 条可判、18 条攻破、ASR 25.0%，识别出 4 类 P0 防御（marker 7 条、xss 5 条……）。

真实目标：在输入框填 `http://你的agent:端口`，平台会读目标的 `/capabilities`（没有就降级为 answer 级判定器），然后投递到 `/chat`。

## 架构

```
autoscan/
├── server.py        FastAPI：POST /api/scan + GET /api/job/{id} + 前端
├── pipeline.py      AutoScan 状态机：probe→select→campaign→advise→done
├── advice.py        判定器→加固建议映射（P0/P1/P2 分级）
├── demo_target.py   内置脆弱靶子（返回 answer + tool_calls）
└── static/index.html 单页 UI：一键提交 + 进度 + 报告
```

**与 evolve.py 的关系**：evolve.py 是测评引擎（CLI），autoscan 是编排平台。平台用子进程调引擎，通过日志读进度——不污染引擎全局状态。

## 平台比裸引擎多什么

| 裸引擎（evolve.py） | 平台（autoscan） |
|---|---|
| 要记一堆 CLI 参数 | 一个 URL 就够 |
| 手动看 caps 选判定器 | 自动探测 + 选型 |
| 出 ASR 数字 | 出数字 **+ 该怎么改**（加固建议） |
| 命令行进度 | Web 实时进度 + 报告 |
| 单目标 | 内置靶子 + 任意 URL |

## 工程细节（面试可讲）

- **Windows 文件锁**：平台轮询进度时不能打开 partial.json——会撞上引擎的原子写（`os.replace`）导致 WinError 5。改成读日志尾部提取进度；同时给 `os.replace` 加了重试。
- **stdout PIPE 死锁**：子进程输出必须重定向到文件，不能用 PIPE 却不消费（缓冲满会阻塞子进程）。
- **URL 规范化**：用户填 host 或 host/chat 都能正确投递到 /chat 端点。
- **状态机**：JobStatus 对象维护 5 阶段状态，支持并发任务，前端轮询进度。

## 测试

```bash
python -m unittest tests.test_autoscan -v    # 3 条，离线
python -m unittest discover -s tests         # 全量 91 条
```
