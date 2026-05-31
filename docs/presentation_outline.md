# 5-Min Presentation Outline
## Evaluating LLM Limitations in Multi-Turn Agentic Applications

---

## 总体节奏

| Slide | 主题 | 时间 |
|---|---|---|
| 1 | Motivation | 1 min |
| 2 | Application & Dataset | 50s |
| 3 | Evaluation Metrics | 40s |
| 4 | Approaches（核心） | 1.5 min |
| 5 | Results | 40s |
| 6 | Key Findings | 30s |

> **说明**：每个 slide 附英文 + 中文两版 script，约 750 词 / 5 分钟正常语速。斜体是过渡句，**加粗**是需要配合 slide 强调的词。

---

## Slide 1 — Motivation（1 min）

**Slide 内容**：
- 对比图：Single Agent（简单，一个 LLM box）vs Agentic Workflow（多节点，State Tracker → Reasoner → ...）
- 核心问题：Does adding more LLM nodes actually help?

**Script（英文）**：

> "As LLMs become more capable, a natural question arises: should we use a single model end-to-end, or break the task into a pipeline of specialized agents, each handling a different subtask?
>
> Multi-agent and workflow-based architectures have become popular — the idea being that decomposing complex tasks into smaller steps, with dedicated nodes for planning, verification, and execution, should outperform a single flat agent.
>
> But does it actually? **When does adding more LLM nodes help, and when does it hurt?** These questions are underexplored, especially in long-horizon, tool-use settings where agents must maintain state and execute precise operations across many steps.
>
> In this project, we systematically evaluate the limitations of both single agents and agentic workflows in a complex multi-turn tool-use benchmark — and investigate what actually drives the performance gap."

**Script（中文）**：

> "随着 LLM 能力不断增强，一个自然的问题出现了：应该用单个模型端到端处理任务，还是把任务拆成多个专门的 agent 组成的流水线——每个节点负责规划、验证或执行不同的子任务？
>
> 多 agent 和 workflow 架构越来越流行，核心假设是：把复杂任务分解成更小的步骤，让专门的节点各司其职，应该比单个 flat agent 表现更好。
>
> 但事实真的如此吗？**增加 LLM 节点什么时候有帮助，什么时候反而有害？** 这些问题在需要跨多个步骤维护状态、执行精确操作的长链工具调用场景中，还缺乏系统研究。
>
> 在这个项目里，我们在一个复杂的多轮工具调用 benchmark 上，系统评测了单 agent 和 agentic workflow 各自的局限性——并探究是什么真正决定了性能差距。"

---

## Slide 2 — Application & Dataset（50s）

**Slide 内容**：
- tau2-bench retail task example（对话截图）
- 两个模型：Gemini 2.5 Flash vs gemma4:e4b
- 一行说明自己构建数据集的经历

**Script（英文）**：

> "To ground this study in a concrete setting, we use **multi-turn customer service** as our application — a domain where agents must handle exchanges, returns, and cancellations across a long conversation while calling tools in the right order.
>
> We first tried to **build our own evaluation dataset**, but quickly ran into a fundamental problem: **ambiguity**. Instructions had edge cases supporting multiple valid interpretations, so a model could produce a perfectly reasonable answer and still score zero. This 'spurious negatives' problem undermines evaluation validity.
>
> *This led us to identify an existing benchmark instead.* We used **tau2-bench retail** — ground truth is determined programmatically by database state, so there's no ambiguity: either the database changed correctly or it didn't. 50 tasks, 16 tools, two models: **Gemini 2.5 Flash** and **gemma4:e4b** running locally."

**Script（中文）**：

> "为了在具体场景下研究这个问题，我们选择了**多轮客服**作为应用场景——agent 需要在长对话中处理换货、退货、取消等操作，按正确顺序调用工具。
>
> 我们首先尝试**自己构建评测数据集**，但很快遇到了一个根本性问题：**歧义**。instruction 存在边界情况，支持多种合理解读，模型给出完全合理的答案却得零分——这就是"伪负样本"问题，会直接破坏评测有效性。
>
> *这让我们转而选用已有 benchmark。* 我们使用 **tau2-bench retail**——ground truth 由数据库状态程序化判断，没有歧义：数据库要么改对了，要么没有。50 个任务，16 个工具，两个模型：**Gemini 2.5 Flash** 和本地运行的 **gemma4:e4b**。"

