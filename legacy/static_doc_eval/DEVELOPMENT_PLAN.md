# 详细开发计划

## 0. 基本约束

- 只复用旧项目里的模型接口调用方式：
  `ChatVertexAI(model_name=..., project=PROJECT_ID, location=..., temperature=0)`
  和 `ChatOllama(model=..., temperature=0)`。
- 不复用旧项目的 benchmark 数据、source 文档、任务文本、gold label、prompt 或实验结果。
- 新 benchmark 数据将在本项目中重新生成，基于新的 schema 和新的半合成任务世界。
- agent 和 workflow 统一使用 LangChain / LangGraph 实现。

## 1. 研究目标

本项目比较：在 hard 多步工作流任务上，显式 agentic workflow 是否能帮助本地小模型缩小与较强闭源模型 single-agent 的差距。

对比系统：

1. `large_single`：使用 Google Cloud Vertex Gemini 2.5 Flash 或 Gemini 2.0 Flash 的单智能体。
2. `small_single`：使用本地 Ollama Gemma 4B 级别模型的单智能体。
3. `small_agentic_workflow`：使用本地 Ollama Gemma，并通过 Planner、Collector、Reasoner、Verifier 组成 LangGraph workflow。

主要预期：

- `large_single` 应该明显强于 `small_single`。
- 10 个 hard task 需要足够难，不能让 single-agent 轻松接近满分。
- `small_agentic_workflow` 预计通过规划、状态拆分、证据整合和显式验证，相比 `small_single` 有提升。

## 2. 框架选择

LangChain：

- single-agent baseline 使用 `create_agent(model=..., tools=..., system_prompt=...)`。
- 最终输出统一为结构化 JSON，并用确定性规则评分。
- 三个系统使用相同 tool surface 和相同最终 output schema。

LangGraph：

- 使用 `StateGraph` 建模显式共享状态。
- 主 workflow：
  `Planner -> Collector -> Reasoner -> Verifier -> 可选 Collector retry -> Final`。
- 主实验中 `MAX_WORKFLOW_REVISIONS=1`，避免 workflow 因为更多 retry budget 获得不公平优势。

模型适配：

- Vertex Gemini adapter 放在 `src/cs263_agent_eval/model_factory.py`。
- Ollama adapter 也放在同一个文件。
- 模型名通过 `.env` 配置：
  `LARGE_VERTEX_MODEL`、`ALTERNATE_VERTEX_MODEL`、`SMALL_OLLAMA_MODEL`。
- LangChain 当前 Google 文档更推荐新 Gemini 代码使用统一 Google package，但本项目保留 `ChatVertexAI`，因为旧项目已经在当前环境中验证过这个 Vertex 接口调用方式。

## 3. 项目结构

当前已初始化结构：

```text
pyproject.toml
README.md
DEVELOPMENT_PLAN.md
src/cs263_agent_eval/
  config.py
  model_factory.py
  schemas.py
  agents/single_agent.py
  workflows/small_agentic_workflow.py
  tools/local_tools.py
  benchmark/generator.py
  eval/scoring.py
tests/test_scoring.py
```

计划生成的数据与结果目录：

```text
data/generated/hard_v1/
  tasks.jsonl
  sources/<task_id>/
outputs/runs/
outputs/reports/
```

## 4. Benchmark 设计

采用半合成 benchmark：

1. 程序化定义 hidden structured truth。
2. 将 hidden truth 渲染成多种 source：邮件文本、政策文档、CSV 表格、发票式文本、HTML 片段、ticket log、JSON API record 等。
3. 加入 distractor、过期记录、政策例外、冲突更新等难点。
4. gold output 从 hidden truth 程序生成，不使用 LLM 输出作为标准答案。
5. 使用确定性代码评分。

每个 hard task 应满足：

- 4-6 个 source。
- 正确完成至少需要 3 次 tool call。
- 至少包含一个冲突、覆盖规则、例外条款或 distractor。
- 至少包含一个计算或多条件判断。
- JSON 输出包含 4-8 个字段。
- 关键字段需要证据支持。

## 5. 10 个 Hard Task 蓝图

以下只是任务蓝图。具体 source 内容、数值和 gold label 必须在本项目中重新生成。

