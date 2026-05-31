# Planner-Executor Agent 设计方案（tau2 Retail）

## 1. 动机：为什么从 4 节点流水线切换

在 4 节点线性流水线（State Tracker → Reasoner → Verifier → Action Generator）的多轮实验中，最好成绩稳定在 0.45（前 20 任务），始终低于 large_single agent 的 0.50。

诊断发现根本原因：**State Tracker 把产品变体信息抽象掉了**。当用户说"我想换一个更大的"，State Tracker 无法可靠地从 `get_product_details` 的返回结果里选出正确的 variant_id，导致 Reasoner 反复调 read 工具（最严重的案例是 `get_product_details` 被调用 85 次），整个对话陷入死循环。

参考文献 "Rethinking the Value of Multi-Agent Workflow"（arxiv 2601.12307）也指出：**同构多 agent（同一个 LLM、不同 prompt）相比单 agent 没有收益**，多节点传递引入的上下文损耗会抵消结构化的好处。

---

## 2. 架构设计

### 核心思路

把推理和执行分成两个专注的角色：

- **Planner**：看完整对话历史，做决策——保留 large_single 的完整推理能力
- **Executor**：纯确定性，把 Planner 的计划转成 tau2 tool call——不引入 LLM 误差
- **Verifier**：轻量门控，只在写操作前检查——比较 conv_summary，不依赖结构化 state

```
tau2 runtime
│
│  user message / tool result
│         ↓
├──── generate_next_message(msg, state) ────────────────────────────────────┐
│                                                                            │
│   [Planner]  ← 完整对话历史 + policy + 工具描述 + turn_count              │
│       ↓ JSON 计划 {type, tool, tool_args, text_content}                   │
│                                                                            │
│   [Verifier] ← 仅在 write_tool / final_reply 时触发                       │
│       ↓ 使用 conv_summary（Python 确定性生成）                             │
│       ↓ approved / rejected（→ 回到 Planner，最多 2 次）                  │
│                                                                            │
│   [Executor] ← 纯确定性：校验参数 + 构造 tau2 AssistantMessage             │
│       ↓                                                                   │
│   AssistantMessage（text reply 或 tool call）                              │
└────────────────────────────────────────────────────────────────────────────┘
```

### 每轮最多 2 个 LLM 调用

| 情况 | LLM 调用次数 |
|---|---|
| ask_user / call_tool | 1（Planner） |
| write_tool / final_reply（通过验证） | 2（Planner + Verifier） |
| write_tool（拒绝后重试） | 最多 4（Planner + Verifier × 2） |

对比原 4 节点流水线每轮固定 3-4 次，这里减少了一半。

---

## 3. 各组件说明

### Planner

**输入**：
- 完整对话历史（tau2 messages → LangChain format）
- Policy 文本
- 工具描述（名称 + 参数类型）
- turn_count
- 可选：Verifier 的拒绝反馈（用于重试）

**输出**：JSON 计划

```json
{
  "type": "ask_user | call_tool | write_tool | final_reply",
  "reason": "brief reason",
  "tool": "exact tool name",
  "tool_args": { "param": value },
  "text_content": "what to say to the user",
  "requires_verification": true or false
}
```

**关键设计**：
- 不做任何上下文压缩——完整对话历史直接传入，和 large_single 一样
- 产品变体选择由 Planner 直接从对话历史里的 tool 结果中判断，不经过中间抽象
- `requires_verification=true` 仅用于 `write_tool` 和 `final_reply`

**对比 4 节点流水线中的 Reasoner**：Reasoner 只能看到 State Tracker 压缩后的结构化状态；Planner 看到原始完整对话，等于完整保留了 large_single 的推理能力。

---

### Verifier（轻量版）

**输入**：
- `conv_summary`（由 Python 确定性生成，见下）
- Planner 的计划（提议动作）
- Policy 文本

**检查项（写操作）**：
1. 用户已认证（对话中有成功的 user lookup）
2. 订单状态匹配（exchange/return 需 delivered；cancel/modify 需 pending）
3. 非重复写（该操作未在对话中已执行）
4. item_ids 正确（来自订单详情，非 product_ids）
5. 包含所有用户提到的 item
6. payment_method_id 存在

