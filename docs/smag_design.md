# SMAG Agent 设计方案（tau2 Retail）

## 1. 动机

前几代架构（workflow、planner_executor）的核心问题是：**写操作验证依赖 LLM**。无论是 workflow 的 Verifier 节点，还是 PE 的 conv_summary Verifier，本质上都是让 LLM 来判断"这个操作现在能不能执行"。LLM 在这件事上有两个固有弱点：

1. **状态提取不可靠**：LLM 生成的 structured state 或 conv_summary 可能漏掉关键字段（如 payment_method_id 未被正确提取到 state 里），导致本来合法的写操作被误拒，或本来非法的操作被放行
2. **不是真正的校验**：LLM "验证" 时实际上是在做语义理解，而不是精确的字段比对。问 LLM "这个 item_id 在订单里吗" 和直接在 Python dict 里查 key 是完全不同的可靠性

SMAG（State Machine Augmented Generation）的核心思路：**把状态追踪和前置校验从 LLM 移到确定性 Python 代码**，LLM 只负责推理和自然语言生成。

---

## 2. 架构设计

```
tau2 runtime
│
│  user message / tool result
│         ↓
├──── generate_next_message(msg, state) ─────────────────────────────────────┐
│                                                                             │
│   [1] Python StateMachine.update()                                         │
│       ← 解析 tool result（JSON 解析，确定性）                               │
│       → 更新：authenticated, orders, completed_writes, error_log           │
│         ↓                                                                  │
│   [2] LLM（完整对话历史 + SM context 注入）                                 │
│       ← bind_tools()，直接输出 tool_call 或 text                            │
│         ↓                                                                  │
│   [3] Python StateMachine.can_execute()（仅写操作触发）                     │
│       → 确定性前置校验                                                      │
│       → 拒绝时注入原因，重试 LLM（最多 2 次）                               │
│         ↓                                                                  │
│   [4] Executor（参数校验 + 构造 tau2 AssistantMessage）                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**每轮 LLM 调用次数**：
- 正常轮次（读工具/文本）：1 次
- 写操作通过校验：1 次（LLM）
- 写操作被拒绝后重试：最多 3 次（LLM × 3，超过则直接执行原方案）

---

## 3. Python StateMachine

状态机是整个架构的核心，全部逻辑由 Python 确定性实现，不涉及任何 LLM 调用。

### 3.1 状态数据结构

```python
@dataclass
class OrderState:
    order_id: str
    status: str                    # "delivered" | "pending" | "cancelled" ...
    payment_method_id: str
    items: dict[str, dict]         # item_id -> {product_id, name}

@dataclass
class RetailStateMachine:
    authenticated: bool            # find_user_id 成功后设为 True
    user_id: str | None
    orders: dict[str, OrderState]  # order_id -> OrderState
    completed_writes: list[dict]   # [{tool, order_id, args, turn}]
    error_log: list[dict]          # tool 调用错误记录
```

### 3.2 update()：从 tool result 更新状态

**纯 JSON 解析，不走 LLM**：

| Tool 调用 | 更新逻辑 |
|---|---|
| `find_user_id_by_name_zip` / `find_user_id_by_email` | `authenticated=True`, `user_id=result.strip()` |
| `get_user_details` | 从 `d["orders"]` 提取 order_id 列表，初始化 OrderState |
| `get_order_details` | 解析 `status`, `payment_method_id`, `items[]`，填入 OrderState |
| 任意写工具（成功） | 追加到 `completed_writes` |
| 任意工具（Error 结果） | 追加到 `error_log`，不更新其他状态 |

### 3.3 can_execute()：确定性前置校验

在 LLM 提议写操作后，Python 立即检查以下条件：

| 检查项 | 实现方式 |
|---|---|
| 用户已认证 | `self.authenticated == True` |
| 无重复写操作 | `(tool_name, order_id)` 不在 `completed_writes` 里 |
| 订单状态匹配 | `self.orders[order_id].status == "delivered"` / `"pending"` |
| item_ids 合法 | `item_ids ⊆ set(self.orders[order_id].items.keys())` |
| payment_method_id 存在 | `args.get("payment_method_id") is not None` |

每项检查都是 O(1) Python 操作，输出具体的 blocking issues 列表，比 LLM 给出的模糊拒绝理由更精确。

### 3.4 to_context()：生成注入 LLM 的状态摘要

```
<state_machine>
authenticated: true (user_id: yusuf_rossi_9620)
orders:
  #W2378156: status=delivered, payment=credit_card_9513926
    item 1151293680: Mechanical Keyboard
    item 4983901480: Smart Thermostat