| ID | 任务主题 | Sources | Gold Fields | 难点机制 |
| --- | --- | --- | --- | --- |
| H01 | 报销核对 | 报销邮件、receipt 文本、差旅政策、财务 CSV、审批备注 | reimbursable_total, denied_items, policy_exceptions, approval_required | receipt 有过期条目，per-diem cap，例外审批覆盖默认规则 |
| H02 | 供应商合同续约决策 | 合同摘录、用量 CSV、价格表、amendment 邮件、SLA | recommended_plan, projected_cost, savings, renewal_deadline, risk_flags | 阶梯价格叠加 amendment 覆盖基础合同 |
| H03 | 事故 SLA root-cause 总结 | alert log、ticket timeline、SLA 文档、客户等级表、status page note | breached_sla, breach_minutes, impacted_customers, credit_due, evidence_ids | 时间戳跨时区，且不同客户等级 SLA 不同 |
| H04 | 库存补货计划 | 库存 CSV、销售预测、供应商 lead-time 表、安全库存政策、pending PO 列表 | reorder_skus, order_quantities, stockout_risk, earliest_recovery_date | pending orders 只能部分覆盖需求，不同 SKU lead time 不同 |
| H05 | 活动运营方案 | 场地表、餐饮报价、无障碍政策、活动邮件、staffing rules | feasible_venue, total_cost, staffing_count, unmet_constraints, next_action | 容量、无障碍、AV、预算约束互相冲突 |
| H06 | 学位审核 | transcript CSV、培养方案规则、transfer-credit note、petition 邮件、term calendar | graduation_eligible, missing_requirements, counted_units, petition_needed, deadline | 课程替代、transfer cap、residency 要求相互作用 |
| H07 | Grant budget 合规检查 | budget 表、grant rules、purchase list、PI 邮件、institutional addendum | allowable_costs, disallowed_costs, remaining_budget, approval_path | sponsor rule 与机构 addendum 冲突 |
| H08 | 招聘 shortlist 综合 | applicant 表、面试记录、岗位 rubric、利益冲突说明、availability 邮件 | shortlist, excluded_candidates, score_breakdown, interview_schedule | rubric 加权、利益冲突排除、时间可用性同时约束 |
| H09 | 研究证据抽取 | 生成的 abstracts、results tables、纳入标准、reviewer note、erratum | included_studies, excluded_studies, aggregate_metric, caveats | erratum 修改一个结果，纳入标准需要多步判断 |
| H10 | 财务月结 variance 分析 | ledger CSV、budget 表、correction 邮件、会计政策、部门映射 | adjusted_variance, variance_drivers, reclassifications, materiality_flag | reclassification 和 accrual correction 改变最终 variance |

任务校准目标：

- 如果 `large_single` 首次运行几乎满分，则任务太简单，需要提高难度。
- 如果所有系统都失败，通常说明任务信息不足或要求不清，需要重写。
- 优先保留这样的任务：`large_single` 通常高于 `small_single`，但 `large_single` 也不稳定或存在局部错误；`small_single` 常见失败点是 planning、证据整合、冲突处理或计算。

## 6. Tool Surface

先使用受控本地工具集合：

- `list_sources()`：列出当前任务可用 source IDs。
- `read_source(source_id)`：读取一个生成的 source。
- `run_calculation(expression)`：确定性算术工具。

后续如果需要，可以增加 typed wrappers：

- `read_csv(source_id)`。
- `read_policy(source_id)`。
- `query_record(record_id)`。
- `search_sources(query)`。

公平性原则：

- 三个系统拿到相同工具。
- workflow 可以在节点之间传递结构化中间状态。
- workflow 不能拿到 hidden gold data，也不能拿到比 single-agent 更多的特权 source ID。

## 7. Agent 实现

### 7.1 Large Single Agent

- 默认模型：Vertex Gemini 2.5 Flash。
- 备选模型：Vertex Gemini 2.0 Flash。如果 2.5 Flash 太强或不可用，则切换到 2.0。
- 使用 LangChain `create_agent`。
- prompt 形状与 small single agent 保持一致。
- temperature 设为 0。
- 最大步数由 `MAX_AGENT_STEPS` 控制。

### 7.2 Small Single Agent