---

## Slide 3 — Evaluation Metrics（40s）

**Slide 内容**：
- 三个指标 + 5 类错误类型表格

**Script（英文）**：

> "For evaluation, we use three layers of metrics.
>
> **DB Check** — did the database actually change correctly? Saying 'I've processed your return' without updating the order state is a complete failure.
>
> **NL Assertion** — did the agent communicate the result clearly? A task where the execution is correct but the agent fails to answer a follow-up question still scores zero.
>
> Third, we designed a **five-type error taxonomy** to understand *why* agents fail: wrong write arguments, partial writes, DB-correct-but-NL-fail, transfer-abort where the agent gives up mid-conversation, and no write attempted. This turns a single success rate into a diagnostic breakdown."

**Script（中文）**：

> "评测上我们用了三层指标。
>
> **DB Check**——数据库状态是否真的改对了？说"已为您办理退货"但订单状态没变，就是完全失败。
>
> **NL Assertion**——agent 是否清晰地沟通了结果？执行对了但没回答用户追问的问题，仍然得零分。
>
> 第三，我们设计了**五类错误分类**来理解 agent *为什么*失败：写操作参数错误、部分写成功、DB 对但 NL 失败、agent 放弃并转人工、以及从未尝试写操作。这把一个成功率数字变成了可诊断的分布。"

---

## Slide 4 — Approaches（1.5 min） ← 重点

**Slide 内容**：
- 四个系统的架构图（Baseline / Workflow / Planner-Executor / SMAG），每个配一行 pros/cons

**Script（英文）**：

> "We found that both models fail mainly on **write operation precision** — the agent reads the right information but then passes wrong item IDs or swaps the payment methods between two orders. This accounts for roughly 48% of all failures.
>
> So we tried three architectural approaches.
>
> **First, a four-node linear workflow**: State Tracker, Reasoner, Verifier, Action Generator. The Verifier does improve payment-method precision on some tasks — but the State Tracker compresses the conversation into a structured JSON, losing critical product variant information along the way. This creates a new failure mode: the agent gets stuck, gives up, and transfers to a human. Workflow ends up *worse* than baseline.
>
> **Second, Planner-Executor**: the Planner sees the full conversation history — fixing the context loss — while a deterministic Executor handles tool calls. Variant selection improves, but write validation weakens. Neither approach clearly beats the flat agent. This is consistent with recent work showing that homogeneous multi-agent pipelines — same model, different prompts — don't outperform a flat agent.
>
> **Third, our SMAG-inspired approach**: the key insight is to move state tracking and precondition checking *out of the LLM entirely* and into deterministic Python code. A Python state machine parses every tool result and tracks exactly which items belong to which order and what the payment methods are. Before any write operation, Python checks: authenticated? correct order status? item IDs valid?
>
> The LLM keeps doing what it's good at — understanding user intent and selecting product variants — while Python enforces the parts that need precision. This is the design principle: **use rule-based code for anything that's structurally deterministic; only use LLM where semantic understanding is truly required.**"

**Script（中文）**：

> "我们发现两个模型失败的主要原因都是**写操作参数精度**——agent 读对了信息，却传错了 item ID，或者把两个订单的支付方式搞混了。这占所有失败的约 48%。
>
> 于是我们尝试了三种架构方向。
>
> **第一，四节点线性流水线**：State Tracker、Reasoner、Verifier、Action Generator。Verifier 确实在部分任务上改善了支付方式匹配——但 State Tracker 把对话压缩成结构化 JSON 时，丢失了关键的产品变体信息。这引入了新的失败模式：agent 反复卡住，最终放弃并转人工。workflow 的表现反而*比 baseline 更差*。
>
> **第二，Planner-Executor**：Planner 保留完整对话历史，修复了上下文损耗；Executor 纯确定性处理工具调用。变体选择改善了，但写操作校验弱化了。两个方案都没能明显超越 flat agent，这与文献中"同构多 agent 流水线不优于单 agent"的结论一致。
>
> **第三，我们的 SMAG 方案**：核心思路是把状态追踪和前置校验*完全从 LLM 里拿出来*，交给确定性 Python 代码。Python 状态机解析每一条工具返回结果，精确追踪哪个 item 属于哪个订单、支付方式是什么。每次写操作前，Python 检查：已认证？订单状态正确？item ID 合法？
>
> LLM 只负责它擅长的——理解用户意图和选择产品变体——Python 负责需要精确度的部分。这就是设计原则：**结构确定的环节用 rule-based 代码；只有真正需要语义理解的地方才用 LLM。**"

