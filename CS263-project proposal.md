# 研究计划（更新版）

## 项目题目

**Evaluating Single- and Multi-Agent Architectures for Multi-Step Workflows**

可选中文表述：

- 评估单智能体与多智能体架构在多步工作流中的效果
    
- 评估单智能体与多智能体架构在文档与多应用多步工作流中的效果
    

## 1. 项目背景

大语言模型已经能够完成一定程度的工具调用与任务自动化，但在需要多步信息获取、跨 source 协调、证据整合和结果验证的工作流任务中，仍然容易出现规划不清、工具选择不稳、证据不足或最终输出不一致等问题。因此，本项目首先关注的是：单智能体与多智能体架构在这类复杂应用中的局限性分别体现在哪些任务、哪些难度和哪些失败模式上；在此基础上，再进一步考察多智能体分工与显式验证机制是否能够缓解这些局限。

## 2. 核心研究问题

1. 在多步工作流任务中，多智能体架构是否优于更简单的方法？
    
2. 这种提升主要来自哪里：角色分工，还是最终验证？
    
3. 不同任务类型、不同难度下，复杂架构是否都值得，还是只在更长、更难的工作流中才体现优势？
    
4. 小模型在多智能体架构下，是否能够在这些任务上接近强模型单智能体架构的表现，并呈现更好的性能—成本权衡？
    

## 3. Benchmark 任务类型

我们计划构建一个小型 benchmark，包含两类任务：

### A. Document-centered workflows

典型流程：读取文档/PDF/表格/网页内容 → 找证据 → 整合信息 → 输出结构化答案。

这类任务主要关注：

- 多文档证据整合
    
- 表格/文本信息抽取
    
- 简单计算或比对
    
- 基于证据的最终回答
    

### B. General multi-app workflows

典型流程：查看邮件或任务描述 → 查文件/文档/记录/API → 整合信息 → 生成回复或行动建议。

这类任务主要关注：

- 跨 source 协调
    
- 多步任务执行
    
- 中间状态维护
    
- 最终输出生成
    

说明：网页搜索、页面打开等能力不再单独作为第三类任务，而是作为 source 或工具融入上述两类任务中。

## 4. 任务难度设计

每一类任务再分为三档：

- **Easy**：1–2 个 source，1–2 个工具，任务较短
    
- **Medium**：2–3 个 source，需要信息整合或简单计算
    
- **Hard**：3 个以上 source / 工具，存在多步依赖、冲突信息、状态更新或更长链路
    

## 5. 数据构建思路

我们不会依赖开放互联网作为主实验环境，而是使用**半合成 benchmark**：

- 先定义结构化真值（hidden state）
    
- 再把真值渲染成网页、文档、邮件、API 返回等 source
    
- 最终标准答案由程序自动生成，而不是人工逐条填写
    

例如：

- document 任务的标准答案可以是表格数值、字段集合或证据支持的结论
    
- multi-app 任务的标准答案可以是最终 JSON、最终回复中的关键信息，或最终状态
    

少量更强的 LLM 可用于表面文本改写、样本扩充和网页/文档内容包装，但不会直接把 LLM 输出当作 gold label。

## 6. 统一数据结构

不同任务类型不需要完全相同的细节 schema，但会共享同一个顶层结构，方便统一跑实验。

统一外层字段包括：

- task_id
    
- task_type
    
- difficulty
    
- instruction
    
- available_tools
    
- sources
    
- gold_output
    
- evaluation_criteria
    

各任务类型内部再保留自己的 type-specific 字段。

## 7. 可调用工具

为了控制实验规模，我们计划使用一个小型通用工具箱，例如：

- `web_search(query)`
    
- `open_page(url_or_id)`
    
- `read_document(doc_id)`
    
- `run_python(code_or_expression)`
    
- `query_api(key_or_record_id)`
    

如任务需要，也可以加入轻量的邮件/文件读取工具，但不会一开始做过大的 live-tool 世界。

## 8. 模型选择

按照课程要求，我们计划选择 1–2 个模型进行评测。

当前更聚焦的做法是：

- **主实验模型**：选择一个较小的开源模型作为主要研究对象，例如 **Gemma 系列**（如工程实现受限，也可换为 Qwen 系列）
    