- 模型：本地 Ollama Gemma 4B 级别模型。
- 使用与 large single 相同的 `create_agent` harness、相同工具、相同输出 schema、相同步数限制。
- 这是主要弱 baseline。

### 7.3 Small Agentic Workflow

LangGraph state：

- `task`
- `plan`
- `collected_evidence`
- `draft_answer`
- `verifier_feedback`
- `revision_count`
- `final_answer`

节点职责：

- Planner：拆解任务，列出 required fields、source hypotheses、computations 和 conditions to check。
- Collector：根据 plan 调用工具收集证据。
- Reasoner：基于 evidence 推导每个输出字段，并记录简短 derivation。
- Verifier：检查字段覆盖、证据支持、矛盾、算术和 schema。
- Optional retry：如果 Verifier 找到具体缺失证据或矛盾，最多进行一次 targeted collection/reasoning。

## 8. Evaluation 方案

主要指标：

- Task success rate：所有关键字段正确才算成功。
- Field accuracy：exact / numeric / set 字段的平均正确率。
- Evidence accuracy：引用 source 是否真的支持答案。
- Tool coverage：是否调用了完成任务所需的 source/tool 类型。
- Latency。
- Vertex 运行的估算 cost。
- Step count / tool call count。

评分规则：

- Exact fields：标准化后精确匹配。
- Numeric fields：按字段配置绝对误差或百分比误差。
- Set fields：计算 precision、recall、F1。
- Evidence fields：source IDs 必须能支持对应字段。
- Task success：所有 critical fields 通过才为 1。

实验矩阵：

```text
10 hard tasks x 3 systems = 30 main runs
可选：如果小模型方差较大，每个 system 重复 3 次
可选消融：
  small_workflow_no_verifier
  small_workflow_no_planner
  small_single_with_verifier
```

## 9. Baseline 驱动的任务构建

任务构建阶段可以使用 single-agent baseline 做难度校准，但不能把 baseline 输出当作数据来源。

流程：

1. 基于 10 个蓝图生成 20-30 个候选 hard tasks。
2. 跑 `large_single` 和 `small_single`。
3. 检查确定性分数与失败模式。
4. 保留 10 个满足以下条件的任务：
   - gold label 明确；
   - 至少一个 single-agent 系统在重要字段上失败；
   - `large_single` 通常高于 `small_single`；
   - 难度来自推理和证据整合，而不是信息缺失。
5. 冻结 `hard_v1`，之后不能再根据 workflow 结果反向调任务。

## 10. 实现里程碑

### Milestone A：基础设施

- 完成 uv 依赖管理。
- 确认 Vertex Gemini 连接。
- 确认 Ollama Gemma 连接。
- 增加单任务、单系统 runner CLI。

### Milestone B：Benchmark Generator

- 为 10 个蓝图实现 hidden-state generator。
- 将 hidden state 渲染成多格式 source。
- 生成 `tasks.jsonl`，包含 gold output 和 evaluation criteria。
- 增加验证测试，确保 gold output 能从 sources 推导出来。

### Milestone C：Agents

- 实现 `large_single` 和 `small_single`。
- 增加 JSON 提取和 schema validation。
- 记录 tool calls、latency 和 errors。

### Milestone D：Workflow

- 将当前 placeholder LangGraph nodes 替换为模型驱动的 Planner、Collector、Reasoner、Verifier。
- 增加一次 targeted retry path。
- 保存中间状态，方便后续 failure analysis。

### Milestone E：Evaluation

- 实现 exact / numeric / set / evidence scoring。
- 增加 experiment runner。
- 按 task 和 system 生成 summary tables。
- 增加 failure-mode 标签，例如 planning miss、wrong source、arithmetic error、conflict not resolved、schema error、unsupported evidence。

### Milestone F：Report

- 报告 aggregate scores。
- 报告 per-task breakdown。
- 比较 cost 和 latency。
- 分析 workflow decomposition 在哪些任务上有效，哪些任务上无效。

## 11. 近期下一步

1. 在允许下载依赖后运行 `uv sync`。
2. 确认本地 Ollama 已 pull 目标 Gemma 模型后运行 `uv run check-models`。
3. 优先实现 H01-H03 的 task generator。
4. 实现主 experiment runner。
5. 用 `large_single` 和 `small_single` 校准候选任务难度。
