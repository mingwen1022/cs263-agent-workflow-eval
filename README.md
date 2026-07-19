# CS263 Agent Workflow Evaluation

**把一个单 Agent 的决策循环拆成多个专业化 LLM 节点，到底让它更可靠，还是引入了新的失败模式？**

在同一个基准、同一批任务、同一套评分口径下，实现并对比四种多轮 tool-calling Agent 架构，只改变"决策怎么被拆分"，回答一个具体问题：**分工增益和误差累积，哪个更大。**

## 评测设置

- **基准**：[tau2-bench](https://github.com/sierra-research/tau2-bench) retail 域
- **任务**：50 个客服任务（换货 / 退货 / 取消 / 改单），每个由 user simulator 驱动 10~20 轮对话，Agent 需调用 16 个读/写工具完成
- **评分**（二元，两项都过才得 1 分）：
  - **DB Check**：对话结束后数据库状态与 ground truth 完全一致（衡量"有没有真的把操作做对"）
  - **NL Assertion**：最终回复满足语义要求（衡量"有没有把结果/政策说清楚"）
- 开发集用前 20 个任务做诊断，最终对比用完整 50 个任务，`temperature=0`、seed 固定

## 对比的四种架构

| # | 架构 | 说明 |
|---|---|---|
| ① | **Flat 单 Agent** | 单个 LLM 跑完整决策循环（baseline） |
| ② | **四节点 LLM 工作流** | 状态跟踪 / 推理 / 校验 / 执行各一个 LLM 节点 |
| ③ | **Planner-Executor** | LLM 规划 + LLM 执行 |
| ④ | **SMAG** | 把状态追踪与前置校验交给确定性 Python 状态机，LLM 只做推理 |

## 核心结果

| 架构 | Success Rate (50 任务) |
|---|---|
| ② 四节点 LLM 工作流 | 0.34 |
| ③ Planner-Executor | 0.38 |
| ① Flat 单 Agent（baseline） | 0.54 |
| ④ **SMAG（确定性状态机）** | **0.62** |
| ④ SMAG · 本地 4.5B 小模型 | 0.58 |

**结论：**
1. **拆成更多 LLM 节点反而更差**——②③ 都低于不拆的 baseline ①。
2. **增益来自把状态与校验交给代码**——SMAG（④）用确定性 Python 做状态追踪 + 前置校验，最好（0.62）。
3. **架构 > 模型规模**——本地 4.5B 小模型跑 SMAG（0.58）反超大模型跑 Flat（0.54）。
4. **多节点的问题不在写精度，在校验误判**——工作流和 SMAG 的写参数错误数完全一样（都 9/50），但工作流多出 11 次"放弃任务"：LLM 做校验会误判，误判导致放弃。

诊断口径（前 20 任务）还把"Success Rate"这个单一数字拆成可分别改进的维度：Flat 大模型读准确率 87%、写精度 57%——写才是瓶颈，这也是 SMAG 用代码兜住写操作的动机。

## 仓库结构

```
src/cs263_agent_eval/     # 核心：benchmark / tools / tau2 / workflows / agents / eval
scripts/                  # 五种架构各一个运行脚本
  run_tau2_large_single.py     # ① Flat 大模型
  run_tau2_small_single.py     # ① Flat 小模型
  run_tau2_workflow.py         # ② 四节点工作流
  run_tau2_planner_executor.py # ③ Planner-Executor
  run_tau2_smag.py             # ④ SMAG
configs/tau2/retail_50.json    # 任务集配置
results/ · reports/            # 运行产物与汇总
docs/                          # 实验报告、SMAG 设计、架构设计文档
```

## 运行

用 [`uv`](https://github.com/astral-sh/uv) 管理依赖：

```bash
uv sync
uv run check-models                        # 检查模型接口连通
uv run python scripts/run_tau2_smag.py     # 跑 SMAG（其余架构换对应脚本）
```

`.env` 需包含 `PROJECT_ID`（Vertex），可选 `GOOGLE_API_KEY`；本地小模型走 Ollama。

## 说明

本项目仅借鉴既有项目的**模型接口调用方式**（`ChatVertexAI` 的参数形状等），**不复用**其数据、任务、gold label、prompt 或实验结果；tau2-bench 作为第三方基准以 submodule 引入。