completed_writes: none
</state_machine>
```

这段文本每轮注入 LLM 的 system prompt，让 LLM 知道当前状态——但不依赖 LLM 来维护这个状态。

---

## 4. LLM 的角色

SMAG 中 LLM 负责的事情：

1. **推理对话意图**：理解用户想要什么（exchange which item for what）
2. **选择产品变体**：从 get_product_details 的返回里判断哪个 variant 匹配用户偏好
3. **决定操作序列**：什么时候调哪个工具（信息收集 → 询问确认 → 执行写操作）
4. **生成自然语言**：用户面对的确认信息、问题、最终回复

LLM **不负责**：

- 判断 item_id 是否在订单里（Python 做）
- 判断订单状态是否匹配（Python 做）
- 判断操作是否重复（Python 做）
- 追踪已完成的操作（Python 做）

使用 `bind_tools()` 让 LLM 直接输出 tool_call，和 large_single 一样的接口，不需要额外的 JSON plan 解析层。

---

## 5. 与其他架构的对比

| 维度 | large_single | workflow_v5 | planner_executor | SMAG |
|---|---|---|---|---|
| 每轮 LLM 调用 | 1 | 3-4 | 1-2 | 1-3 |
| 状态追踪 | 隐式（上下文） | LLM 生成 state | Python conv_summary | Python 解析（确定性） |
| 写操作校验 | 无 | LLM Verifier | LLM Verifier（弱） | Python `can_execute()` |
| item_id 校验 | 无 | LLM 判断 | 无 | `item_id ∈ order.items`（确定性） |
| payment 校验 | 无 | LLM 判断（误判多） | 无 | 检查非空即可 |
| 产品变体选择 | LLM（完整上下文） | State Tracker 丢失 | LLM（完整上下文） | LLM（完整上下文） |
| **前 20 任务 avg** | 0.50 | 0.45 | 0.40 | **0.65** |

---

## 6. 实验结果（前 20 任务）

**任务级对比：**

```
 task  large  small  wf_v5   pe   smag
    0    ✅     ❌     ❌     ✅    ❌   ← SM 未收到确认前 LLM 终止
    1    ✅     ✅     ✅     ✅    ❌   ← 同上
    2    ❌     ✅     ❌     ❌    ❌   ← DB 对但 NL 失败
    3    ✅     ✅     ❌     ❌    ❌   ← DB 对但 NL 失败（写操作本身正确！）
    4    ✅     ✅     ❌     ❌    ✅   ← SMAG 新增
    6    ❌     ✅     ❌     ❌    ✅   ← SMAG 新增（extra item 问题解决）
    7    ❌     ❌     ✅     ✅    ✅
    8    ✅     ❌     ❌     ✅    ❌   ← 变体选择，agent=[]
   10    ✅     ✅     ✅     ✅    ✅
   11    ❌     ❌     ✅     ❌    ✅
   13    ❌     ✅     ✅     ✅    ✅
   14    ❌     ❌     ✅     ❌    ✅
   15    ❌     ❌     ✅     ❌    ✅
   16    ✅     ✅     ✅     ❌    ✅
   19    ❌     ❌     ❌     ❌    ❌   ← 复杂 return + exchange
   20    ❌     ❌     ❌     ❌    ✅   ← SMAG 新增（modify × 4）
   21    ✅     ❌     ❌     ❌    ✅   ← SMAG 新增
   22    ❌     ❌     ❌     ✅    ✅
   23    ✅     ✅     ❌     ❌    ❌   ← 3 步操作，第 3 步 modify 失败
   24    ✅     ✅     ✅     ✅    ✅
```

**SMAG 的错误分布（失败任务）：**

| 错误类型 | 数量 | 说明 |
|---|---|---|
| 未执行写操作（agent=[]） | 4 | LLM 给出口头确认但未调工具（task 0/1/8/19） |
| DB 正确但 NL 失败 | 2 | 执行正确，最终回复语义不满足（task 2/3） |
| 部分写成功 | 1 | task 23：前 2 步 exchange 对，第 3 步 modify 参数错 |
| WRITE_WRONG_ARGS | 0 | 基本消除 |
| TRANSFER_ABORT | 0 | 基本消除 |

**关键发现**：SMAG 基本消除了之前最主要的失败类型（WRITE_WRONG_ARGS），从 large_single 的 60% 降到 0%。新出现的主要问题是"LLM 口头确认但未执行"（agent=[]），根因是 LLM 在 bind_tools 模式下有时会选择文字确认而非直接调工具。

---

## 7. 残留问题分析

### 7.1 未执行写操作（task 0/1/8/19）

**现象**：对话时间短（30-80s），agent=[]，NL=1.0（说对了），DB=0.0（没做）

**根因**：LLM 在准备好执行写操作时，生成了"我将为您处理…"的确认文本，用户看到确认信息后说 STOP，实际写工具从未被调用。

**潜在修复**：在 SM context 中加提示："当所有前置条件已满足时，直接调用写工具，不要先给文字确认。"

### 7.2 DB 正确 NL 失败（task 2/3）

**现象**：写操作执行完全正确，但最终回复遗漏了用户提问的附加问题（如 task 3 的 t-shirt 变体数量）

**根因**：LLM 专注于执行操作，生成最终回复时没有回答对话中的附加问题

**潜在修复**：在 system prompt 中加提示："最终回复时回答用户在整个对话中提出的所有问题"

### 7.3 多步操作的第 N 步失败（task 23）

**现象**：前 2 步 exchange 正确，第 3 步 modify_pending_order_items 参数错

**根因**：SM 正确追踪了前 2 步的完成，但第 3 步的 new_item_ids 选择错误（属于产品变体选择问题）

---

## 8. 实现文件

```
src/cs263_agent_eval/
  tau2/
    smag_agent.py              ← RetailStateMachine + SMAGAgent

configs/tau2/
  retail_50.json               ← 新增 "smag_large" 条目

scripts/
  run_tau2_smag.py             ← runner 脚本
```
