# Presentation Reference：实验与逻辑架构说明

这份文档是给 presenter 自己看的 reference，不是逐字讲稿。范围只覆盖 slide 中出现的内容：motivation、evaluation、approaches、results、key findings。更细的未来优化和没有出现在 slide 里的实验细节不展开。

---

## 1. 核心问题

本项目要回答的问题是：

> 在多轮、需要工具调用的 agentic task 里，把一个 flat single agent 拆成多节点 workflow，是否真的能提升表现，还是会引入新的失败模式？

这里的重点不是单纯比较模型大小，而是比较 **architecture design**：

- 单个 LLM 端到端决策：上下文完整，但所有状态追踪和写参数构造都靠模型自己记。
- 多节点 LLM workflow：把状态追踪、推理、验证、执行拆开，直觉上更模块化，但节点之间会传递中间状态，可能造成信息损失。
- SMAG：把可确定性处理的状态追踪和前置校验移到 Python，让 LLM 只处理语言理解和下一步选择。

Slide 1 的核心 takeaway 是：**decomposition 本身不是免费收益**。在 agentic task 里，每个 LLM 节点都有错误率，节点越多，错误可能越容易累积。

---

## 2. Evaluation：为什么从自建任务切到 tau2-bench

### 2.1 自建任务的结构

最早的任务是企业文档型 hard task：

- 每个任务有独立 instruction。
- 每个任务有 4-8 个 source documents，例如 csv、pdf、docx、txt、md。
- agent 需要调用本地 read tools 读取 source。
- 最终输出结构化 JSON。
- 评分按字段算：numeric fields 精确匹配，set fields 做无序集合匹配和 alias 匹配。

这种任务能测 cross-document reasoning，但核心问题是 **gold answer 容易有歧义**。

例子：某个字段要求列出 policy exceptions。source 里可能有多个合理解释，模型输出了一个合理答案，但和手写 gold 不完全一致，就会被判错。这会让评测变成“模型是否猜中标注者的解释”，而不是“模型是否真的完成任务”。

### 2.2 tau2-bench retail 的结构

后续主评测切换到 tau2-bench retail domain。

数据和运行配置在：

- `data/tau2/domains/retail`
- `configs/tau2/retail_50.json`

本实验使用 50 个 retail tasks，task ids 是配置文件里的 50 个 task id。每个 task 都属于多轮客服场景，例如：

- exchange item
- return delivered item
- cancel pending order
- modify pending order
- lookup-only question

每个 task 的输入不是一堆静态文档，而是：

- user goal / scenario
- shared retail policy
- shared initial database state
- user simulator

### 2.3 LLM user simulator

tau2 的一个关键点是：用户不是固定脚本，而是由一个 LLM 模拟。

本项目配置：

- user simulator：`vertex_ai/gemini-3-flash-preview`
- temperature：0.0
- max tokens：4096

运行时流程是：

1. task 给出用户目标，例如“exchange order #W2378156 里的 keyboard”。
2. user simulator 根据目标扮演 customer。
3. agent 和 user simulator 进行多轮对话，通常 10-20 turns。
4. agent 可以回复用户，也可以调用工具。
5. tau2 environment 执行工具并返回 tool result。
6. 对话结束后，tau2 evaluator 检查最终 DB 状态和最终自然语言回复。

所以这里不是一次性问答，而是一个 **interactive tool-agent evaluation**。

### 2.4 Tool 和环境责任划分

重要区分：

- **agent 决定是否调用工具、调用哪个工具、传什么参数**。
- **tau2 负责实际执行工具、更新 DB、返回 tool result、做最终评分**。

也就是说，tool call 的决策仍然是 agent 的能力；tau2 只是 environment 和 evaluator。

retail domain 一共有 16 个工具，大致分两类：

- Read tools：查用户、查订单、查商品详情等。
- Write tools：换货、退货、取消订单、修改订单等。

read tool 错了通常只是信息不完整；write tool 错了会直接导致最终 DB state 错。

