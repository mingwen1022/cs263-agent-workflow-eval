# Presentation Outline
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

> Script 约 750 词，5 分钟正常语速。

---

## Slide 1 — Motivation（1 min）

### Slide 上展示的内容

**标题**：When Does Adding LLM Nodes Help?

**左侧图（Single Agent）**：
```
User Message
     ↓
 [  LLM  ]
     ↓
Tool Call / Reply
```
标注：1 LLM call per turn

**右侧图（Agentic Workflow）**：
```
User / Tool Result
        ↓
[State Tracker LLM]
        ↓
  [Reasoner LLM]
        ↓
  [Verifier LLM]
        ↓
[Action Generator LLM]
        ↓
  Tool Call / Reply
```
标注：3–4 LLM calls per turn

**底部大字问题**：
> Does decomposing tasks into more LLM nodes actually improve performance?

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

> "随着 LLM 能力不断增强，一个自然的问题出现了：应该用单个模型端到端处理任务，还是把任务拆成多个专门的 agent 组成的流水线——每个节点负责规划、验证或执行不同的子任务？
>
> 多 agent 和 workflow 架构越来越流行，核心假设是：把复杂任务分解成更小的步骤，让专门的节点各司其职，应该比单个 flat agent 表现更好。
>
> 但事实真的如此吗？**增加 LLM 节点什么时候有帮助，什么时候反而有害？** 这些问题在需要跨多个步骤维护状态、执行精确操作的长链工具调用场景中，还缺乏系统研究。
>
> 在这个项目里，我们系统评测了单 agent 和 agentic workflow 各自的局限性——并探究是什么真正决定了性能差距。"

---

## Slide 2 — Application & Dataset（50s）

### Slide 上展示的内容

**标题**：Setting & Dataset

**左上：Scenario（一个简化对话框）**
```
User:   I want to exchange my keyboard in order #W2378156.
Agent:  Could you verify your identity?
User:   Yusuf Rossi, zip 19122.
Agent:  [calls find_user_id → get_order_details → exchange_item]
Agent:  Done! Your keyboard has been exchanged.
```
小字注释：16 tools available, 10–20 turns per task

**右上：两个模型对比**
```
Gemini 2.5 Flash          gemma4:e4b
(large cloud model)    (local, 4.5B params)
```

**左下：Dataset 选择**
| | Self-built (attempted) | tau2-bench retail (used) |
|---|---|---|
| Ground truth | Handcrafted — ambiguous | DB state — programmatic |
| Problem | Spurious negatives | No ambiguity |

**右下：tau2-bench 数字**
- **50 tasks**, 1 trial each
- Pass criteria: DB state ✓ AND NL response ✓

---

**Script（英文）**：

> "To ground this study in a concrete setting, we use **multi-turn customer service** as our application — a domain where agents must handle exchanges, returns, and cancellations across a long conversation while calling tools in the right order.
>
> We first tried to **build our own evaluation dataset**, but quickly ran into a fundamental problem: **ambiguity**. Instructions had edge cases supporting multiple valid interpretations, so a model could produce a perfectly reasonable answer and still score zero. This 'spurious negatives' problem undermines evaluation validity.
>
> This led us to identify an existing benchmark instead. We used **tau2-bench retail** — ground truth is determined programmatically by database state, so there's no ambiguity: either the database changed correctly or it didn't. 50 tasks, 16 tools, two models: **Gemini 2.5 Flash** and **gemma4:e4b** running locally."

**Script（中文）**：

> "我们选择了**多轮客服**作为应用场景——agent 需要在长对话中处理换货、退货、取消等操作，按正确顺序调用工具。
>
> 我们首先尝试**自己构建评测数据集**，但很快遇到一个根本性问题：**歧义**。instruction 存在边界情况，支持多种合理解读，模型给出完全合理的答案却得零分——这就是"伪负样本"问题，会直接破坏评测有效性。
>
> 于是我们转而选用已有 benchmark：**tau2-bench retail**——ground truth 由数据库状态程序化判断，没有歧义：数据库要么改对了，要么没有。50 个任务，16 个工具，两个模型：**Gemini 2.5 Flash** 和本地运行的 **gemma4:e4b**。"

---

## Slide 3 — Evaluation Metrics（40s）

### Slide 上展示的内容

**标题**：Evaluation Design

**左侧：三层指标（图标 + 说明）**

| Metric | What it checks | Why it matters |
|---|---|---|
| ✅ DB Check | Final database state matches ground truth | "Saying" ≠ "Doing" |
| 💬 NL Assertion | Agent's response satisfies semantic requirements | Execution + communication both required |
| 🔍 Error Taxonomy | Why did the agent fail? | Turns a number into a diagnosis |

**右侧：5 类错误（色块标签）**

```
■ WRITE_WRONG_ARGS    wrong item IDs or payment method
■ PARTIAL_WRITE       some writes correct, some not
■ DB_OK_NL_FAIL       executed correctly, said it wrong
■ TRANSFER_ABORT      agent gave up, called human
■ NO_WRITE            never attempted the write
```

