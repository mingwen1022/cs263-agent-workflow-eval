# Benchmark 任务设计说明

> 本文档描述 CS263 Agent 评测 Benchmark 中 Hard 和 Medium 两类多文档工作流任务的构建方法论。

---

## 1. 设计目标

每个任务必须满足：

1. **要求多源推理** —— 没有任何单一文件能完整回答任务，模型必须跨文件综合信息。
2. **确定性且可验证** —— Gold Answer 可从源文件中唯一推导，不存在歧义。
3. **不包含答案提示** —— 源数据中不得有直接暴露答案的列或字段（例如 `eligible = true/false`）。
4. **模拟真实企业工作流** —— 任务来自可识别的业务场景：SLA 审查、费用报销、供应商续约、薪资更正等。
5. **包含噪音和干扰项** —— 源文件中包含看似合理但实际超出范围的行和文档。

---

## 2. 任务结构

### 2.1 任务 JSON Schema

```json
{
  "task_id": "hard_<domain>_<id>",
  "task_family": "multi_app_workflow",
  "difficulty": "hard" | "medium",
  "instruction": "<原文传给 agent 的任务指令>",
  "allowed_tools": ["list_sources", "read_csv", ...],
  "source_manifest": "sources/<task_id>/source_manifest.json",
  "gold_output": { "<字段>": <值>, ... },
  "evaluation_criteria": {
    "exact_fields": [...],
    "numeric_tolerances": { "<字段>": 0.01, ... },
    "set_fields": [...],
    "set_aliases": { "<字段>": { "<规范标签>": ["别名1", ...] } },
    "scoring_notes": "..."
  }
}
```

### 2.2 源文件

每个任务有 3–8 个混合格式的源文件：

| 格式 | 典型内容 |
|------|---------|
| CSV | 事务数据：费用明细、事故日志、发票行项、客户分级 |
| Markdown | 政策、合同、SLA 规则、资格标准 |
| TXT | 审批备忘录、邮件背景、更正说明 |
| PDF | 数据包摘要（少量使用，增加格式多样性） |
| DOCX | 审批文件、运营备注 |

---

## 3. 反提示原则

最关键的设计规则：**源数据中不得包含答案键（answer keys）**。

### 3.1 禁止模式

| 模式 | 禁止原因 | 正确替代方案 |
|------|---------|------------|
| `qualifying_alert = true/false` 列 | 直接告知使用哪条告警 | 删除该列；模型必须从环境/描述字段推断 |
| `eligible_for_credit = true/false` 列 | 直接告知谁有资格获得信用额度 | 删除；模型必须交叉比对分级 + 状态 + 政策 |
| `include_in_renewal = true/false` 列 | 直接告知哪些行计入续约 | 删除；模型必须应用合同范围规则 |
| `notes: "Noise row from prior trip"` | 明确标注噪音行 | 使用中性注释或不加注释 |
| `notes: "Start clock here"` | 直接指出 SLA 计时起点 | 删除；模型必须读取环境字段 + 事故政策 |

### 3.2 允许的上下文提示

CSV 文件中的 notes 列仅在以下情况保留：说明*为什么*产生这条记录（不直接给出处理决策）。

**当前实例（PC-08 更正批次）：**

```
notes: "Rate miscalculation identified in payroll audit"   ← 说明原因，可保留
notes: "Duplicate of C1"                                   ← 事实标注，可保留
notes: "Different employee correction included in batch"   ← 事实背景，可保留
```

模型仍需读政策文件才能知道如何处理这些记录；仅凭 notes 无法直接回答任务。

**禁止的 notes 类型：**
- 直接告知包含 / 排除结论（如 `"Noise row"`、`"Start clock here"`）
- 直接给出资格判断（如 `"Sandbox seats are not billable"`、`"Gold but not affected"`）

**判断标准**：如果模型只读 notes 列（不读政策文件），能否直接回答任务的关键字段？能的话，notes 提示过多。

### 3.3 无效干扰工具

`allowed_tools` 中包含几个返回无用数据的工具：
`lookup_vendor_status`、`search_employee_directory`、`check_public_calendar`、`estimate_shipping_cost`。
这些工具用于测试 Agent 是否会浪费工具调用预算在无关操作上。

---

## 4. 输出字段设计

### 4.1 字段类型选择

