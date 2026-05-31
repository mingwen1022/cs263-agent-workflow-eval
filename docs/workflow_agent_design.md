# Workflow Agent 设计方案（tau2 Retail）

## 1. 总体思路

本文档描述一个 4 节点 workflow agent，用于替代 tau2 retail 任务中的平铺式单节点 agent。该 workflow 运行在 tau2 的 `HalfDuplexAgent.generate_next_message()` 接口内：每次 tau2 传入一条消息（用户轮或工具结果），pipeline 执行一遍，返回恰好一个 action。

```
tau2 runtime
│
│  用户消息 / 工具结果
│         ↓
├──── generate_next_message(msg, state) ──────────────────────────────────────┐
│                                                                              │
│   [节点 1] State Tracker    ← 最新消息 + structured_state                   │
│         ↓ 更新后的 structured_state                                          │
│   [节点 2] Reasoner         ← structured_state + policy + tools             │
│         ↓ proposal                                                           │
│   [节点 3] Verifier         ← 仅在 proposal 为 write_tool / final_reply 时  │
│         ↓ approved / rejected（rejected → 回到 Reasoner 带 feedback）        │
│   [节点 4] Action Generator ← 通过验证的 proposal + state                   │
│         ↓                                                                   │
│   AssistantMessage（文本回复 或 tool call）                                   │
└──────────────────────────────────────────────────────────────────────────────┘
│
│  tau2 执行工具 / 把回复发给 user simulator
│         ↓ 下一条 observation
│   （循环）
```

**structured state 跨轮持久化**（存在 `WorkflowAgentState` 里）。每轮只更新增量，不重新扫描整个对话历史。

---

## 2. Structured State 结构

State Tracker 维护一个 JSON 对象作为 agent 的工作记忆，取代单节点 agent 依赖上下文隐式记忆的方式。

```json
{
  "user_identity": {
    "authenticated": false,
    "user_id": null,
    "name": null,
    "zip": null,
    "email": null
  },
  "task_goal": {
    "intent": null,
    "order_ids": [],
    "description": ""
  },
  "orders": {
    "<order_id>": {
      "status": null,
      "payment_method_id": null,
      "items": [
        {
          "item_id": null,
          "product_id": null,
          "name": null,
          "status": "pending_lookup | looked_up | replacement_selected | done"
        }
      ]
    }
  },
  "items_to_modify": [
    {
      "name": "keyboard",
      "item_id": null,
      "product_id": null,
      "replacement_product_id": null,
      "status": "needs_order_lookup | needs_product_lookup | needs_replacement_selection | ready"
    }
  ],
  "missing_info": ["用户身份认证", "thermostat 的替换商品"],
  "tool_results": [
    {
      "tool": "find_user_id_by_name_zip",
      "args": {},
      "result_summary": "user_id = yusuf_rossi_9620"
    }
  ],
  "constraints": [
    "exchange_delivered_order_items 每个订单只能调用一次",
    "订单状态必须是 delivered 才能换货",
    "退款时 payment method 必须是 gift_card 或 credit_card"
  ],
  "completed_actions": [
    {
      "tool": "exchange_delivered_order_items",
      "args": {},
      "turn": 7
    }
  ],
  "task_complete": false
}
```

---

## 3. 各节点说明

### 节点 1：State Tracker

**职责**：纯提取。根据最新 observation 更新 structured state，不做任何决策。

**输入**：
- 最新消息（用户消息或工具结果）
- 上一轮的 `structured_state`
- 当前轮次编号

**输出**：更新后的 `structured_state`（JSON 增量或完整替换）

**Prompt 策略**：
```
你维护一个客服对话的结构化状态。
给定最新消息和当前状态，输出更新后的状态 JSON。
只更新有新信息的字段。
不要推断或做决策，只提取事实。
```

**更新示例**：

| Observation | State 增量 |
|---|---|
| "我叫 Yusuf Rossi，邮编 19122" | `user_identity.name`、`user_identity.zip`，从 `missing_info` 移除"用户认证" |
| 工具结果：`user_id = yusuf_rossi_9620` | `user_identity.user_id = "yusuf_rossi_9620"`，`user_identity.authenticated = true` |
| 工具结果：订单详情 | `orders[W2378156].status`、`items[*].item_id` 等填入 |
| 工具结果：`exchange_delivered_order_items` 成功 | `completed_actions` 追加，`task_complete = true` |

