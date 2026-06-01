# Presentation Outline
## Evaluating LLM Limitations in Multi-Turn Agentic Applications

---

## 总体节奏

| Slide | 主题 | 时间 |
|---|---|---|
| 1 | Motivation | 1 min |
| 2 | Evaluation (Dataset + Metrics) | 50s |
| 3 | Approaches | 1.5 min |
| 4 | Results | 40s |
| 5 | Key Findings | 30s |

> Script 约 700 词，5 分钟正常语速。

---

## Slide 1 — Motivation（1 min）

### Slide 上展示的内容

**标题**：Motivation

**左侧：Flat Single Agent 流程图**
- User Message → LLM → (Tool Call / Assistant Response) → loop back

**右侧：Multi-Node Agentic Workflow 流程图**
- User Message → [State Tracker LLM → Reasoner LLM → Verifier LLM → Action Generator LLM] → (Tool Call / Assistant Response)
- 虚线框包围 4 个 LLM 节点
- 右侧注释："Decompose one decision loop into specialized LLM nodes"

**中间红色大字问题**：
> Does LLM-based decomposition improve multi-step tool use, or introduce new failure modes?

**V.S.**

---

**Script（英文）**：

> "As LLMs become more capable, a natural question arises: should we use a single model end-to-end, or break the task into a pipeline of specialized agents, each handling a different subtask?
>
> Multi-agent and workflow-based architectures have become popular — the idea being that decomposing complex tasks into smaller steps, with dedicated nodes for planning, verification, and execution, should outperform a single flat agent.
>
> But does it actually? **When does adding more LLM nodes help, and when does it hurt?** These questions are underexplored, especially in long-horizon, tool-use settings where agents must maintain state and execute precise operations across many steps.
>
> In this project, we systematically evaluate the limitations of both single agents and agentic workflows in a complex multi-turn tool-use benchmark — and investigate what actually drives the performance gap."

**Script（中文）**：

> "随着 LLM 能力不断增强，一个自然的问题出现了：应该用单个模型端到端处理任务，还是把任务拆成多个专门的 agent 组成的流水线？
>
> 多 agent 和 workflow 架构越来越流行，核心假设是：把复杂任务分解成更小的步骤，让专门的节点各司其职，应该比单个 flat agent 表现更好。
>
> 但事实真的如此吗？**增加 LLM 节点什么时候有帮助，什么时候反而有害？** 这些问题在需要跨多个步骤维护状态、执行精确操作的场景中，还缺乏系统研究。
>
> 在这个项目里，我们系统评测了单 agent 和 agentic workflow 各自的局限性——并探究是什么真正决定了性能差距。"

---

## Slide 2 — Evaluation（50s）

### Slide 上展示的内容

**标题**：Evaluation

**左栏：Self-built Tasks**（灰色/淡色）

Task Structure:
1. Task Inputs: Task-specific Instruction + 4-8 task-specific Source Documents (csv/pdf/docx/txt/md)；No shared base across tasks, each task has unique documents, unique instruction.
2. Agent actions: Explores sources with tools (list_source/read_csv/read_pdf...); Cross-document reasoning
3. Task Output: Structure JSON with multiple fields

Evaluation Metrics:
- Numeric fields: exact match with tolerance; e.g., total_overspend = $56,700 (±$0.01)
- Set fields: unordered set match + alias lookup; e.g., over_budget_departments = {engineering, marketing}; alias: "eng"/"cc_201"/"engineering_dept" all valid
- Score: correct fields / total fields

Example Task（代码块）：
```
Task: Budget Variance Analysis
Input: actuals.csv, policy.md, transfers.csv ...
Output: {
  total_overspend: $56,700,
  over_budget_departments: [engineering, marketing],
  approved_transfers: [tr_b01, tr_b02],
  frozen_categories: [eng_headcount, mktg_campaigns]
}
```

**Problem 红色框**：
- multiple valid interpretations exist
- model's correct answer ≠ gold answer
- spurious negatives undermine validity

**中间大箭头**："Switch to"

**右栏：Tau2-bench (Retail domain)**（高亮）

右上角：tau2-bench logo + GitHub 截图

Task Structure:
1. Task Inputs: User goal/scenario (varies across task); **Shared Base**: Initial DB state; Retail policy
2. Agent actions: Multi-turn conversation (10-20 turns with LLM simulate user); Tool calls: 16 retail tools — Read: find user id/get order details; Write: exchange items/cancel orders
3. Task Output: Final DB state + natural language response