- **参考模型**：选择一个较强的闭源模型作为上限参考，例如 **Claude / OpenAI / Gemini** 中的一种
    

这样设计的目的不是做大规模模型横评，而是研究：

- 小模型在 single-agent 与 multi-agent 架构下差距有多大
    
- 小模型的 multi-agent 架构，能否接近强模型的 single-agent 表现
    
- 在接近性能的同时，是否具有更好的成本表现
    

## 9. 对比方法

本项目主要进行**架构对比**，并围绕“小模型 + 多智能体”这一主线展开。

### 9.1 小模型 Single-Agent

一个统一的 agent 负责完成全部步骤：

- 根据任务描述决定先查看哪些 source
    
- 自主选择工具（如读文档、查网页、查 API、运行简单计算）
    
- 根据中间结果决定下一步
    
- 最后一次性输出结构化答案
    

这里的关键点是：整个过程由**同一个 agent 决策体**完成，不做显式角色分工。

### 9.2 小模型 Single-Agent + Verifier

前半部分与 Single-Agent 相同，但在得到初始答案后增加一个独立 verifier：

- Single-Agent 先完成检索、推理和初步输出
    
- Verifier 检查输出是否满足格式要求、是否与证据一致
    
- 若不满足要求，Verifier 最多反馈 **1 次** 给前面的 agent 进行修正
    
- 修正后输出最终答案
    

因此，这个架构测的是：在不引入多智能体分工的前提下，单独加入验证回路是否能够提升表现。

### 9.3 小模型 Multi-Agent + Verifier（主方法）

主方法将任务拆分给多个通用角色节点：

- **Planner**：生成高层步骤或子目标
    
- **Retriever**：负责检索网页、文档、记录等信息
    
- **Reasoner**：整合检索结果并形成中间结论
    
- **Verifier**：检查最终输出是否满足格式和证据要求
    

执行流程为：

1. Planner 先给出高层步骤；
    
2. Retriever 根据步骤获取信息；
    
3. Reasoner 基于信息生成答案；
    
4. Verifier 检查答案；
    
5. 若不通过，Verifier 最多反馈 **1 次** 给前面的相关节点进行修正；
    
6. 输出最终结果。
    

这个架构的目标是测试：在已有 verifier 的基础上，显式角色分工是否还能带来额外收益。

### 9.4 强模型 Single-Agent（参考）

使用一个较强闭源模型运行 single-agent 架构，流程与小模型 Single-Agent 相同：

- 自主选择工具
    
- 自主进行多步检索与推理
    
- 最后输出结构化结果
    

其作用主要是作为性能参考上限，用于回答：小模型在 multi-agent 架构下，是否能够接近强模型 single-agent 的表现。

### 9.5 架构比较的核心逻辑

真正的核心对比包括：

- **小模型 Single-Agent vs 小模型 Single-Agent + Verifier**
    
    - 测试 verifier 本身是否有效
        
- **小模型 Single-Agent + Verifier vs 小模型 Multi-Agent + Verifier**
    
    - 测试在已有 verifier 的前提下，多智能体分工是否仍有额外收益
        
- **小模型 Multi-Agent + Verifier vs 强模型 Single-Agent**
    
    - 测试小模型通过更复杂架构，能否逼近强模型单智能体的能力
        

为了避免把框架层面的自动修正能力混入架构比较，所有主对比方法将统一使用：

- 相同的最终输出 schema
    
- **最多一次** final structured output 修正
    

也就是说，结构化输出只作为统一的输出约束，而不作为某一种架构的额外优势来源。

## 10. 主方法设计

主方法将使用一个图结构 workflow：

- **Planner**：生成高层步骤
    
- **Retriever**：负责检索网页/文档/记录等信息
    
- **Reasoner**：整合信息并生成中间结论
    
- **Verifier**：检查输出是否满足格式和证据要求
    

各节点原则上基于同一套大工具集合工作，主要通过职责分工和 graph routing 区分，而不是通过过强的人为 tool 切割制造优势。

实现上，LangChain / LangGraph 将作为统一的工程框架与编排层，而不是主要实验变量。也就是说，实验比较的重点是上层架构设计，而不是是否使用某个框架本身。