**设计选择**：State Tracker 是小而专注的 LLM 调用（仅输出 JSON）。它看不到完整对话历史，只看增量和当前 state，减少 token 消耗，也更适合小模型。

---

### 节点 2：Reasoner / Planner

**职责**：决策中心。读取 `structured_state`，决定下一步该做什么，输出结构化 `proposal`（不是自然语言）。

**输入**：
- `structured_state`
- Policy 文本
- 可用工具列表（名称 + 描述）
- 可选：来自 Verifier 拒绝的 `verifier_feedback`

**输出**：JSON `proposal`

```json
{
  "type": "ask_user | call_tool | write_tool | final_reply",
  "reason": "用户提供了 order_id，但尚未完成身份认证。",

  // ask_user 时：
  "ask_content": "请用户提供姓名和邮编以完成认证。",

  // call_tool 或 write_tool 时：
  "tool": "find_user_id_by_name_zip",
  "tool_args": {
    "first_name": "Yusuf",
    "last_name": "Rossi",
    "zip": "19122"
  },

  // final_reply 时：
  "reply_content": "确认键盘和温控器均已完成换货，说明使用的支付方式。",

  // 是否需要 Verifier 验证：
  "requires_verification": true
}
```

`requires_verification` 在 `type` 为 `write_tool` 或 `final_reply` 时为 `true`。

**Reasoner 应遵循的决策逻辑**（编码进 prompt）：

1. `user_identity.authenticated == false` 且需要操作订单 → 先问用户身份
2. `items_to_modify` 中有 `status != ready` 的条目 → 先补全缺失信息
3. 所有 item 均 `ready` 且该意图无 `completed_actions` → 提议写操作
4. `task_complete == true` → 提议 `final_reply`
5. 存在 `verifier_feedback` → 先解决 blocking issues 再重新提议

**设计选择**：Reasoner 只输出 JSON，不生成自然语言，让小模型专注于逻辑判断，语言生成交给节点 4。

---

### 节点 3：Verifier

**职责**：不可逆操作的守门人。仅在 `proposal.requires_verification == true` 时触发。

**触发条件**：
- 写操作工具调用（如 `exchange_delivered_order_items`、`return_delivered_order_items`、`cancel_pending_order`、`modify_pending_order`）
- `final_reply`（对话结束前）

**输入**：
- `structured_state`
- Reasoner 输出的 `proposal`
- Policy 文本

**输出**：

```json
// 通过
{
  "approved": true,
  "blocking_issues": []
}

// 拒绝
{
  "approved": false,
  "blocking_issues": [
    "用户要求换两件商品，但 tool_args 里只有一个 item_id。",
    "温控器的替换商品尚未选定。",
    "exchange_delivered_order_items 只能调用一次，必须把两件商品都包含进去。"
  ],
  "required_fix": "先确认温控器的替换 product_id，再调用 exchange。"
}
```

**写操作校验项**：

| 校验项 | 说明 |
|---|---|
| 完整性 | 用户提到的所有 item 都包含在调用里 |
| 无重复写 | `completed_actions` 里没有该订单的同一工具调用 |
| 订单状态 | `orders[order_id].status` 满足工具要求（如换货需 delivered） |
| 已认证 | `user_identity.authenticated == true` |
| 参数正确性 | `item_ids` 是订单里的 item ID，不是 product ID |
| 支付方式 | 退款时 `payment_method_id` 存在且有效 |

**最终回复校验项**：

| 校验项 | 说明 |
|---|---|
| 任务覆盖 | `task_goal` 中的所有意图都有对应的 `completed_action` |
| 无未完成项 | `items_to_modify` 中无 `status != done` 的条目 |
| 回复准确 | `reply_content` 提到了所有被操作的 item |

**拒绝循环**：Verifier 拒绝后，workflow 回到节点 2（Reasoner）并注入 `verifier_feedback`。每轮最多重试 2 次，超过后退回安全的 ask_user 动作。