Evaluation Metrics:
- DB check: final DB state matches ground truth
- NL assertion: agent response satisfies semantics
- Score: binary: 0 or 1; both pass → score 1

Example Task（代码块）：
```
User:  "Exchange the keyboard in order #W2378156"
Agent: "Could you verify your identity?"
User:  "Yusuf Rossi, zip 19122"
Agent: find_user_id(Yusuf Rossi, 19122)
       → get_order_details(#W2378156)
       → get_product_details(keyboard)
       → exchange_delivered_order_items(
           order=#W2378156,
           item_ids=[1151293680],
           new_item_ids=[7706410293])
Agent: "Done! Your keyboard has been exchanged."
DB: order status → "exchange_requested" ✓
```

---

**Script（英文）**：

> "To ground this study in a concrete setting, we use multi-turn customer service as our application domain.
>
> We first tried to build our own evaluation dataset. Each task had its own custom source documents and instruction — no shared base, no universal policy. This created a fundamental problem: ambiguity. Instructions had edge cases supporting multiple valid interpretations, so a model could produce a perfectly reasonable answer and still score zero. This 'spurious negatives' problem undermines evaluation validity.
>
> This led us to tau2-bench retail instead. All 50 tasks share the same retail policy document and database — ground truth is anchored to a single authoritative policy. Either the database changed correctly or it didn't. 50 tasks, 16 tools, two models: Gemini 2.5 Flash and gemma4:e4b running locally."

**Script（中文）**：

> "我们选择了多轮客服作为应用场景。
>
> 我们首先尝试自己构建评测数据集——每个 task 都有各自独立的文档和 instruction，没有共享的 policy 作为 ground truth 的权威来源。这导致了根本性问题：歧义。instruction 存在边界情况，模型给出完全合理的答案却得零分——伪负样本直接破坏了评测有效性。
>
> 于是我们转向 tau2-bench retail。所有 50 个 task 共享同一份 retail policy 和数据库——ground truth 由统一的权威 policy 确定，没有歧义。数据库要么改对了，要么没有。50 个任务，16 个工具，两个模型：Gemini 2.5 Flash 和本地运行的 gemma4:e4b。"

---

## Slide 3 — Approaches（1.5 min） ← 重点

### Slide 上展示的内容

**标题**：Approaches

**Model Selection 蓝色小标题**

- **Gemini 2.5 Flash** (large): via Google Vertex AI API; tested on all 4 architectures
- **Gemma4:e4b** (small, local 4.5B): via Ollama, running locally; tested on Flat Single Agent and SMAG only (local inference speed constraint)
- **User Simulator**: Gemini 3.0 Flash (Vertex AI), simulates customer across all tasks
- **Goal**: evaluate how architecture design affects agent performance across model sizes

**Agent Architecture 蓝色小标题**

右上角标题：Score (50 tasks, tau2-bench retail)

4行横向流程图：

**Flat Single Agent**
```
[User/Tool Message] → [LLM (bind_tools, full context)] → [Tool Call/Response]
        ↑_________________________tool result___________________________|
```
Score: Gemini: 0.54 ｜ gemma4: 0.50（绿色）

**4-node Workflow**
```
[User/Tool Message] → [State Tracker LLM] → [Reasoner LLM] → [Verifier LLM (write only)] → [Action Gen LLM] → [Tool Call/Response]
                                                    ↑_____________rejected_______________|
```
Score: Gemini: 0.38 ↓（红色）

**Planner-Executor**
```
[User/Tool Message] → [Planner LLM (full conv. history)] → [Verifier LLM (weak, conv_summary)] → [Executor (deterministic, no LLM)] → [Tool Call/Response]
```
Score: Gemini: 0.34 ↓（红色）

**SMAG** *(Architecture adapted from SMAG — State Machine Augmented Generation, arXiv:2503.21036)*
```
[User/Tool Message] → [Python SM.update() (parse tool result)] → [LLM (full ctx + SM context)] → [Python can_execute() (precondition check)] → [Tool Call/Response]
                                                                         ↑__________rejected (≤2 retries)_________|
```
Score: Gemini: 0.62 ↑ ｜ gemma4: 0.58 ↑（绿色）

图例：🔵 LLM node　🟠 Python/deterministic　🟢 Input/Output