### 2.5 tau2 评分逻辑

tau2 的最终分数是 binary：

- DB Check 通过
- NL Assertion 通过
- 两者都通过才得 1，否则得 0

DB Check：

- 检查最终数据库状态是否和 ground truth 一致。
- 这是 agentic task 最核心的部分，因为客服 agent 不能只是“说对”，必须真的改对系统状态。

NL Assertion：

- 检查 agent 最终回复是否满足语义要求。
- 例如 DB 已经改对了，但 agent 没有回答用户追问的问题，也会失败。

所以一个任务成功必须同时满足：

```text
score = 1 if DB_check == pass and NL_assertion == pass else 0
```

---

## 3. Models

### 3.1 Agent models

Slide 里比较两个 agent model size：

| 模型 | 用途 | 接口 |
|---|---|---|
| Gemini 2.5 Flash | large model | Google Vertex AI |
| gemma4:e4b | small local model | Ollama |

实验配置：

- Gemini 2.5 Flash 跑全部四种架构。
- gemma4:e4b 跑 Flat Single Agent 和 SMAG。
- 小模型没有跑全部 workflow，主要是本地推理速度限制。

### 3.2 User simulator model

user simulator 固定为：

```text
vertex_ai/gemini-3-flash-preview
```

这样可以控制变量：不同 agent architecture 面对的是同一套 user simulation 机制。

---

## 4. Agent runtime：每轮到底发生什么

所有 agent 都接在 tau2 的 `HalfDuplexAgent.generate_next_message()` 接口下。

每一轮 tau2 会给 agent 一条输入：

- user message，或
- tool result / MultiToolMessage

agent 必须返回一个 `AssistantMessage`：

- 要么是自然语言回复；
- 要么是 tool call；
- 不能同时又回复又调工具。

这点很重要，因为它让所有架构都在同一个 tau2 environment 里公平比较。

---

## 5. Architecture 1：Flat Single Agent

### 5.1 运行逻辑

Flat Single Agent 是 baseline。

流程：

```text
User / Tool Message
  -> LLM(bind_tools, full context)
  -> Tool Call or Assistant Response
  -> tau2 environment
  -> next user/tool message
```

实现上使用 LangChain chat model 的 `bind_tools()`。它不是 LangChain 自带的完整 agent loop，而是每个 tau2 turn 调一次 LLM，让它输出 exactly one action。

### 5.2 优点

- LLM 看到完整对话历史。
- 没有中间状态压缩。
- 实现简单，调用链短。

### 5.3 缺点

- 状态追踪完全靠 LLM 隐式记忆。
- 多订单、多 item、多 payment method 时容易混淆。
- write tool 参数一旦错，DB Check 直接失败。

这也是 baseline 的主要错误来源：`WRITE_WRONG_ARGS`。

---

## 6. Architecture 2：4-node Workflow

### 6.1 设计目的

4-node workflow 测试一个常见假设：

> 把一个复杂决策拆成多个专门 LLM 节点，是否会比 single agent 更好？

流程：

```text
User / Tool Message
  -> State Tracker LLM
  -> Reasoner LLM
  -> Verifier LLM
  -> Action Generator LLM
  -> Tool Call / Response
```

### 6.2 四个节点职责

State Tracker：

- 读取最新 user/tool message。
- 更新 structured state。
- 维护用户身份、订单、items、missing info、completed actions 等。

Reasoner：

- 读取 structured state 和 policy。
- 决定下一步应该 ask user、read tool、write tool，还是 final reply。
- 输出 proposal。

Verifier：

- 只在 write tool 或 final reply 前触发。
- 检查 proposal 是否满足 policy、订单状态、认证状态、item 完整性等。
- 如果拒绝，把 feedback 返回给 Reasoner 重试。

Action Generator：

- 把通过验证的 proposal 转成 tau2 需要的 `AssistantMessage`。
- 输出自然语言或 tool call。

### 6.3 失败机制