**Exact 字段**（数值或布尔）：答案明确且可直接计算时使用。
- 浮点字段须有 `numeric_tolerance`（默认 0.01），处理浮点舍入误差。
- 字符串 exact 字段应尽量避免（改用 set 字段），因为模型对同一角色会用不同表述。

**Set 字段**（数组）：用于枚举需要推理的项目。
- 每个预期项目生成两类检查：
  - `contains`：该项是否存在于模型答案中？
  - `no_unexpected_items`：模型是否只包含有证据支撑的项？
- `no_unexpected_items` 检查对过度包含的答案扣分。

### 4.2 别名（Alias）设计

别名涵盖表述正确但措辞不同的合理 label 变体。设计原则：

- **别名应覆盖模型的自然输出** —— 先跑试验评测，收集模型输出，为所有语义正确的变体添加别名。
- **别名不能为错误推理背书** —— 如果模型输出了错误项目，不能为了提分而把错误项加为别名。
- **别名经过标准化处理**（`_normalize_label()`）：全小写，非字母数字字符替换为下划线，连续下划线合并。

**不同字段类型的别名覆盖宽度：**

| 字段类型 | 别名宽度 | 理由 |
|---------|---------|------|
| excluded_rows / excluded_alerts | 宽 —— 同时覆盖行 ID 和描述 | 模型可能用 "n1" 或 "prior_invoice_line" 表示同一行 |
| denied_items / risk_flags | 中 —— 覆盖常见改写 | 模型对同一政策违规使用不同的类别名称 |
| 客户名 / 供应商名 | 窄 —— 规范名 + 明显缩写 | 专有名词，非类别 |

### 4.3 字段语义：excluded vs. denied 的区别

两类字段是小模型最常混淆的：

- **excluded_rows / excluded_alerts / excluded_lines**：完全**不属于**此案例的行（错误的 claim ID、不同实体、先前批次、已作废条目）。其金额不得出现在任何计算中。

- **denied_items / denied_corrections / dispute_items**：**属于**此案例但被政策**拒绝**的项目（餐费中的酒精、上下班通勤、高级 WiFi）。其金额从总额中专门扣除。

这两个概念必须分别放在不同字段，绝不重叠。混淆两者是小模型常见的推理失败模式。

---

## 5. 噪音项设计

噪音项测试 Agent 是否能正确界定分析范围。

### 5.1 噪音类型

| 噪音类型 | 示例 | 测试什么能力 |
|---------|------|------------|
| 错误实体 | 同一批次导出中另一员工的更正记录 | Agent 必须按员工 ID 过滤 |
| 错误时期 | Q1 2026 报告中的 Q4 2025 数据 | Agent 必须应用时间范围约束 |
| 错误发票 | INV-58 审查中混入 INV-57 行项 | Agent 必须按发票号匹配 |
| 先前批次 | MP-08 批次中混入 MP-07 条目 | Agent 必须检查批次 ID |
| Staging 事件 | 生产事故日志中的 Staging 告警 | Agent 必须读取 environment 字段 |
| 不同部门 | Engineering 预算申请中混入 Finance 行 | Agent 必须按部门范围过滤 |

### 5.2 噪音数量校准

- **Hard 任务**：3–5 个噪音项；噪音项需要推理才能识别（例如：不同员工 + 正确更正类型，看起来非常合理）。
- **Medium 任务**：1–2 个噪音项；噪音相对容易发现（错误 claim ID、不同部门）。

噪音项在源文件中**不得被标注为"噪音"**，识别它们本身就是任务的一部分。

---

## 6. 数值字段设计

### 6.1 计算复杂度对照

| 难度 | 计算模式 | 示例 |
|------|---------|------|
| 简单 | 直接查找（单一来源） | 读取基础费率 |
| Medium | 1–2 步推导 | 小时费率 × 工时 = 总额 |
| Hard | 多步骤 + 修正 + 上限 | 基础费 + 超额 − 修正，按每日上限截断 |

### 6.2 多步骤计算模式

**超额计费模式**（需要跨文件 JOIN）：
```
实际用量（来自使用量 CSV） - 包含用量（来自定价 CSV） = 超额用量
超额费用 = 超额用量 × 单价（来自定价 CSV）
总费用 = 基础费 + 超额费用
```
这是最难的模式，因为模型需要关联两个不同的源文件。小模型（4B 参数）在没有明确指导的情况下几乎总会失败。

**上限模式**（每日/每项限额）：
```
原始总额 = sum(合格项目)
上限后金额 = min(原始总额, 上限)
拒绝金额 = 原始总额 - 上限后金额
```