---

**Script（英文）**：

> "For evaluation, we use three layers of metrics.
>
> **DB Check** — did the database actually change correctly? Saying 'I've processed your return' without updating the order state is a complete failure.
>
> **NL Assertion** — did the agent communicate the result clearly? A task where the execution is correct but the agent fails to answer a follow-up question still scores zero.
>
> Third, we designed a **five-type error taxonomy** to understand why agents fail: wrong write arguments, partial writes, DB-correct-but-NL-fail, transfer-abort where the agent gives up, and no write attempted. This turns a single success rate into a diagnostic breakdown."

**Script（中文）**：

> "评测上我们用了三层指标。
>
> **DB Check**——数据库状态是否真的改对了？说"已为您办理退货"但订单状态没变，就是完全失败。
>
> **NL Assertion**——agent 是否清晰地沟通了结果？执行对了但没回答用户追问的问题，仍然得零分。
>
> 第三，我们设计了**五类错误分类**来理解 agent 为什么失败：写操作参数错误、部分写成功、DB 对但 NL 失败、agent 放弃并转人工、以及从未尝试写操作。这把一个成功率数字变成了可诊断的分布。"

---

## Slide 4 — Approaches（1.5 min） ← 重点

### Slide 上展示的内容

**标题**：What We Tried — and Why

**四个系统横向排列，每个一列：**

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Flat Single    │  │    Workflow     │  │Planner-Executor │  │      SMAG       │
│     Agent       │  │  (4-node LLM)  │  │                 │  │  (Python SM)    │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│                 │  │  State Tracker  │  │   Planner LLM   │  │  Python SM      │
│    [  LLM  ]    │  │  Reasoner LLM  │  │  (full context) │  │  update()       │
│  bind_tools()   │  │  Verifier LLM  │  │       ↓         │  │  can_execute()  │
│                 │  │  Action Gen.   │  │  Executor (det.) │  │       ↓         │
│                 │  │                 │  │                 │  │   [  LLM  ]     │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│ ✓ Full context  │  │ ✓ Verifier helps│  │ ✓ Full context  │  │ ✓ Full context  │
│ ✗ Write errors  │  │ ✗ Context lost  │  │ ✗ Weak verifier │  │ ✓ Deterministic │
│                 │  │ ✗ TRANSFER↑↑   │  │                 │  │   validation    │
└─────────────────┘  └─────────────────┘  └─────────────────┘  └─────────────────┘
```

**底部：Design Principle**
> Use **rule-based code** for structurally deterministic tasks.
> Reserve **LLM** for semantic understanding only.

---

**Script（英文）**：

> "We found that both models fail mainly on **write operation precision** — the agent reads the right information but then passes wrong item IDs or swaps the payment methods between two orders. This accounts for roughly 48% of all failures.
>
> So we tried three architectural approaches.
>
> **First, a four-node linear workflow**: State Tracker, Reasoner, Verifier, Action Generator. The Verifier does improve payment-method precision on some tasks — but the State Tracker compresses the conversation into a structured JSON, losing critical product variant information. This creates a new failure mode: the agent gets stuck, gives up, and transfers to a human. Workflow ends up *worse* than baseline.
>
> **Second, Planner-Executor**: the Planner sees the full conversation history — fixing the context loss — while a deterministic Executor handles tool calls. Variant selection improves, but write validation weakens. Neither approach clearly beats the flat agent — consistent with work showing homogeneous multi-agent pipelines don't outperform a flat agent.
>
> **Third, SMAG**: move state tracking and precondition checking *out of the LLM* and into deterministic Python. A state machine parses every tool result and tracks items, orders, and payment methods. Before any write, Python checks: authenticated? correct order status? item IDs valid? The LLM keeps doing what it's good at — intent and variant selection. Python enforces what needs precision."

**Script（中文）**：

> "我们发现两个模型失败的主要原因都是**写操作参数精度**——读对了信息，却传错了 item ID，或者把两个订单的支付方式搞混了。约占所有失败的 48%。
>
> 于是我们尝试了三种架构方向。
>
> **第一，四节点线性流水线**：State Tracker、Reasoner、Verifier、Action Generator。Verifier 在部分任务上改善了支付方式匹配——但 State Tracker 把对话压缩成 JSON 时丢失了关键信息，引入新的失败模式：agent 反复卡住，最终放弃转人工。workflow 反而*比 baseline 更差*。
>
> **第二，Planner-Executor**：Planner 保留完整上下文，修复了上下文损耗，Executor 纯确定性处理工具调用。变体选择改善，但写操作校验弱化，两个方案都没超越 flat agent。
>
> **第三，SMAG**：把状态追踪和前置校验*完全从 LLM 里拿出来*，交给确定性 Python。状态机解析每条工具返回，追踪 item、订单、支付方式。每次写操作前 Python 检查：已认证？订单状态正确？item ID 合法？LLM 只负责意图理解和变体选择，Python 负责需要精确度的部分。"

---

## Slide 5 — Results（40s）

### Slide 上展示的内容

**标题**：Results

**左：成功率表（50 tasks）**

| System | Model | avg reward |
|---|---|---|
| **SMAG** | Gemini 2.5 Flash | **0.62** ↑ |
| large_single | Gemini 2.5 Flash | 0.54 |
| small_single | gemma4:e4b | 0.50 |
| planner_executor | Gemini 2.5 Flash | 0.38 |
| workflow | Gemini 2.5 Flash | 0.34 |

**中：突出显示的惊喜结果**

```
┌──────────────────────────────────────┐
│  SMAG + small model (gemma4:e4b)     │
│  = 0.65   same as SMAG + large model │
│                                      │
│  flat small: 0.50  →  SMAG: 0.65    │
│              +15% with same model    │
└──────────────────────────────────────┘
```

**右：错误分布条形图（前20任务，按系统）**

```
large_single  ■■■■■■■■ WRITE_WRONG  ■■■■ PARTIAL  ■■ OTHER
workflow      ■■■■ WRITE  ■■■■■■■■■■■■■■■■■ TRANSFER_ABORT
smag_large    ■■■■ WRITE  ■■ DB_NL  ■ PARTIAL
smag_small    ■■■ WRITE   ■■ DB_NL  ■■ TRANSFER
```

---

**Script（英文）**：

> "The results show a clear progression. The flat large-model baseline achieves 54% on 50 tasks. Workflow drops to 34% — worse than baseline. Planner-Executor recovers to 38%. SMAG with the large model reaches **62% — an 8-point improvement**.
>
> But the most striking result: we ran SMAG with the **small local model**, gemma4:e4b. It achieves **exactly the same score**. The small model under SMAG completely matches the large model, while the flat small agent was 15 points behind.
>
> Looking at errors, both SMAG variants nearly eliminated transfer-abort — down from 15 to 0–2 — while keeping write-argument errors low."

**Script（中文）**：

> "结果呈现清晰趋势。大模型 flat agent 在 50 个任务上达到 54%。Workflow 降到 34%——比 baseline 更差。Planner-Executor 恢复到 38%。大模型 SMAG 达到 **62%——提升 8 个百分点**。
>
> 但最引人注目的结果是：我们用**小模型 gemma4:e4b** 跑了 SMAG，成绩**完全一样**。小模型在 SMAG 下完全追上了大模型，而 flat agent 下两者相差 15 个百分点。
>
> 从错误类型看，两个 SMAG 版本几乎消除了 transfer-abort 问题——从 15 次降到 0–2 次。"

---

## Slide 6 — Key Findings（30s）

### Slide 上展示的内容

**标题**：Takeaways

**两条大字 takeaway（各占一行，加粗）**：

**① Multi-node LLM pipelines amplify errors**

```
1 node:    error rate ε
4 nodes:   1 − (1 − ε)⁴   >> ε