这个架构的问题不是“节点不够多”，而是 **中间状态压缩不可靠**。

State Tracker 把完整对话压缩成 JSON 时，可能漏掉：

- product variant 信息
- payment_method_id
- 用户中途提出的附加问题
- 某些 order/item 的对应关系

后续 Reasoner、Verifier、Action Generator 都基于这个压缩状态工作。如果 state 错了，后面节点都在错误信息上推理。

实验结果中 4-node Workflow 的主要问题是 `TRANSFER_ABORT` 很高：模型常常误判任务无法完成，于是调用 `transfer_to_human_agents` 放弃。

---

## 7. Architecture 3：Planner-Executor

### 7.1 设计目的

Planner-Executor 是对 4-node workflow 的简化。

目标是减少上下文损失：

- Planner 看完整对话历史。
- Executor 用确定性代码执行。
- Verifier 变轻量，只做写操作前门控。

流程：

```text
User / Tool Message
  -> Planner LLM(full conversation history)
  -> Verifier LLM(weak, conv_summary)
  -> Executor(Python deterministic)
  -> Tool Call / Response
```

### 7.2 组件职责

Planner：

- 读取完整 conversation history、policy、tools。
- 输出 JSON plan，包括 action type、tool name、tool args、text content。

Verifier：

- 只在 write tool / final reply 前触发。
- 使用 Python 生成的 `conv_summary` 做轻量检查。
- 比 4-node 的 Verifier 少依赖 LLM structured state。

Executor：

- 不调用 LLM。
- 检查 tool name 是否存在。
- 过滤不在 schema 里的 hallucinated 参数。
- 构造 tau2 `AssistantMessage`。

### 7.3 失败机制

Planner-Executor 保留了完整上下文，所以比 4-node 少一些 state compression 问题。

但 Verifier 变弱后，很多错误 write args 没有被拦住，导致 `WRITE_WRONG_ARGS` 比较高。它说明：只保留完整上下文不够，写操作前还需要非常精确的字段级校验。

---

## 8. Architecture 4：SMAG

SMAG 全称是：

```text
State Machine Augmented Generation
```

本项目里的 SMAG 是 SMAG-inspired 架构：用 Python state machine 增强 LLM generation。

### 8.1 核心思想

有些问题不应该交给 LLM 推理。

例如：

- `item_id` 是否属于这个 order？
- 这个 order 是否已经查过？
- write operation 是否重复执行过？
- 用户是否已经 authenticated？

这些都是查表或前置条件检查，可以用 Python 确定性完成。

SMAG 的核心是：

- Python 负责状态追踪和 precondition check。
- LLM 负责语言理解、产品变体选择、下一步动作选择和自然语言回复。

### 8.2 运行流程

```text
User / Tool Message
  -> Python StateMachine.update()
  -> LLM(full context + state machine context)
  -> Python StateMachine.can_execute() for write tools
  -> Tool Call / Response
```

更细地说：

1. tau2 传入 user message 或 tool result。
2. 如果是 tool result，Python state machine 解析结果并更新状态。
3. state machine 生成一段 `<state_machine>` context 注入 system prompt。
4. LLM 看完整对话历史 + state machine context，决定下一步。
5. 如果 LLM 提议 write tool，Python `can_execute()` 做确定性前置检查。
6. 如果检查失败，把 rejection reason 注入 prompt，让 LLM 最多重试 2 次。
7. 通过后返回 tau2 tool call。

### 8.3 State machine 维护什么

核心状态包括：

- authenticated
- user_id
- orders
- order status
- payment_method_id
- item_id -> product / name 映射
- completed_writes
- error_log

示例：

```text
authenticated: true
orders:
  #W2378156: status=delivered, payment=credit_card_9513926
    item 1151293680: Mechanical Keyboard
completed_writes: none
```

### 8.4 can_execute 检查什么

对 write tools 做确定性检查：