在主实验中，所有方法都共享相同的 final output schema 约束；只有 multi-agent 方法会额外维护节点间的结构化中间状态，这部分将作为其内部设计的一部分，并在消融实验中单独考察。

## 11. 消融实验

消融实验用于分析主方法中哪些模块真正起作用。计划包括：

- 去掉 verifier
    
- 去掉多智能体分工，改成单智能体
    
- 去掉结构化中间状态（如时间允许）
    
- 将 planner/retriever/reasoner 的职责边界弱化，观察明确分工是否真的有帮助
    

说明：

- 主实验中不会把“无限次结构化修正”作为默认设置，因为这会把 retry budget 混入架构效果。
    
- 所有方法统一最多一次 final output 修正，以保证公平性。
    
- 若时间充足，可在附加实验中再考察更宽松的 retry policy，但这不作为主线结论的一部分。
    

## 12. 评测指标

主要指标包括：

- 最终任务成功率
    
- 结构化字段准确率
    
- 证据/来源引用正确率（如适用）
    
- 平均步骤数
    
- token / cost
    
- latency
    

我们会分别报告：

- 不同任务类型上的结果
    
- 不同难度上的结果
    
- 不同架构上的结果
    

## 13. 实验目标

本项目的终极目标不只是证明主方法分数更高，而是回答：

1. 多智能体 + verifier 是否真的优于更简单的架构？
    
2. 提升主要来自角色分工还是验证机制？
    
3. 在什么任务类型、什么难度下，这种复杂架构才值得使用？
    
4. 小模型在 multi-agent 架构下，是否能够接近强模型 single-agent 的表现，并在成本上更有优势？
    

## 14. 预期贡献

1. 构建一个小型、可自动评测的多步工作流 benchmark；
    
2. 比较不同 agent 架构在 document-centered 与 multi-app 两类任务上的表现；
    
3. 分析多智能体分工与 verifier 分别带来的收益；
    
4. 探索小模型 multi-agent 架构是否能够接近强模型 single-agent 的能力；
    
5. 分析不同任务类型与难度下的性能—成本权衡。
    

## 15. 计划分工（待补充）

- 成员 A：数据生成与 benchmark 搭建
    
- 成员 B：baseline / single-agent 实现
    
- 成员 C：multi-agent workflow、ablation 与结果分析
    

## 16. 简要说明

这份版本主要用于 planning report，重点说明研究题目、任务设计和实验框架；后续 midterm report 再补 literature review、实验进展和更详细的技术细节。



# Project Title

**Evaluating Single- and Multi-Agent Architectures for Multi-Step Workflows**

## 1. Background

Large language models are increasingly capable of tool use and task automation, but they still struggle on workflow-style tasks that require multi-step information gathering, cross-source coordination, evidence integration, and output verification. In this project, we first study where the limitations of single-agent and multi-agent architectures appear in such complex applications: which task types, which difficulty levels, and which failure modes. Based on that analysis, we then examine whether multi-agent role decomposition and an explicit verifier can help mitigate these limitations.

## 2. Core Research Questions

1. On multi-step workflow tasks, do multi-agent architectures outperform simpler approaches?
    
2. If improvement exists, does it mainly come from role decomposition or from explicit verification?
    
3. Across task types and difficulty levels, when is a more complex architecture actually worthwhile?
    
4. Can a smaller model under a multi-agent architecture approach the performance of a stronger model under a single-agent architecture, while offering a better performance-cost tradeoff?
    

## 3. Benchmark Task Types

We plan to build a small benchmark with two task categories.

### A. Document-Centered Workflows

Typical pipeline: read documents / PDFs / tables / web content → find evidence → integrate information → output a structured answer.

These tasks focus on:

- multi-document evidence integration
    
- table/text information extraction
    
- simple calculation or comparison
    
- evidence-grounded final answers
    

### B. General Multi-App Workflows

Typical pipeline: inspect an email or task description → query files / documents / records / APIs → integrate information → generate a response or action recommendation.

These tasks focus on:

- cross-source coordination
    
- multi-step task execution
    
- intermediate state maintenance
    
- final response generation
    

Web search and page browsing are not treated as a separate benchmark category; instead, they are included as sources or tools within the two workflow types above.