**关键改进**：原 4 节点流水线中，Verifier 依赖 State Tracker 的结构化状态来判断支付方式是否匹配，State Tracker 不可靠时会产生大量误判（false reject）。新版 Verifier 使用 `conv_summary` 直接从对话历史提取关键事件，不再依赖 LLM 生成的中间 state。

---

### conv_summary（Python 确定性生成）

这是新架构与旧流水线的核心区别之一：**不用 LLM 提取 state，用代码解析对话历史**。

```python
# 输入：tau2 messages 列表
# 输出：紧凑的文本摘要，例如：
"""
USER: I want to exchange the keyboard in order W2378156 for a wireless one.
AUTH: user_id=yusuf_rossi_9620
ORDER: #W2378156 status=delivered pay=credit_card_9513926
WRITE_EXECUTED: exchange_delivered_order_items → success
"""
```

生成规则：
- `find_user_id_*` 成功 → `AUTH: user_id=...`
- `get_order_details` 成功 → `ORDER: #WX status=... pay=...`
- Write tool 调用 → `WRITE_PROPOSED: tool_name(args)`
- Write tool 成功结果 → `WRITE_EXECUTED: tool_name → success`
- 工具错误 → `TOOL_ERROR: tool_name → error msg`

完全确定性，零 LLM 调用，Verifier 拿到的上下文比 State Tracker 更可靠。

---

### Executor

**输入**：Planner 通过 Verifier 验证的计划

**输出**：tau2 `AssistantMessage`

**逻辑（纯确定性）**：
1. 如果 `type` 是 `call_tool` 或 `write_tool`：
   - 校验工具名是否在已知工具列表中（P1 防护）
   - 过滤掉工具参数中不在 schema 里的字段（防止 LLM 幻想参数导致工具报错）
   - 构造 `ToolCall`，返回 tool_call 类型消息
2. 如果 `type` 是 `ask_user` 或 `final_reply`：
   - 直接使用 Planner 的 `text_content`，返回 text 类型消息

不需要 LLM 调用。

---

## 4. LangGraph DAG

```
START
  │
  ▼
planner ◄────────────────────────────────┐
  │                                       │
  ├── requires_verification=false ──► executor ──► END
  │
  ▼ (requires_verification=true)
verifier
  │
  ├── approved=true  ──────────────► executor ──► END
  │
  └── approved=false ──► bump_retry ──► planner（带 feedback）
                              │
                              └── (retry >= 2) ──► safe_fallback ──► END
```

---

## 5. Agent State（跨轮持久化）

```python
class PlannerExecutorState:
    messages: list[Any]          # tau2 完整消息历史
    turn_count: int              # 当前轮次
    write_counts: dict[str, int] # 每个写工具的调用次数（用于 P0 循环防护）
```

**没有 structured_state**：上下文信息完全在 messages 里，Planner 每轮都看完整历史。

---

## 6. 与其他方案的对比

| 维度 | large_single | 4 节点流水线 | Planner-Executor |
|---|---|---|---|
| 每轮 LLM 调用 | 1 | 3-4 | 1-2 |
| 对话上下文完整性 | 完整 | 压缩（State Tracker 抽象） | 完整 |
| 写操作验证 | 无 | Verifier（依赖 structured state） | Verifier（依赖 conv_summary） |
| 产品变体选择 | 直接推理 | 依赖 State Tracker 提取 | 直接推理 |
| 状态追踪可靠性 | 隐式（上下文召回） | LLM 生成 state（不可靠） | Python 确定性 conv_summary |
| 循环防护 | 无 | P0 write + read 计数 | P0 write 计数 |

---

## 7. 实现文件

```
src/cs263_agent_eval/
  tau2/
    planner_executor_agent.py   ← PlannerExecutorTau2Agent + LangGraph

configs/tau2/
  retail_50.json                ← 新增 "planner_executor_large" 条目

scripts/
  run_tau2_planner_executor.py  ← runner 脚本
```

---

## 8. 预期改进

**应该修复的问题（来自 4 节点流水线的已知失败）**：
- task 0/3/4/8/23：产品变体选择死循环 → Planner 直接从 tool 结果里选，不经过 State Tracker
- task 11/13/14/15：保持 Verifier 对写参数的门控优势

**不确定的问题**：
- task 19/20/21/22：复杂多步操作，可能仍然困难