- 用户是否已认证。
- order_id 是否存在。
- order status 是否满足工具要求。
- item_ids 是否属于该 order。
- payment_method_id 是否存在。
- 是否重复执行同一类 write。

这些检查用 Python dict / set 完成，不让 LLM“猜”。

### 8.5 为什么 SMAG 更好

tau2 retail 的主要难点不是读信息，而是 **写参数精度**。

Flat agent 能读到信息，但会在多订单、多 item 场景里传错：

- wrong item ID
- swapped payment method
- extra item
- missing item

SMAG 把这些字段级一致性检查从 LLM 移到 Python，所以减少了 write precision 相关错误，也减少了 LLM workflow 的误判放弃。

---

## 9. Results：最终 50 tasks

### 9.1 Success / Avg Reward

| System | Model | Tasks | Success | Avg Reward |
|---|---|---:|---:|---:|
| Flat Single Agent | Gemini 2.5 Flash | 50 | 27/50 | 0.54 |
| Flat Single Agent | gemma4:e4b | 50 | 25/50 | 0.50 |
| 4-node Workflow | Gemini 2.5 Flash | 50 | 17/50 | 0.34 |
| Planner-Executor | Gemini 2.5 Flash | 50 | 19/50 | 0.38 |
| SMAG | Gemini 2.5 Flash | 50 | 31/50 | 0.62 |
| SMAG | gemma4:e4b | 50 | 29/50 | 0.58 |

主要解读：

- large flat vs small flat：0.54 vs 0.50，只差 4 个百分点。
- 两个 LLM workflow 都低于 flat baseline。
- SMAG 提升最明显：Gemini SMAG 0.62，gemma4 SMAG 0.58。
- 小模型 + SMAG 超过了大模型 flat single agent。

### 9.2 Error Distribution

| System | Model | WRITE_WRONG_ARGS | PARTIAL_WRITE | DB_OK_NL_FAIL | TRANSFER_ABORT | NO_WRITE | Total Fail |
|---|---|---:|---:|---:|---:|---:|---:|
| Flat Single Agent | Gemini 2.5 Flash | 11 | 7 | 1 | 4 | 0 | 23 |
| Flat Single Agent | gemma4:e4b | 12 | 5 | 2 | 6 | 0 | 25 |
| 4-node Workflow | Gemini 2.5 Flash | 9 | 5 | 4 | 15 | 0 | 33 |
| Planner-Executor | Gemini 2.5 Flash | 17 | 2 | 0 | 11 | 1 | 31 |
| SMAG | Gemini 2.5 Flash | 9 | 3 | 3 | 4 | 0 | 19 |
| SMAG | gemma4:e4b | 7 | 5 | 4 | 5 | 0 | 21 |

错误类型含义：

- `WRITE_WRONG_ARGS`：执行了写操作，但参数错，例如 item id 错或 payment method 搞混。
- `PARTIAL_WRITE`：任务需要多个写操作，只有一部分写对。
- `DB_OK_NL_FAIL`：数据库改对了，但最终回复没满足语义要求。
- `TRANSFER_ABORT`：agent 调用了 transfer_to_human_agents，中途放弃。
- `NO_WRITE`：任务需要写操作，但 agent 从未尝试写。

### 9.3 结果背后的逻辑

Flat Single Agent：

- 主要错在 `WRITE_WRONG_ARGS`。
- 说明它能读到很多信息，但写参数精度不够。

4-node Workflow：

- `WRITE_WRONG_ARGS` 没有最高，但 `TRANSFER_ABORT` 非常高。
- 说明多 LLM 节点引入了新的 failure mode：state compression / verifier feedback 让 agent 误以为任务不可完成。

Planner-Executor：

- 保留完整上下文后，state loss 有改善。
- 但 verifier 变弱，`WRITE_WRONG_ARGS` 升高。

SMAG：

- 成功率最高。
- 不是因为 LLM 更强，而是因为把稳定、可规则化的状态追踪和前置校验交给 Python。

---

## 10. Key Findings 的逻辑依据