**修正模式**（收据修正）：
```
修正后金额 = 提交金额 - 不可报销部分
上限适用于：修正后金额（不是原始金额）
```

这些模式经常组合出现，正是 Hard 任务难的核心所在。

---

## 7. 难度校准

### 7.1 目标精度范围

| 难度 | large_single | small_single | 差距 |
|------|-------------|-------------|------|
| 简单 | ~100% | ~100% | ~0% |
| **Medium** | **~87–90%** | **~64–70%** | **~20–25%** |
| **Hard** | **~88–95%** | **~60–65%** | **~28–35%** |

### 7.2 校准流程

1. **设计任务和 Gold Answer** —— 手动追踪每个源文件，验证 Gold 正确。
2. **Gold 测试** —— `score_prediction(task, task.gold_output)` 必须返回 100%。这能发现 schema 不匹配和别名缺失。
3. **试验评测** —— 在 `large_single` 和 `small_single` 上测试。
4. **识别别名缺口** —— 收集每个字段的模型输出，为表述正确但 label 不同的变体添加别名。
5. **识别结构问题** —— 如果两个模型得分相同（差距 0%），通常意味着：
   a. 任务太简单（两个都得 100%），或
   b. 两个模型在相同的别名缺口上都失败。
6. **调整任务内容或别名** —— 添加噪音项增加难度；扩展别名修复假阴性。
7. **重新运行并迭代** —— 重复步骤 3–6 直到达到目标范围。

### 7.3 校准过程中的反作弊规则

- 别名只能为**推理正确**的 label 添加 —— 模型用不同表述表达了正确答案，应该得分。
- 别名**不能**为推理错误的 label 添加 —— 即使很多模型都输出了错误 label，评分也必须扣分。
- 任务指令和源文件内容**不能**为迎合特定模型的输出习惯而修改 —— 只能扩展别名，不能编码答案。
- Workflow Prompt 中的数值示例必须使用**通用占位符变量**，不能使用任何特定任务的真实数值。

---

## 8. Hard 任务概况

10 个任务，覆盖 6 个企业领域：

| 任务 | 领域 | 源文件 | 检查数 | 核心难点 |
|------|------|--------|--------|---------|
| hard_incident_sla_ir42 | 运营/SLA | 7 | 22 | 4维客户资格检查，告警排除推理 |
| hard_initial_tr19_reimbursement | 财务/报销 | 8 | 20 | 两次收据修正、酒店上限 + 研讨会上限、8 个拒绝项 |
| hard_vendor_renewal_cb27 | 采购 | 8 | 16 | 跨表费用计算（基础费 + 席位超额 + 存储超额） |
| hard_purchase_order_po91 | 采购 | 5 | 15 | 政策类别区分（support vs support_upgrade） |
| hard_conference_expense_ce44 | 财务/报销 | 4 | 16 | 赞助商抵扣、超上限会议注册费 |
| hard_invoice_dispute_inv58 | 应付/财务 | 5 | 18 | 发票 vs PO 三维不匹配（数量 + 费率 + 未授权收费） |
| hard_access_review_ar29 | IT 安全 | 4 | 18 | 历史违规记录影响当前 PII 访问决策 |
| hard_sla_compliance_sc11 | 客户成功 | 4 | 16 | 月度信用上限跨多个事故累加 |
| hard_budget_variance_bv22 | 财务/预算 | 4 | 23 | 各部门 5% 阈值判断，跨部门转账规则 |
| hard_payroll_correction_pc08 | HR/薪资 | 5 | 15 | 历史批次交叉查验，佣金类型排除 |

---

## 9. Medium 任务概况

11 个任务，覆盖 8 个领域，设计为 Hard 模式的简化版本：