**设计选择**：Verifier 只对照已知 state 检查提议动作，不重新读对话也不调工具。误报（拦截合法操作）代价低（多一轮）；漏报（放过错误写操作）代价高（任务失败 + DB 不可逆变更）。

---

### 节点 4：Action Generator

**职责**：把通过验证的 proposal 转成 tau2 期望的 `AssistantMessage`。唯一需要生成自然语言的节点。

**输入**：
- 通过验证的 `proposal`
- `structured_state`（用于事实依据）
- Policy 文本（用于语气和措辞约束）

**输出**：tau2 `AssistantMessage`，两种形式之一：
- `content`（文本）+ `tool_calls = None` → 文本回复 / 问用户
- `content = None` + `tool_calls` 列表 → 工具调用

**映射关系**：

| Proposal 类型 | Action Generator 输出 |
|---|---|
| `ask_user` | 生成简洁自然的提问，以 `ask_content` 为意图 |
| `call_tool` | 从 `tool` + `tool_args` 构造 `ToolCall`，无需 LLM |
| `write_tool` | 从 `tool` + `tool_args` 构造 `ToolCall`，无需 LLM |
| `final_reply` | 生成完整确认回复，以 `reply_content` 为提纲 |

**设计选择**：`call_tool` 和 `write_tool` 是纯确定性的，直接格式化 JSON 成 ToolCall，不需要 LLM 调用。只有 `ask_user` 和 `final_reply` 才需要生成文本，小模型的语言生成压力大幅减少。

---

## 4. LangGraph DAG

```
START
  │
  ▼
state_tracker
  │
  ▼
reasoner ◄──────────────────────────────────────────┐
  │                                                  │
  ├── requires_verification=false ──► action_generator ──► END
  │
  ▼ (requires_verification=true)
verifier
  │
  ├── approved=true  ──────────────► action_generator ──► END
  │
  └── approved=false ──► bump_retry ──► reasoner（带 feedback）
                              │
                              └── (retry >= 2) ──► safe_fallback ──► END
```

**各节点类型**：
- `state_tracker` — LLM 调用（JSON 输出）
- `reasoner` — LLM 调用（JSON 输出），可接收 `verifier_feedback`
- `verifier` — LLM 调用（JSON 输出），仅写操作/最终回复时触发
- `action_generator` — 文本回复时 LLM 调用；工具调用时纯确定性
- `bump_retry` — 计数器自增，无 LLM
- `safe_fallback` — 重试耗尽时生成安全的 ask_user 消息

**每轮执行机制**：每次 `generate_next_message()` 调用时，graph 跑到 END 并返回一个 `AssistantMessage`。`WorkflowAgentState`（含 `structured_state`）存在 tau2 `HalfDuplexAgent` 的 state 里，跨轮携带。

---

## 5. Agent State 与 tau2 集成

```python
@dataclass
class WorkflowAgentState:
    messages: list[Any]           # tau2 消息历史（同 LangChainTau2AgentState 的角色）
    structured_state: dict        # 由 State Tracker 跨轮维护
    turn_count: int = 0
    last_verifier_feedback: dict | None = None
    retry_count: int = 0          # 每轮重置

class WorkflowTau2Agent(HalfDuplexAgent[WorkflowAgentState]):

    def get_init_state(self, message_history=None) -> WorkflowAgentState:
        return WorkflowAgentState(
            messages=list(message_history or []),
            structured_state=EMPTY_STATE_TEMPLATE,
        )

    def generate_next_message(self, message, state) -> tuple[AssistantMessage, WorkflowAgentState]:
        # 1. 把传入消息追加到历史
        # 2. 运行 LangGraph pipeline 一次 → 得到 AssistantMessage
        # 3. 把 AssistantMessage 追加到历史
        # 4. 返回 (AssistantMessage, updated_state)
        ...
```

LangGraph graph 在 agent 构造时编译一次，之后每轮复用。

---

## 6. 与单节点 Agent 的对比

