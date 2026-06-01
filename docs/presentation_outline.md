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

> "So here's a question a lot of people are asking right now: if you have a complex task for an LLM, is it better to just use one model end-to-end, or split it into a pipeline — one node for planning, one for verification, one for execution?
>
> Multi-agent workflows are really popular right now. The intuition makes sense: break it down, specialize each part, and you should get better results overall.
>
> But does that actually work? Especially when the agent needs to make tool calls, track state across 15 turns, and get the exact right parameters for a write operation — does adding more LLM nodes help, or does it just create more ways to fail?
>
> That's what we set out to test."

**Script（中文）**：

> "现在很多人都在问一个问题：对于复杂任务，是用一个模型端到端跑，还是拆成流水线——一个节点规划、一个节点校验、一个节点执行，效果会更好？
>
> 多 agent workflow 现在很流行，直觉上也说得通：分工专业化，每个部分都更专注，整体应该更好。
>
> 但真的是这样吗？尤其是在 agent 需要跨十几轮对话追踪状态、精确构造写操作参数的场景下——多加 LLM 节点到底是帮了忙，还是带来了更多出错的地方？
>
> 这就是我们想搞清楚的问题。"

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

> "We used multi-turn customer service as our test setting — the agent has to handle things like exchanges and cancellations across a 15-turn conversation, calling the right tools in the right order.
>
> We actually started by building our own dataset. But we quickly ran into a problem: our instructions were ambiguous. A model could give a totally reasonable answer that just happened not to match our gold standard — and score zero. That makes the evaluation itself unreliable.
>
> So we switched to tau2-bench retail. All 50 tasks share the same policy document and the same database, so the ground truth is unambiguous — either the database changed correctly, or it didn't. We tested two models: Gemini 2.5 Flash via the API, and gemma4:e4b running locally."

**Script（中文）**：

> "我们用多轮客服作为测试场景——agent 需要在十几轮对话里处理换货、取消之类的操作，按正确顺序调用工具。
>
> 一开始我们自己构建了数据集。但很快发现一个问题：我们的 instruction 有歧义，模型给出了完全合理的答案，却因为和我们定的标准答案不一样得了零分。这让评测本身就不可靠了。
>
> 所以我们换成了 tau2-bench retail。所有 50 个任务共享同一份 policy 文档和同一个数据库，ground truth 没有歧义——数据库要么改对了，要么没有。我们测了两个模型：Gemini 2.5 Flash 走 API，gemma4:e4b 本地跑。"

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

> "So what's actually going wrong? Both models fail mainly on write precision — the agent gets all the right information, but then passes the wrong item ID, or mixes up the payment methods for two different orders. About 48% of all failures come down to this.
>
> We tried three approaches to fix it.
>
> First, a four-node workflow. We added a Verifier node, and it did help with payment precision on some tasks — but the State Tracker was compressing the full conversation into a JSON object, and losing context in the process. That created a new problem: the agent would get confused, give up, and call for a human transfer. The workflow ended up scoring worse than the baseline.
>
> Second, Planner-Executor. We gave the Planner the full conversation history, which fixed the context loss. But now the Verifier was weaker, and write errors went back up. Still didn't beat the baseline.
>
> Third, SMAG. The key insight here: state tracking isn't a reasoning problem — it's a lookup. So instead of asking an LLM to figure out which item belongs to which order, we just write Python code to do it. A state machine parses every tool result and tracks the exact items, orders, and payment methods. Before any write operation, Python checks the preconditions directly. The LLM only handles the parts that actually need language understanding."

**Script（中文）**：

> "那到底哪里出了问题？两个模型失败的主要原因都是写操作参数精度——信息读对了，但传错了 item ID，或者把两个订单的支付方式搞混了。大概 48% 的失败都是这个原因。
>
> 我们试了三种方向来解决这个问题。
>
> 第一个是四节点流水线。加了 Verifier 节点确实在部分任务上改善了支付方式的匹配——但 State Tracker 把完整对话压缩成 JSON 的时候，丢失了很多关键信息。结果引入了新问题：agent 反复卡住，最后放弃转人工。分数比 baseline 还低。
>
> 第二个是 Planner-Executor。Planner 保留完整对话历史，上下文损耗的问题修了——但 Verifier 变弱了，写操作错误又上来了。还是没超过 baseline。
>
> 第三个是 SMAG。核心思路是：状态追踪根本不是推理问题，是查表问题。所以我们不用 LLM 来判断哪个 item 属于哪个订单，直接写 Python 代码做这件事。状态机解析每条工具返回，精确追踪 item、订单、支付方式。每次写操作前 Python 直接检查前置条件。LLM 只负责真正需要语义理解的部分。"

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

> "Looking at the numbers — the flat large-model baseline is 54%. Workflow drops to 34%, which is actually worse. Planner-Executor gets to 38%. And SMAG with Gemini hits 62%.
>
> But the most interesting result is the small model. gemma4:e4b running locally on SMAG gets 58% — that's higher than the flat large model at 54%. A 4.5-billion-parameter local model, beating a large cloud model, just by changing the architecture.
>
> And if you look at the error table, you can see why the workflows struggled — they didn't actually fix the errors, they just traded one type of failure for another. SMAG is the only one that brought down all error categories at the same time."

**Script（中文）**：

> "看数字——大模型 flat agent baseline 是 54%。Workflow 降到 34%，比 baseline 还低。Planner-Executor 到 38%。SMAG 用大模型跑到 62%。
>
> 但最有意思的结果是小模型。gemma4:e4b 本地跑 SMAG 拿到 58%——比大模型 flat agent 的 54% 还高。一个 45 亿参数的本地模型，只靠换架构，就超过了大的云端模型。
>
> 看错误分布的话，可以看到为什么 workflow 没能提升——它们并没有真正减少错误，只是把错误从一类移到了另一类。SMAG 是唯一一个把所有错误类型都降下来的架构。"

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

> "So three things we took away from this.
>
> First, more LLM nodes doesn't mean better. Every node adds its own error rate, and those stack. When the State Tracker gets something wrong, every node after it is working with bad information.
>
> Second, in agentic tasks, the right architecture matters more than model size. gemma4:e4b on SMAG hits 0.58 — beating Gemini 2.5 Flash as a flat agent at 0.54. Same task, smaller model, better architecture, better result.
>
> Third, for tasks with predictable, repetitive structure, deterministic code just works better than LLM pipelines. Checking whether an item ID is actually in an order is a lookup — not a reasoning problem. Encode that in Python, and you eliminate a whole class of errors. Thank you."

**Script（中文）**：

> "所以我们有三个主要的收获。
>
> 第一，LLM 节点多不等于效果好。每个节点都有自己的错误率，这些错误会叠加。State Tracker 漏掉一个字段，后面所有节点都在基于错误信息做决策。
>
> 第二，在 agentic 任务里，架构比模型大小更重要。gemma4:e4b 跑 SMAG 拿到 0.58，打赢了 Gemini 2.5 Flash 的 flat agent 0.54。同样的任务，更小的模型，更好的架构，更好的结果。
>
> 第三，对于结构可预测、重复性高的任务，确定性代码比 LLM 流水线更可靠。判断一个 item ID 是不是在订单里，这是查表，不是推理。用 Python 写死这个逻辑，直接消灭了一整类错误。谢谢。"

---

## 备注

- **Slide 3 是全场核心** — 1.5 min，先讲 baseline 失败原因，再讲三个方向，SMAG 是核心
- **时间不够时**：Key Findings 第三条可以简化成一句，省出 10s
- **Slide 2 右侧 Example Task** 可以在讲 tau2-bench 时手势指向，不需要逐字朗读