State Tracker misses field
    → Reasoner wrong decision
         → Verifier wrong check
              → Action Generator wrong output
```

**② Architecture > Model Size**

```
flat small (gemma4:e4b)    0.50
flat large (Gemini Flash)  0.54   +4%

SMAG small (gemma4:e4b)    0.65
SMAG large (Gemini Flash)  0.62   tied

→ Rule-based state tracking removes the bottleneck
```

**底部小字（future work）**：
> Gap to paper's 82%: replacement variant validation — clearest next step

---

**Script（英文）**：

> "Two takeaways.
>
> First: **multi-node LLM pipelines amplify errors**. Each node introduces some error ε, and four nodes in series give roughly 1−(1−ε)⁴. When the State Tracker misses one field, the Reasoner, Verifier, and Action Generator all build on that same mistake — which is why our workflow performed worse than baseline.
>
> Second: **architecture matters more than model size**. The small model under SMAG matches the large model exactly. Moving state extraction to Python removed the bottleneck that previously separated them. Deterministic code is always 100% accurate — that advantage doesn't disappear with better models.
>
> The gap to the paper's 82% is mainly about validating replacement variants — the clearest direction for future work. Thank you."

**Script（中文）**：

> "两条 takeaway。
>
> 第一：**多节点 LLM 流水线放大误差**。每个节点有错误率 ε，四个节点串联误差约为 1−(1−ε)⁴。State Tracker 漏掉一个字段，后面三个节点全在同一个错误上继续做决策——这就是 workflow 反而比 baseline 更差的原因。
>
> 第二：**架构比模型大小更重要**。小模型在 SMAG 下与大模型成绩完全相同，把状态提取交给 Python 之后，之前拉开两者差距的瓶颈消失了。确定性代码始终是 100% 精确，这个优势不会因为模型更好而消失。
>
> 我们的 62% 和论文 82% 的差距主要在替代变体校验，这是最明确的后续方向。谢谢。"

---

## 备注

- **Slide 4 是全场核心** → 1.5 min，四列架构图一目了然，口头补充每个的优缺点
- **Slide 5 的惊喜结果** → smag_small = smag_large 这个 box 要视觉上突出，是最有力的 finding
- **时间不够时**：Slide 6 底部 future work 一行可以省略不说