## 4. Difficulty Design

Each task category will be divided into three difficulty levels:

- **Easy**: 1–2 sources, 1–2 tools, short task horizon
    
- **Medium**: 2–3 sources, requiring information integration or simple computation
    
- **Hard**: 3+ sources/tools, with longer horizons, state updates, conflicting information, or stronger multi-step dependencies
    

## 5. Data Construction

We will not rely on the live open web as the primary experimental environment. Instead, we will build a **semi-synthetic benchmark**:

- first define a structured hidden truth state,
    
- then render that truth into web pages, documents, emails, and API outputs,
    
- and finally generate the gold answer programmatically rather than annotating each example manually.
    

For example:

- document tasks may use table values, field sets, or evidence-supported conclusions as gold outputs;
    
- multi-app tasks may use a final JSON object, key information in a response draft, or a target end state.
    

A stronger LLM may be used only for surface-level rewriting, sample expansion, or packaging content into more natural pages/documents, but its outputs will not be used directly as gold labels.

## 6. Unified Data Schema

Different task types do not need identical fine-grained schemas, but they will share a common top-level structure so that they can be evaluated under one framework.

Shared top-level fields include:

- `task_id`
    
- `task_type`
    
- `difficulty`
    
- `instruction`
    
- `available_tools`
    
- `sources`
    
- `gold_output`
    
- `evaluation_criteria`
    

Each task type may additionally contain its own type-specific payload.

## 7. Available Tools

To keep the project manageable, we plan to use a small general-purpose tool set such as:

- `web_search(query)`
    
- `open_page(url_or_id)`
    
- `read_document(doc_id)`
    
- `run_python(code_or_expression)`
    
- `query_api(key_or_record_id)`
    

If needed, lightweight email or file-reading tools may also be added, but we will avoid building a very large live-tool environment.

## 8. Model Selection

Following the course requirement, we plan to evaluate 1–2 models.

Our current focused setup is:

- **Main experimental model**: a smaller open model, such as the **Gemma** family (or Qwen if implementation constraints make it more practical)
    
- **Reference model**: a stronger closed model, such as one model from **OpenAI, Claude, or Gemini**
    

The point is not to conduct a broad model benchmark, but to study:

- how much a smaller model improves under single-agent vs multi-agent architectures,
    
- whether a smaller model with a multi-agent architecture can approach the performance of a stronger single-agent system,
    
- and whether it can do so with better cost efficiency.
    

## 9. Comparison Methods

The main comparison dimension is **architecture**, centered around the “small model + multi-agent” question.

### 9.1 Small Model Single-Agent

A single agent handles the full workflow:

- decides which sources to inspect first,
    
- chooses tools on its own,
    
- determines the next step based on intermediate results,
    
- and produces the final structured output.
    

The key point is that the entire workflow is controlled by **one unified decision-making agent**, without explicit role decomposition.

### 9.2 Small Model Single-Agent + Verifier

This architecture keeps the same single-agent workflow, but adds an explicit verification stage:

- the single agent first completes retrieval, reasoning, and an initial answer,
    
- a verifier checks whether the answer satisfies formatting and evidence constraints,
    
- if the answer fails verification, the verifier may provide feedback **once**,
    
- the agent then revises the output and returns the final answer.
    

This setup isolates the effect of adding verification without introducing multiple agents.

### 9.3 Small Model Multi-Agent + Verifier (Main Method)

The main method decomposes the workflow into several general-purpose roles:

- **Planner**: proposes high-level steps or subgoals
    
- **Retriever**: gathers information from documents, web sources, and records
    
- **Reasoner**: integrates retrieved information into an answer
    
- **Verifier**: checks whether the final output satisfies format and evidence requirements
    

Execution flow:

1. Planner proposes a high-level sequence;
    
2. Retriever gathers relevant information;
    
3. Reasoner produces an answer;
    
4. Verifier checks the answer;
    
5. if verification fails, feedback is provided **at most once**;
    
6. the workflow revises and returns the final result.
    

The purpose of this architecture is to test whether explicit role decomposition adds value beyond verification alone.

### 9.4 Strong Model Single-Agent (Reference)

A stronger closed model is run under the same single-agent setting:

- it autonomously chooses tools,
    