| 任务 | 领域 | 源文件 | 检查数 | 核心难点 |
|------|------|--------|--------|---------|
| medium_incident_sla_mi01 | 运营/SLA | 3 | 14 | 3 客户分级检查 + Staging vs 生产告警识别 |
| medium_expense_claim_me07 | 财务/报销 | 2 | 8 | 每日餐费上限 + 通勤排除 + WiFi 拒绝 |
| medium_vendor_selection_mv14 | 采购 | 2 | 9 | 3 条件过滤（SLA、地区、合同期限） |
| medium_access_request_ma03 | IT 安全 | 2 | 7 | 基于角色的权限矩阵（3 条申请，1 条错误员工） |
| medium_invoice_review_mi22 | 应付/财务 | 2 | 8 | PO 匹配 + 未授权附加费 |
| medium_leave_request_ml09 | HR | 3 | 7 | 天数阈值 → 审批类型 + 余额检查 |
| medium_budget_request_mb16 | 财务/预算 | 2 | 7 | 类别审批分级 + 2 个噪音行 |
| medium_payroll_review_mp12 | HR/薪资 | 2 | 10 | 佣金类型排除 + 错误员工噪音 |
| medium_support_sla_ms08 | 客户成功 | 2 | 9 | P1/P2/P3 响应时间 SLA 检查 |
| medium_contract_amendment_mc19 | 采购 | 2 | 9 | 经理 vs VP 审批层级，覆盖 4 种修订类型 |
| medium_onboarding_check_mo05 | HR | 2 | 10 | 入职前必须完成 vs 入职 5 天内必须完成的任务拆分 |

---

## 10. 观测到的模型失败模式

### 10.1 小模型（Gemma 4-E4B）的系统性失败

| 失败模式 | 示例 | 根本原因 |
|---------|------|---------|
| 跨文档 JOIN | CB-27：读到基础费 1200 但漏算席位超额 | 无法可靠地关联两个 CSV 文件中的值 |
| Set 字段不完整 | TR-19：列出通勤、WiFi、礼品，但漏掉 meal_cap_excess | 没有系统地对每个项目逐条应用政策规则 |
| 政策分级误用 | IR-42：漏掉 Silver 和 Bronze 分级的排除 | 没有对每位客户验证每条标准 |
| Label 格式偏差 | 输出 "overtime_c1" 而非 "c1_overtime" | 复合标签的构建方式与预期不同 |
| 不应用上限的算术 | 直接对原始金额求和，不应用每日/每项上限 | 多步骤计算中跳过修正/上限步骤 |

### 10.2 大模型（Gemini 2.5 Flash）的系统性失败

| 失败模式 | 示例 | 表现 |
|---------|------|------|
| Set 字段过度包含 | CB-27：列出 17 个 ignored_inputs 而非 6 个 | `no_unexpected_items` 检查失败 |
| 遗漏 Risk Flags | CB-27：漏掉 discount_deadline 和 standard_sla_gap | Risk flags 需要综合 2+ 个来源 |
| 复杂性下的算术错误 | TR-19：计算税后净额而非税前总更正额 | 在认知负载下误解字段语义 |
| 冗余 Label 拼接 | IR-42：输出 "s1_staging_alert" 而非 "s1" | 在 Prompt 中提供过于详细的格式指导时出现 |

### 10.3 Workflow 失败模式（对比 single small agent）

多阶段 Workflow（Planner → Collector → Reasoner → Verifier）在 Hard 任务上提升 +12.6%，但在 Medium/Easy 任务上可能损失 -6.4%。

| Workflow 失败模式 | 出现条件 |
|-----------------|---------|
| Collector 摘要不完整 | 含 6+ 个源文件的复杂任务；模型在读完所有源前停止 |
| Reasoner Label 漂移 | 较简单任务中，单次 Pass 已经准确；多阶段引入不同措辞 |
| Verifier 误批准 | Verifier 无法独立重推导跨文档 JOIN |
| Draft 答案为空 | 极复杂的数值推理；Reasoner 无法输出可解析的 JSON |

**核心发现**：Workflow 架构存在任务复杂度阈值。低于阈值时，单次 Pass Agent 更可靠；高于阈值时，系统性证据收集和验证机制带来明显收益。

---

## 11. Workflow Prompt 设计约束

四个节点的系统 Prompt（Planner、Collector、Reasoner、Verifier）必须满足：

1. **领域无关** —— 不得引用特定任务类型、业务领域或字段名称
2. **任务无关** —— 不得包含任何数值、实体名称或其他任务特定内容
3. **不嵌入答案** —— Prompt 中的计算示例不能使用任何 Benchmark 任务中的真实数值
4. **通用性构建** —— 同一套 4 个 Prompt 用于所有 10 个 Hard + 11 个 Medium 任务

违反上述约束将使对比失效：如果 Workflow Prompt 包含任务特定提示，Workflow 的优势不能归因于架构，而是信息泄露。

判断标准：同一套 4 个 Prompt 能否直接应用于全新任务领域（如医疗理赔、法律文件审查）并仍提供相同的结构性收益？当前 Prompt 的设计目标即通过这一测试。