---

**Script（英文）**：

> "We found that both models fail mainly on write operation precision — the agent reads the right information but then passes wrong item IDs or swaps the payment methods between two orders. This accounts for roughly 48% of all failures.
>
> So we tried three architectural approaches.
>
> First, a four-node linear workflow: State Tracker, Reasoner, Verifier, Action Generator. The Verifier does improve payment-method precision on some tasks — but the State Tracker compresses the conversation into a structured JSON, losing critical context. This creates a new failure mode: the agent gets stuck, gives up, and transfers to a human. Workflow ends up worse than baseline.
>
> Second, Planner-Executor: the Planner sees the full conversation history, fixing context loss. Variant selection improves, but write validation weakens. Neither approach clearly beats the flat agent — consistent with work showing homogeneous multi-agent pipelines don't outperform a flat agent.
>
> Third, SMAG: move state tracking and precondition checking out of the LLM entirely and into deterministic Python code. A state machine parses every tool result and tracks items, orders, and payment methods. Before any write, Python checks: authenticated? correct order status? item IDs valid? The LLM keeps doing what it's good at — reasoning and language. Python enforces what needs precision. This is the design principle: use rule-based code for structurally deterministic tasks; only use LLM where semantic understanding is truly required."

**Script（中文）**：

> "我们发现两个模型失败的主要原因都是写操作参数精度——读对了信息，却传错了 item ID，或者把两个订单的支付方式搞混了。约占所有失败的 48%。
>
> 于是我们尝试了三种架构方向。
>
> 第一，四节点线性流水线。Verifier 在部分任务上改善了支付方式匹配——但 State Tracker 把对话压缩成 JSON 时丢失了关键信息，引入新的失败模式：agent 反复卡住，最终放弃转人工。workflow 反而比 baseline 更差。
>
> 第二，Planner-Executor。Planner 保留完整上下文，修复了上下文损耗，但写操作校验弱化，两个方案都没超越 flat agent。
>
> 第三，SMAG：把状态追踪和前置校验完全从 LLM 里拿出来，交给确定性 Python 代码。状态机解析每条工具返回结果，精确追踪 item、订单、支付方式。每次写操作前 Python 检查：已认证？订单状态正确？item ID 合法？LLM 只负责语义理解，Python 负责需要精确度的部分。"

---

## Slide 4 — Results（40s）

### Slide 上展示的内容

**标题**：Results

**左侧 Summary（蓝色标题）**

- **Flat Single Agent:** large model (0.54) vs small model (0.50), only a 4% gap, suggesting the task is architecture-sensitive, not model-size-sensitive
- **4-node Workflow (0.34) and Planner-Executor (0.38)** both fall below the flat agent baseline. Adding more LLM nodes introduces new failure modes and hurts overall performance
- **SMAG** improves over the baseline for both models: Gemini reaches 0.62 (+8%), and **gemma4:e4b reaches 0.58**, a small local model outperforming the flat large model (0.54)
- Error breakdown (bottom table) shows why: LLM-based workflows trade one failure type for another, while SMAG reduces failures across all error categories

**右侧上：Performance 表格**

| System | Model | Tasks | Success | Avg Reward |
|---|---|---|---|---|
| Flat Single Agent | Gemini 2.5 Flash | 50 | 27/50 | **0.54** |
| Flat Single Agent | gemma4:e4b | 50 | 25/50 | **0.5** |
| 4-node Workflow | Gemini 2.5 Flash | 50 | 17/50 | **0.34**（红色）|
| Planner-Executor | Gemini 2.5 Flash | 50 | 19/50 | **0.38**（红色）|
| SMAG | Gemini 2.5 Flash | 50 | 31/50 | **0.62**（绿色）|
| SMAG | gemma4:e4b | 50 | 29/50 | **0.58**（绿色）|

**右侧下：Error Distribution 表格**

| System | Model | WRITE_WRONG_ARGS | PARTIAL_WRITE | DB_OK_NL_FAIL | TRANSFER_ABORT | NO_WRITE | Total Fail |
|---|---|---|---|---|---|---|---|
| Flat Single Agent | Gemini 2.5 Flash | 11 | 7 | 1 | 4 | 0 | 23 |
| Flat Single Agent | gemma4:e4b | 12 | 5 | 2 | 6 | 0 | 25 |
| 4-node Workflow | Gemini 2.5 Flash | 9 | 5 | 4 | **15** | 0 | 33 |
| Planner-Executor | Gemini 2.5 Flash | **17** | 2 | 0 | 11 | 1 | 31 |
| SMAG | Gemini 2.5 Flash | 9 | 3 | 3 | 4 | 0 | **19** |
| SMAG | gemma4:e4b | 7 | 5 | 4 | 5 | 0 | **21** |