### Finding 1：More LLM nodes 不等于 better performance

证据：

- Flat large：0.54
- 4-node Workflow：0.34
- Planner-Executor：0.38

解释：

- 多节点 LLM workflow 会把一次决策拆成多个中间表示。
- State Tracker 一旦漏信息，下游节点会基于错误 state 推理。
- Verifier 如果误判，会导致合法操作被拒绝，甚至触发 transfer。

所以问题不是“workflow 不能做”，而是 **LLM-only decomposition 容易产生 error accumulation**。

### Finding 2：小模型 + 好架构可以超过 flat 大模型

证据：

- Gemini 2.5 Flash flat：0.54
- gemma4:e4b SMAG：0.58

解释：

- tau2 retail 的瓶颈主要是状态追踪和参数一致性，不是纯语言推理能力。
- 小模型只要不负责容易出错的字段级校验，就可以表现得更好。

### Finding 3：结构可预测任务适合 rule-based harness

证据：

- SMAG 把 state tracking / can_execute 移到 Python 后，两个模型都提升。
- Python 检查 item/order/payment 关系，比 LLM 语义判断更可靠。

解释：

- 高频客服任务有固定结构：认证、查订单、查商品、写操作、最终回复。
- 这些流程中很多约束是可编码的。
- 可编码的部分用 deterministic harness，LLM 保留在语言理解和选择策略上。

---

## 11. QA 速查

### Q1：tau2 的 gold answer 是怎么来的？

tau2 不要求 agent 输出一个静态 gold JSON。它通过任务定义、初始 DB、policy、reference behavior / evaluator 计算最终预期状态。评测时主要比较最终 DB state 和 NL assertions。也就是说，agent 的实际工具操作会改变 DB，最后看 DB 是否到达正确状态。

### Q2：NL Assertion 是 LLM judge 吗？

在本项目配置里，NL assertion judge 使用 `vertex_ai/gemini-3-flash-preview`，temperature 0。DB Check 是结构化状态比较，NL Assertion 是语义检查。

### Q3：agent 调工具是 tau2 决定还是 agent 决定？

agent 决定。agent 输出 tool call name 和 arguments；tau2 environment 负责执行工具、返回结果、更新数据库和最终评分。

### Q4：为什么 small flat 和 large flat 差距只有 4%？

因为 retail task 的核心瓶颈是写参数精度和状态追踪，不是深层知识推理。小模型在读信息上不一定差很多，但在 write precision 上略弱。

### Q5：为什么 4-node workflow 反而更差？

因为它引入了中间状态压缩。State Tracker 漏掉或抽象掉信息后，Reasoner 和 Verifier 都会基于不完整 state 工作，导致误判、重复读工具或 transfer abort。

### Q6：Planner-Executor 为什么没有解决问题？

它解决了一部分上下文压缩问题，因为 Planner 看完整历史。但 Verifier 更轻量，字段级校验不够强，所以更多错误 write args 被放行。

### Q7：SMAG 为什么有效？

SMAG 把“可以确定性判断”的部分移到 Python，比如 item_id 是否在订单里、order status 是否匹配、是否重复写。LLM 不再需要记住和验证所有字段映射，只负责语言理解和下一步动作。

### Q8：SMAG 是不是完全不需要 LLM 推理？

不是。LLM 仍然负责理解用户目标、选择工具、根据商品详情选择 variant、生成回复。Python 只负责状态维护和前置条件检查。

### Q9：为什么说 rule-based harness 比 LLM pipeline 更适合这类任务？

因为这类客服任务有稳定流程和明确约束。对于明确约束，Python 检查比 LLM 判断更可靠；LLM pipeline 反而会在节点传递中累积错误。

### Q10：这些结论能推广到所有 agentic tasks 吗？

不能直接推广到所有任务。这个结论更适用于结构明确、工具固定、状态可解析、写操作约束明确的 high-frequency agentic tasks。对于开放式研究、创意、长程规划任务，纯规则 harness 不一定适用。

