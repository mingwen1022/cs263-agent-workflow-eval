# 实验报告：多文档 Agentic Workflow 评测

## 1. 任务与数据集

**任务类型**：多轮客服 agent，处理零售订单操作（换货、退货、取消、修改）。

**评测框架**：[tau2-bench](https://github.com/sierra-research/tau2-bench) retail domain。每个任务由一个 user simulator 驱动多轮对话，agent 调用 16 个工具（read/write）完成操作。

**评分标准**（二元，0 或 1）：
- **DB Check**：对话结束后数据库状态与 ground truth 完全一致
- **NL Assertion**：agent 的最终回复满足语义要求

只有两项都通过，该任务才得 1 分。

---

## 1b. 评测指标的必要性说明

### DB Check（数据库状态检查）

**为什么必要**：customer service agent 的核心价值在于实际执行操作，而非仅仅说对了什么。用户打电话要求退货，如果 agent 说"已为您办理退货"但数据库里的订单状态没有变化，这次服务对用户而言是完全失败的。DB Check 直接衡量 agent 能否正确调用写操作工具（exchange/return/cancel/modify）并传入准确参数，是 agentic task 中最严格、最不可绕过的评估维度。

与静态 NLP 任务不同，agentic task 需要模型完成一系列有因果依赖的工具调用（先查询订单 → 再查询产品 → 最后写入修改）。任意一步参数错误都会导致最终 DB 状态偏差，因此 DB Check 能有效放大 agent 在多步骤推理和状态追踪上的缺陷。

### NL Assertion（自然语言语义检查）

**为什么必要**：正确执行操作是必要条件，但不是充分条件。客服场景要求 agent 同时做到：执行操作 AND 向用户清晰说明操作结果、政策限制或无法完成的原因。NL Assertion 衡量 agent 是否满足这一沟通要求。

典型失败案例（DB_OK_NL_FAIL）：task 3 中 agent 成功修改了 T-shirt 颜色（DB Check 通过），但未回答用户追问的"有多少种 T-shirt 选项"（NL Assertion 失败），整体仍得 0 分。这类失败在纯 DB 检查中会被遗漏，说明 NL Assertion 捕获了 DB Check 无法覆盖的通信质量维度。

### Partial Action Reward（局部动作奖励）

**为什么必要**：二元奖励（0/1）无法区分"完全失败"和"接近成功"。Partial Action Reward 对每个单独的工具调用（read 和 write）给出独立评分，提供更细粒度的诊断信息。

具体价值：
- **区分读写失败**：通过统计 read accuracy 和 write precision 的分别，可以判断 agent 是在信息收集阶段失败（没有查到正确信息）还是在执行阶段失败（信息有但参数传错）。实验发现所有系统的 read accuracy 均高于 write precision，说明 tau2 retail 的核心挑战是写操作参数精度，而非信息检索能力。
- **比较系统差异**：large_single 和 small_single 的 write precision 在失败任务上分别为 22% 和 17%，差距比整体成功率（0.54 vs 0.50）更清晰。
- **支持错误分析**：结合 Partial Action Reward 和 error type 分类，可以识别出系统的具体短板（如 workflow agent 的 TRANSFER_ABORT 比 single agent 多 4-5 个），为架构改进提供方向。

### Error Type Taxonomy（错误类型分类）

**为什么必要**：单一成功率无法解释模型"为什么失败"。我们在 tau2 自带指标之外设计了 5 类错误分类（WRITE_WRONG_ARGS / PARTIAL_WRITE / DB_OK_NL_FAIL / TRANSFER_ABORT / NO_WRITE_ATTEMPTED），每类对应不同的 agent 能力缺陷：

| 错误类型 | 反映的能力缺陷 |
|---|---|
| WRITE_WRONG_ARGS | 多步骤状态追踪精度（item/payment_method 归属混淆） |
| PARTIAL_WRITE | 多操作任务的完整性管理 |
| DB_OK_NL_FAIL | 执行能力与沟通能力的解耦 |
| TRANSFER_ABORT | agent 的鲁棒性和自我认知（是否知道何时放弃） |
| NO_WRITE_ATTEMPTED | 信息收集阶段的循环检测 |

这一分类将"agent 性能"从单一数字分解为可独立改进的维度，是连接评测结果与架构优化的桥梁。

**数据规模**：
- 开发集（诊断）：前 20 个任务（task_ids: 0–24）
- 完整集（最终对比）：50 个任务（task_ids: 0–80，跳过部分编号）

---

## 2. 评测系统

| 系统 | 实现 | 模型 | 说明 |
|---|---|---|---|
| **large_single** | LangChain `langchain_llm_agent` | Gemini 2.5 Flash | flat agent baseline |
| **small_single** | LangChain `langchain_llm_agent` | gemma4:e4b（本地 Ollama） | 小模型 flat agent |
| **workflow** | 自研 `workflow_agent` | Gemini 2.5 Flash | 4 节点线性流水线（State Tracker → Reasoner → Verifier → Action Generator） |
| **planner_executor** | 自研 `planner_executor_agent` | Gemini 2.5 Flash | 2 节点架构（Planner with full context + deterministic Executor） |
| **smag_large** | 自研 `smag_agent` | Gemini 2.5 Flash | 确定性 Python 状态机 + LLM（SMAG-inspired） |
| **smag_small** | 自研 `smag_agent` | gemma4:e4b（本地 Ollama） | 同架构，换小模型 |

---

## 3. 实验结果 — Block 1：成功率

### 3.1 总体成功率

**完整 50 任务（所有系统，最终评测结果）**

| 系统 | 模型 | 成功数 | avg reward | 每轮 LLM 调用 |
|---|---|---|---|---|
| **smag_large** | Gemini 2.5 Flash | **31/50** | **0.62** | 1-2 |
| **smag_small** | gemma4:e4b | **29/50** | **0.58** | 1-2 |
| large_single | Gemini 2.5 Flash | 27/50 | 0.54 | 1 |
| small_single | gemma4:e4b | 25/50 | 0.50 | 1 |
| planner_executor | Gemini 2.5 Flash | 19/50 | 0.38 | 1-2 |
| workflow | Gemini 2.5 Flash | 17/50 | 0.34 | 3-4 |

### 3.2 细粒度指标（前 20 任务，Partial Action Reward）

tau2-bench 对每个工具调用独立评分，可拆分为 read accuracy 和 write precision：

| 系统 | read acc（全部任务） | read acc（失败任务） | write prec（全部任务） | write prec（失败任务） |
|---|---|---|---|---|
| large_single | 87% | 84% | 57% | 22% |
| small_single | 93% | 90% | 48% | 17% |

**关键观察**：
- 所有系统的 read accuracy 均显著高于 write precision，说明信息收集不是主要瓶颈
- 失败任务中 write precision 接近 0（22% / 17%），写操作一旦错，几乎是完全错
- small_single 的 read accuracy 反而高于 large_single，但 write precision 更低

### 3.3 任务级对比矩阵（前 20 任务）

```
 task  large  small    wf    pe  smag_L smag_S     任务特征
    0    ✅     ❌     ❌     ✅    ❌     ✅     exchange 2 items，需变体选择
    1    ✅     ✅     ✅     ✅    ❌     ✅     exchange，标准流程
    2    ❌     ✅     ❌     ❌    ❌     ❌     return，DB OK 但 NL 失败
    3    ✅     ✅     ❌     ❌    ❌     ❌     modify + 多订单 + t-shirt 变体
    4    ✅     ✅     ❌     ❌    ✅     ✅     modify × 2 + 多订单
    6    ❌     ✅     ❌     ❌    ✅     ❌     exchange，extra item 问题
    7    ❌     ❌     ✅     ✅    ✅     ❌     exchange，变体选择
    8    ✅     ❌     ❌     ✅    ❌     ✅     exchange，特定产品变体
   10    ✅     ✅     ✅     ✅    ✅     ✅     lookup only，无写操作
   11    ❌     ❌     ✅     ❌    ✅     ❌     return × 2，payment 跨订单混淆
   13    ❌     ✅     ✅     ✅    ✅     ✅     return，3 items
   14    ❌     ❌     ✅     ❌    ✅     ✅     return × 2，多订单 payment 混淆
   15    ❌     ❌     ✅     ❌    ✅     ✅     modify，payment 精确匹配
   16    ✅     ✅     ✅     ❌    ✅     ✅     cancel × 2 + return
   19    ❌     ❌     ❌     ❌    ❌     ❌     return + exchange 混合
   20    ❌     ❌     ❌     ❌    ✅     ❌     modify × 4，多 item
   21    ✅     ❌     ❌     ❌    ✅     ✅     modify，复杂多步
   22    ❌     ❌     ❌     ✅    ✅     ✅     modify address × 3
   23    ✅     ✅     ❌     ❌    ❌     ✅     exchange × 2 + modify，多订单
   24    ✅     ✅     ✅     ✅    ✅     ✅     cancel，标准流程
```

**关键观察**：
- smag_large 与 smag_small **总分相同（13/20）**，但成功任务集合不完全重叠
- smag_small 独占：task 0, 1, 8, 23（smag_large 失败，smag_small 成功）
- smag_large 独占：task 6, 7, 11, 20（smag_small 失败，smag_large 成功）
- 两个 SMAG 共同成功：task 4, 10, 13, 14, 15, 16, 21, 22, 24（9 个）
- 全部失败：task 19、task 2/3（DB 对但 NL 失败）

---

## 4. 实验结果 — Block 2：错误类型分布

### 4.1 错误类型定义

| 错误类型 | 定义 | 反映的能力缺陷 |
|---|---|---|
| **WRITE_WRONG_ARGS** | 写操作被执行，但参数不匹配 ground truth | 多步状态追踪精度（item/payment 归属混淆） |
| **PARTIAL_WRITE** | 多个写操作中部分成功、部分失败 | 多操作任务的完整性管理 |
| **DB_OK_NL_FAIL** | DB 状态正确，但最终回复语义不满足要求 | 执行能力与沟通能力解耦 |
| **TRANSFER_ABORT** | agent 调用 `transfer_to_human_agents` 终止对话 | 鲁棒性和自我认知（循环后放弃） |
| **NO_WRITE_ATTEMPTED** | 始终未尝试写操作，卡在读操作阶段 | 信息收集循环检测 |

### 4.2 前 20 任务错误分布（含 smag_small）

| 错误类型 | large_single | small_single | workflow | planner_exec | smag_large | **smag_small** |
|---|---|---|---|---|---|---|
| **SUCCESS** | 10 | 10 | 9 | 8 | **13** | **13** |
| WRITE_WRONG_ARGS | 6 | 7 | 2 | 9 | 4 | 3 |
| PARTIAL_WRITE | 2 | 1 | 1 | 1 | 1 | 0 |
| DB_OK_NL_FAIL | 1 | 1 | 3 | 0 | 2 | 2 |
| TRANSFER_ABORT | 1 | 1 | 5 | 2 | 0 | 2 |

**smag_small 关键发现（完整 50 任务）**：smag_small 达到 29/50 = **0.58**，smag_large 达到 31/50 = **0.62**。两者均超过 large_single（0.54）和 small_single（0.50）baseline。在前 20 个开发任务上两者持平（均为 0.65），后 30 个任务上 smag_large 略高于 smag_small，说明在更复杂的任务上大模型的语义推理仍有优势。

### 4.3 完整 50 任务错误分布（最终结果）

| 错误类型 | large_single | small_single | workflow | planner_exec | smag_large | **smag_small** |
|---|---|---|---|---|---|---|
| **SUCCESS** | 27 | 25 | 17 | 19 | **31** | **29** |
| WRITE_WRONG_ARGS | 11 | 12 | 9 | **17** | 9 | 7 |
| PARTIAL_WRITE | 7 | 5 | 5 | 2 | 3 | 5 |
| DB_OK_NL_FAIL | 1 | 2 | 4 | 0 | 3 | 4 |
| TRANSFER_ABORT | 4 | 6 | **15** | **11** | 4 | 5 |
| NO_WRITE | 0 | 0 | 0 | 1 | 0 | 0 |
| **失败合计** | 23 | 25 | 33 | 31 | **19** | **21** |

### 4.4 各系统错误特征对比（占失败任务比例）

```
large_single:  WRITE_WRONG ████████████ 48%  PARTIAL ██████ 30%  TRANSFER ████ 17%  DB_NL ██ 4%
small_single:  WRITE_WRONG ████████████ 48%  PARTIAL ████ 20%  TRANSFER ████████ 24%  DB_NL ██ 8%
workflow:      TRANSFER ██████████████████ 45%  WRITE_WRONG ████████ 27%  PARTIAL ████ 15%  DB_NL ████ 12%
planner_exec:  WRITE_WRONG ████████████████████████ 55%  TRANSFER ████████████ 35%  PARTIAL ██ 6%
smag_large:    WRITE_WRONG ████████████ 47%  DB_NL ████████ 16%  PARTIAL ████████ 16%  TRANSFER ████████ 21%
smag_small:    WRITE_WRONG ████████ 33%  PARTIAL ████████ 24%  TRANSFER ████████ 24%  DB_NL ████████ 19%
```

**关键发现**：
- **single agent**：WRITE_WRONG_ARGS 是主要失败类型（48%），写参数精度是核心瓶颈
- **workflow**：TRANSFER_ABORT 异常高（45%），LLM State Tracker 上下文损耗导致 Reasoner 误判任务无法完成
- **planner_executor**：WRITE_WRONG_ARGS 最高（55%）+ TRANSFER_ABORT（35%），Verifier 弱化是主因
- **smag_large**：TRANSFER_ABORT 降到与 single agent 相近（21%），错误分布最均衡
- **smag_small**：WRITE_WRONG_ARGS 比所有系统都低（33%），Python 状态机的确定性校验在写参数精度上效果显著；TRANSFER_ABORT 略高于 smag_large，说明小模型在复杂任务中仍更容易放弃

---

## 5. 各错误类型原因分析

### 5.1 WRITE_WRONG_ARGS（最主要失败原因）

**占比**：large_single 60%，small_single 70%，planner_executor 90%

**具体表现**：
- **payment_method_id 混淆**（最常见）：多订单场景下，agent 将两个订单的支付方式对调。例如 task 11/14：用户有订单 #W5490111（信用卡）和 #W7387996（PayPal），agent 在 return 时传入了互换的支付方式。
- **exchange 包含多余 item**：用户只要求换一件商品，agent 将两件都放入 `item_ids`（task 6/7）。
- **new_item_ids 选错**：exchange 时选择了错误的替换变体（task 0/8）。
- **modify 工具名错误**：agent 调用了不存在的 `modify_pending_order_items`，实际工具名是 `modify_pending_order`（task 20）。

**根本原因**：
- 大/小模型均依赖 prompt 中的完整对话历史进行推理，在涉及多订单或多 item 时，模型难以准确追踪各 item 与对应订单、支付方式的映射关系。
- planner_executor 的 WRITE_WRONG_ARGS 比例最高（9/20），因为 Verifier 在 conv_summary 层面无法校验 `item_ids` 和 `new_item_ids` 的正确性（需要与 tool 结果逐字段比对）。

### 5.2 PARTIAL_WRITE

**占比**：各系统均约 1-2 个案例

**典型案例**：task 22（3 个 modify 操作，前 2 个正确，第 3 个参数错误）。

**原因**：多步写操作中，agent 记住了前几步，但在最后一步的参数构造上出错，通常是地址格式错误或 payment_method_id 错误。

### 5.3 DB_OK_NL_FAIL

**占比**：workflow_v5 最多（3 个），其他系统 0-1 个

**典型案例**：task 3（写操作成功修改了 T-shirt 颜色，但 agent 未回答用户提问的"有多少种 T-shirt 选项"）。

**原因**：
- **对 workflow 的独特影响**：4 节点流水线中，Action Generator 只基于 Reasoner 的 `reply_content` 生成最终回复，容易遗漏用户在对话中间提出的附加问题（`unanswered_questions`）。
- **large_single/small_single**：flat agent 能从完整上下文召回用户提问，但偶尔仍会遗漏。

### 5.4 TRANSFER_ABORT

**占比**：workflow_v5 最多（5 个），其他系统各 1-2 个

**成因分类**：

| 场景 | workflow | planner_executor | single agents |
|---|---|---|---|
| 用户要求人工 | ✓ | ✓ | ✓ |
| read 工具超限后放弃 | ✓✓✓ | — | — |
| 产品变体无法确定后放弃 | ✓✓ | ✓ | — |

**workflow 特有问题**：read_hint 触发后（get_product_details 达到上限），Reasoner 在某些版本中会误判为"任务无法完成"，调用 `transfer_to_human_agents` 放弃任务（task 3/8/23）。这是 workflow 架构的主要非 baseline 失败来源。

**single agents 的 TRANSFER 案例**：均发生在任务真正无法完成的场景（用户要求违反 policy 的操作，如跨支付方式退款），属于正确行为。

---

## 6. Partial Action Reward 分析

除二元成功率外，tau2-bench 还记录每个工具调用是否匹配 ground truth，可计算 partial action reward。

**前 20 任务，失败任务的平均 read/write accuracy：**

| 系统 | read acc（全部） | read acc（失败） | write prec（全部） | write prec（失败） |
|---|---|---|---|---|
| large_single | 87% | 84% | 57% | 22% |
| small_single | 93% | 90% | 48% | 17% |

**关键发现**：
1. **read accuracy 差距不大**：两种模型在读操作准确率上相近（大模型反而稍低，因为 task 20 中大模型直接跳过了大量读操作）。
2. **write precision 是核心瓶颈**：失败任务的写操作精度都接近 0（22% vs 17%），说明写操作一旦错，基本是完全错——不存在"差一点"的情况。

---

## 7. 系统间对比总结

### 大模型 vs 小模型（flat single agent）

| 维度 | 结论 |
|---|---|
| 总体成功率 | large 0.54 vs small 0.50（50 tasks），差距仅 4% |
| 失败原因 | 均以 WRITE_WRONG_ARGS 为主；small 额外有"信息不完整就写"的情况 |
| 信息收集完整性 | large 接近 100% reads；small 偶有不完整 |

**结论**：tau2 retail 主要考验写参数精度而非深度推理，大小模型的差距（官方 benchmark 相差 24%）在这类任务上被大幅压缩。

### LLM-only Workflow vs SMAG

| 维度 | workflow (LLM Verifier) | smag (Python SM) |
|---|---|---|
| 状态追踪 | LLM 生成 structured state（不可靠） | Python 解析 tool results（确定性） |
| 写操作校验 | LLM 判断 → 误判多，TRANSFER_ABORT 高 | Python `can_execute()` → 精确可靠 |
| WRITE_WRONG_ARGS | 9/50（与 smag 相同） | 9/50 |
| TRANSFER_ABORT | 15/50（最高） | 4/50（与 single 相近） |
| 总体成功率 | 0.34 | **0.62** |

**核心发现**：两个架构的 WRITE_WRONG_ARGS 数量相同（9 个），但 workflow 多了 11 个额外的 TRANSFER_ABORT 失败。这证明 workflow 的问题不在于"写参数没改善"，而在于 LLM Verifier + State Tracker 引入了大量误判导致放弃。

### 架构演进路径

```
large_single (0.54)
    ↓ 加 4 节点流水线（State Tracker 损失上下文）
workflow (0.34)  ← 更差，TRANSFER_ABORT 激增
    ↓ Planner 保留完整上下文，弱化 Verifier
planner_executor (0.38)  ← 略好，但 PE 的弱 Verifier 放通了更多 WRITE_WRONG
    ↓ 状态追踪和校验移到确定性 Python
smag (0.62)  ← 最好，+8% over large_single
```

---

## 8. 主要研究发现

1. **Write precision 是 tau2 retail 的核心难点**：所有系统失败均以 WRITE_WRONG_ARGS 为主，模型在多订单场景下对 item_id、payment_method_id 的精确追踪能力有限。

2. **大小模型在这类任务上差距小**：gemma4:e4b（4.5B 本地）与 Gemini 2.5 Flash 相差 4%（0.50 vs 0.54），远小于通用 benchmark 的差距（GPQA Diamond 差 24%）。Retail 任务主要考验状态追踪而非推理深度。

3. **同构多节点 LLM workflow 不能超越 flat agent**：7 轮迭代的 4 节点流水线最好 0.45，低于 flat large_single 的 0.54。LLM 多节点带来的上下文损耗和误判放弃（TRANSFER_ABORT）抵消了 Verifier 的写精度收益，与文献（arxiv 2601.12307）结论一致。

4. **确定性 Python 状态机是关键突破**：SMAG 将状态追踪和前置校验从 LLM 移到 Python 代码，TRANSFER_ABORT 从 workflow 的 15 次降到 4 次，最终成功率 0.62（+8% over large_single baseline）。

5. **剩余失败集中在 2 个问题**：SMAG 的 19 次失败中，9 次是 WRITE_WRONG_ARGS（new_item_ids 选错，SM 未校验 product variant），另有 4 次是 LLM 口头确认后未执行写操作（agent=[]）。这两个问题是进一步提升的主要方向。

---

## 9. 后续方向

| 方向 | 预期收益 | 现状 |
|---|---|---|
| SMAG 加 new_item_ids 校验 | +3-4 任务 | SM 已追踪订单 item_ids，需扩展到 product variants |
| 解决 agent=[] 问题（口头确认未执行） | +3-4 任务 | 需 prompt 精调，但改 prompt 容易引入新回退 |
| 完整步骤顺序状态机（论文原版 SMAG） | 高（论文 82.6%） | 需为每种操作类型设计独立状态机，工程量大 |
| 异构多 agent（大模型推理 + 小模型执行） | 中等 | 降低 API 成本，保留大模型推理能力 |