- performs multi-step retrieval and reasoning,
    
- and produces the final structured answer.
    

This acts as a performance reference point for the question of whether a smaller model under a multi-agent architecture can approach a stronger single-agent system.

### 9.5 Core Logic of the Comparisons

The most important comparisons are:

- **small model Single-Agent vs small model Single-Agent + Verifier**
    
    - to measure whether verification itself helps;
        
- **small model Single-Agent + Verifier vs small model Multi-Agent + Verifier**
    
    - to test whether role decomposition adds value beyond verification;
        
- **small model Multi-Agent + Verifier vs strong model Single-Agent**
    
    - to test whether a smaller model with a more structured architecture can narrow the gap to a stronger single-agent system.
        

To avoid conflating framework-level auto-repair with architectural effects, all main comparison methods will share:

- the same final output schema,
    
- and **at most one** final structured-output correction attempt.
    

Structured output is therefore treated only as a unified output constraint, not as an extra advantage for one particular architecture.

## 10. Main Method Design

The main method will be implemented as a graph-structured workflow:

- **Planner**: generates high-level steps
    
- **Retriever**: retrieves documents, pages, and records
    
- **Reasoner**: integrates evidence into an answer
    
- **Verifier**: checks whether the output satisfies schema and evidence requirements
    

All nodes operate over the same overall tool set. Their differences come primarily from role definitions and graph routing, rather than from highly artificial tool partitioning.

LangChain / LangGraph will be used as a common engineering and orchestration layer rather than as the main experimental variable. The comparison is intended to focus on architectural design, not on whether a specific framework is used.

All methods in the main experiments will share the same final output schema constraint. Only the multi-agent method will maintain structured intermediate state across nodes; that component will be treated as an internal design choice and studied separately in ablations.

## 11. Ablation Studies

Ablations will be used to identify which components of the main method actually matter. Planned ablations include:

- removing the verifier,
    
- collapsing the multi-agent architecture back into a single-agent system,
    
- removing structured intermediate state (if time permits),
    
- weakening the role boundaries among planner / retriever / reasoner to test whether explicit specialization truly helps.
    

Notes:

- unlimited structured-output retries will **not** be part of the main experiments, since that would confound architecture effects with retry budget;
    
- all methods will share at most one final output correction attempt;
    
- if time permits, a more permissive retry policy may be explored as an additional experiment, but it will not be part of the main conclusion.
    

## 12. Evaluation Metrics

Main metrics include:

- final task success rate,
    
- structured field accuracy,
    
- evidence/source attribution accuracy (when applicable),
    
- average number of steps,
    
- token / cost,
    
- latency.
    

We will report results by:

- task type,
    
- difficulty level,
    
- architecture.
    

## 13. Experimental Goal

The goal of the project is not simply to show that one method scores the highest, but to answer:

1. Does multi-agent + verifier truly outperform simpler architectures?
    
2. Are the gains primarily due to role decomposition or verification?
    
3. For which task types and difficulty levels is the extra complexity worthwhile?
    
4. Can a smaller model under a multi-agent architecture approach the performance of a stronger single-agent model while being more cost-efficient?
    

## 14. Expected Contributions

1. Build a small, automatically evaluable benchmark for multi-step workflows;
    
2. compare different agent architectures on document-centered and multi-app tasks;
    
3. analyze the separate contributions of multi-agent decomposition and verification;
    
4. study whether a small-model multi-agent setup can approach the capability of a stronger single-agent model;
    
5. analyze performance-cost tradeoffs across task types and difficulty levels.
    

## 15. Planned Team Division (To Be Filled)

- Member A: data generation and benchmark construction
    
- Member B: baselines / single-agent implementation
    
- Member C: multi-agent workflow, ablations, and analysis
    

## 16. Note

This version is intended for the planning report. It focuses on the research question, task design, and experimental structure. More detailed literature review, progress updates, and technical details can be added in the midterm report.


https://dl.acm.org/doi/pdf/10.1145/3641289
https://developers.openai.com/api/docs/guides/agent-evals
https://hamel.dev/blog/posts/evals-faq/how-do-i-evaluate-agentic-workflows.html
https://www.langchain.com/blog/the-anatomy-of-an-agent-harness