---

## Slide 5 — Results（40s）

**Slide 内容**：
- 成功率表 + 错误分布条形图

**Script（英文）**：

> "The results show a clear progression. The flat large-model baseline achieves 54% on 50 tasks. Our workflow drops to 34% — worse than baseline. Planner-Executor recovers to 38%. And SMAG with the large model reaches **62% — an 8-point improvement**.
>
> But the most striking result is this: we also ran SMAG with the **small local model**, gemma4:e4b. It achieves **exactly the same score — 65% on the first 20 tasks**. The small model under SMAG completely matches the large model under SMAG, while the flat small agent was 15 points behind.
>
> Looking at error types, both SMAG variants nearly eliminated the transfer-abort problem that plagued the workflow — down from 15 failures to 0 or 2 — while keeping write-argument errors low."

**Script（中文）**：

> "结果呈现出清晰的趋势。大模型 flat agent baseline 在 50 个任务上达到 54%。我们的 workflow 降到 34%——比 baseline 更差。Planner-Executor 恢复到 38%。大模型 SMAG 达到 **62%——提升了 8 个百分点**。
>
> 但最引人注目的结果是：我们也用**小模型 gemma4:e4b** 跑了 SMAG。它的成绩是**完全一样的——前 20 个任务 65%**。小模型在 SMAG 架构下完全追上了大模型，而在 flat agent 下两者相差 15 个百分点。
>
> 从错误类型来看，两个 SMAG 版本几乎都消除了困扰 workflow 的 transfer-abort 问题——从 15 次降到 0 或 2 次——同时把写参数错误控制在较低水平。"

---

## Slide 6 — Key Findings（30s）

**Slide 内容**：
- 两条 takeaways + 一行 future work

**Script（英文）**：

> "Two takeaways.
>
> First: **multi-node LLM pipelines amplify errors**. Each node introduces some error ε, and four nodes in series give roughly 1−(1−ε)⁴. When the State Tracker misses one field, the Reasoner, Verifier, and Action Generator all build on that same mistake — which is why our workflow performed worse than the single-agent baseline.
>
> Second: **deterministic code beats LLM for structured tasks** — and architecture matters more than model size. The small model under SMAG matches the large model under SMAG exactly. Moving state extraction to Python removed the bottleneck that previously separated them. Better models will shrink the remaining gap, but deterministic code is always 100% accurate — that advantage doesn't disappear.
>
> The gap between our 62% and the paper's 82% is mainly about validating replacement variants — the clearest direction for future work. Thank you."

**Script（中文）**：

> "两条 takeaway。
>
> 第一：**多节点 LLM 流水线会放大误差**。每个节点都有一定的错误率 ε，四个节点串联后误差大约是 1−(1−ε)⁴。State Tracker 漏掉一个字段，Reasoner、Verifier、Action Generator 就都在同一个错误的基础上继续做决策——这就是为什么我们的 workflow 反而比单 agent baseline 更差。
>
> 第二：**确定性代码在结构化任务上优于 LLM——架构比模型大小更重要**。小模型在 SMAG 下与大模型成绩完全相同，把状态提取交给 Python 之后，之前拉开两者差距的瓶颈就消失了。更好的模型会缩小剩余差距，但确定性代码始终是 100% 精确——这个优势在原则上不会消失。
>
> 我们的 62% 和论文的 82% 之间的差距，主要在于换货时的替代变体校验，这是最明确的后续方向。谢谢。"

---

## 备注

- **Dataset slide 加了自建数据集的经历** → 说明为什么选择 identify 而不是 design，对应 Idea 1 的要求
- **Slide 4 是全场核心** → 1.5 min，三个 approach 各一段，先说问题再说设计再说局限
- **时间不够时**：Slide 6 可以合并进 Slide 5 最后一句，省下 20s