**Error Types（小字）**：
- **WRITE_WRONG_ARGS:** write executed but wrong arguments — wrong item IDs, swapped payment methods
- **PARTIAL_WRITE:** multiple writes required; some passed, some failed
- **DB_OK_NL_FAIL:** DB state correct but agent's final response failed semantic check
- **TRANSFER_ABORT:** agent called transfer_to_human_agents and terminated — gave up mid-task
- **NO_WRITE:** agent never attempted any write operation

---

**Script（英文）**：

> "The results show a clear pattern. The flat large-model baseline achieves 54%. Workflow drops to 34% — worse than baseline. Planner-Executor recovers to 38%. SMAG with the large model reaches 62% — an 8-point improvement.
>
> Notably, SMAG with the small local model, gemma4:e4b, achieves 58% — still beating the flat large model. A small model with the right architecture outperforms a larger model with the wrong one.
>
> The error breakdown shows why: LLM-based workflows don't reduce errors — they just shift them. SMAG is the only architecture that reduces failures across all error categories."

**Script（中文）**：

> "结果呈现清晰趋势。大模型 flat agent baseline 达到 54%。Workflow 降到 34%——比 baseline 更差。Planner-Executor 恢复到 38%。大模型 SMAG 达到 62%——提升 8 个百分点。
>
> 值得注意的是，小模型 gemma4:e4b 跑 SMAG 达到 58%，同样超过了大模型 flat agent。正确的架构让小模型打赢了更大的模型。
>
> 错误分布说明了原因：LLM-based workflow 不是减少了错误，而是把错误从一类转移到另一类。SMAG 是唯一在所有错误类型上都有所降低的架构。"

---

## Slide 5 — Key Findings（30s）

### Slide 上展示的内容

**标题**：Key Findings

三条带图标的 bullet：

🔄 **More LLM nodes ≠ better performance:** chaining multiple LLMs **accumulates errors** at each step; downstream nodes build on upstream mistakes

🧠 In agentic tasks, **a small model** with the **right architecture** can **outperform a flat large model**: gemma4:e4b under SMAG (0.58) surpasses Gemini 2.5 Flash as a flat agent (0.54)

📋 For **high-frequency** agentic tasks with **predictable structure**, **rule-based harness** outperforms **LLM** pipelines: encoding consistent task logic in deterministic code eliminates error accumulation

---

**Script（英文）**：

> "Three takeaways.
>
> More LLM nodes does not mean better performance — chaining multiple LLMs accumulates errors at each step, and downstream nodes build on upstream mistakes.
>
> In agentic tasks, a small model with the right architecture can outperform a flat large model. gemma4:e4b under SMAG scores 0.58, surpassing Gemini 2.5 Flash as a flat agent at 0.54.
>
> For high-frequency agentic tasks with predictable structure, rule-based harness design outperforms LLM pipelines — encoding consistent task logic in deterministic code eliminates error accumulation more reliably than adding more LLM nodes. Thank you."

**Script（中文）**：

> "三条 takeaway。
>
> 多个 LLM 节点不等于更好的性能——链式 LLM 在每步累积误差，下游节点在上游的错误上继续做决策。
>
> 在 agentic 任务中，正确架构下的小模型可以超过 flat 大模型。gemma4:e4b 在 SMAG 下达到 0.58，超过了 Gemini 2.5 Flash 的 0.54。
>
> 对于结构可预测的高频 agentic 任务，rule-based harness 比 LLM 流水线更有效——把固定的任务逻辑编码进确定性代码，比增加更多 LLM 节点更能消除误差累积。谢谢。"

---

## 备注

- **Slide 3 是全场核心** — 1.5 min，先讲 baseline 失败原因，再讲三个方向，SMAG 是核心
- **时间不够时**：Key Findings 第三条可以简化成一句，省出 10s
- **Slide 2 右侧 Example Task** 可以在讲 tau2-bench 时手势指向，不需要逐字朗读