| 维度 | 单节点（large/small） | Workflow Agent |
|---|---|---|
| 每轮输入 | 完整消息历史 + policy + 工具 schema | 结构化 state 增量 + 最新消息 |
| 记忆方式 | 隐式（依赖上下文召回） | 显式 JSON state，每轮更新 |
| 决策方式 | 一次 LLM 调用包办一切 | 分离：State Tracker（提取）→ Reasoner（决策）→ Verifier（校验）→ Generator（生成） |
| 写操作安全性 | LLM 可能用错误参数调写操作 | Verifier 门控每次写操作，Reasoner 可重试 |
| 上下文增长 | 随对话轮次无限增长 | State Tracker 把历史压缩进 structured state，上下文保持有界 |
| 小模型适配性 | 小模型难以在一次调用里处理长上下文+多步推理 | 每个节点任务单一且 JSON-only，更适合小模型 |
| Token 消耗 | 长任务消耗高（每轮传完整历史） | 读操作无 LLM 消耗；写操作多一次 Verifier 调用 |

---

## 7. 实现计划

### Phase 1：基础框架
- [ ] 定义 `WorkflowAgentState` dataclass 和空 state 模板
- [ ] 实现继承 `HalfDuplexAgent` 的 `WorkflowTau2Agent`
- [ ] 打通 `generate_next_message` → LangGraph 执行 → 返回一个 action

### Phase 2：节点实现
- [ ] `state_tracker_node`：prompt + JSON schema + 更新逻辑
- [ ] `reasoner_node`：prompt + proposal schema + verifier_feedback 注入
- [ ] `verifier_node`：prompt + retail 专项校验（exchange、return、cancel、modify）
- [ ] `action_generator_node`：ask/reply 文本生成；tool call 纯确定性构造

### Phase 3：LangGraph 连线
- [ ] 构建带条件边的 graph（verifier 门控、重试循环、safe fallback）
- [ ] 加入 `bump_retry` 和 `safe_fallback` 节点
- [ ] 调整 `recursion_limit` 和重试上限

### Phase 4：注册与 Runner
- [ ] 将 `WorkflowTau2Agent` 注册到 tau2 registry，命名为 `"workflow_agent"`
- [ ] 在 `configs/tau2/retail_50.json` 的 `agent_systems` 里加入 `"workflow"` 条目
- [ ] 创建 `scripts/run_tau2_workflow.py`

### Phase 5：评估
- [ ] 用与 large/small baseline 相同的前 20 个 task_id 跑 workflow agent
- [ ] 对比：成功率、partial action reward、平均轮次、写操作错误率
- [ ] 错误分析：Verifier 拦截了哪些单节点 agent 会放过的错误？

---

## 8. Retail 专项 Verifier 规则

从 retail policy 和已观察到的失败模式中提炼：

```python
WRITE_TOOL_CHECKS = {
    "exchange_delivered_order_items": [
        "订单状态必须是 'delivered'",
        "用户提到的所有 item 必须都在 item_ids 列表里",
        "每个 item_id 必须有对应的 new_item_ids 条目",
        "新商品必须是同类型、不同选项（如尺寸/颜色）",
        "state 里必须有 payment_method_id",
        "每个订单只能调用一次 exchange，必须一次性包含所有 item",
        "用户必须已认证",
    ],
    "return_delivered_order_items": [
        "订单状态必须是 'delivered'",
        "该 item 之前不能已被退货",
        "退款的 payment_method_id 必须是原始支付方式",
        "用户必须已认证",
    ],
    "cancel_pending_order": [
        "订单状态必须是 'pending'",
        "用户必须已认证",
    ],
    "modify_pending_order": [
        "订单状态必须是 'pending'",
        "所有要修改的 item 必须在一次调用里包含",
        "用户必须已认证",
    ],
}
```

---

## 9. 待创建文件

```
src/cs263_agent_eval/
  tau2/
    workflow_agent.py          ← WorkflowTau2Agent + LangGraph pipeline
  workflows/
    tau2_retail_workflow.py    ← 各节点实现 + prompts

configs/tau2/
  retail_50.json               ← agent_systems 里加 "workflow" 条目

scripts/
  run_tau2_workflow.py         ← 同 run_tau2_small_single.py 结构
```
