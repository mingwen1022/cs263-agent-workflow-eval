# CS263 Final Project — Current Status

> Last updated: 2026-05-28

---

## 1. Research Question

Can a **multi-agent workflow architecture** using a small local model close the performance
gap with a large proprietary model on hard multi-document enterprise workflow tasks?

**Baseline gap**: large single agent (Gemini 2.5 Flash) ≈ 92%, small single agent
(Gemma 4-E4B, local) ≈ 61%. The workflow targets closing this 31-point gap.

---

## 2. Benchmark: Hard Multi-Document Tasks

### 2.1 Task Design

Each task simulates a hard enterprise workflow decision that requires:
- Reading **4–8 source documents** in mixed formats (CSV, MD, TXT, PDF, DOCX)
- Cross-referencing rules/policies against data across multiple files
- Computing numeric totals with corrections, caps, and overages
- Identifying which rows/items are in-scope vs. excluded (noise)
- Returning a structured JSON answer with exact field names

**Difficulty design principles** (anti-hint rules):
- No "hint columns" in CSV files (e.g., no `qualifying = true/false`)
- No explicit labels in `notes` columns
- Noise rows require reasoning from context to exclude (not flagged directly)
- Numeric fields require multi-step cross-document calculation

### 2.2 The 10 Tasks

| Task ID | Domain | Sources | Checks |
|---------|--------|---------|--------|
| `hard_incident_sla_ir42` | Ops / SLA | 7 (CSV+MD+PDF+DOCX+TXT) | 22 |
| `hard_initial_tr19_reimbursement` | Finance / Expense | 8 (CSV+MD+PDF+DOCX+TXT) | 20 |
| `hard_vendor_renewal_cb27` | Procurement / Renewal | 8 (CSV+MD+PDF+DOCX+TXT) | 16 |
| `hard_purchase_order_po91` | Procurement / PO | 5 (CSV+MD+TXT) | 15 |
| `hard_conference_expense_ce44` | Finance / Expense | 4 (CSV+MD+TXT) | 16 |
| `hard_invoice_dispute_inv58` | AP / Invoice | 5 (CSV+MD+TXT) | 18 |
| `hard_access_review_ar29` | IT Security | 4 (CSV+MD+TXT) | 18 |
| `hard_sla_compliance_sc11` | Customer Success | 4 (CSV+MD+TXT) | 16 |
| `hard_budget_variance_bv22` | Finance / Budget | 4 (CSV+MD+TXT) | 23 |
| `hard_payroll_correction_pc08` | HR / Payroll | 5 (CSV+MD+TXT) | 15 |

### 2.3 Task JSON Schema

Each task is defined in `data/generated/hard_v1/tasks/<task_id>.json`:

```json
{
  "task_id": "hard_<name>",
  "task_family": "multi_app_workflow",
  "difficulty": "hard",
  "instruction": "<verbatim task instruction passed to agents>",
  "allowed_tools": ["list_sources", "read_csv", "read_pdf", ...],
  "source_manifest": "sources/<task_id>/source_manifest.json",
  "gold_output": { "<field>": <value>, ... },
  "evaluation_criteria": {
    "exact_fields": ["field1", ...],
    "numeric_tolerances": {"field1": 0.01, ...},
    "set_fields": ["field2", ...],
    "set_aliases": { "field2": { "canonical": ["alias1", "alias2"] } },
    "scoring_notes": "..."
  }
}
```

Source files live in `data/generated/hard_v1/sources/<task_id>/`.

---

## 3. Evaluation Methodology

### 3.1 Metric: Field Accuracy

The only reported metric is **field_accuracy** = `correct_checks / total_checks`.

Each task generates a set of atomic checks:
- **Exact check**: `score_prediction(expected, actual, tolerance)` for numeric/boolean/string fields
- **Set-contains check**: for each expected item in a set field, does the answer contain it (via alias matching)?
- **No-unexpected-items check**: does the answer contain any items NOT in the gold set?

**No task-success binary metric** — field accuracy is a continuous measure that reflects partial credit.

### 3.2 Scoring Logic (`src/cs263_agent_eval/eval/scoring.py`)

```python
# For each set field, two check types are generated:
# 1. One contains-check per gold item (item in actual?)
# 2. One no_unexpected_items check (actual ⊆ gold?)

# Aliases are normalized via _normalize_label():
#   lowercase, non-alphanumeric → underscore, collapse underscores
# Both expected and actual labels are normalized before comparison.

field_accuracy = correct_checks / total_checks
score_percent  = round(field_accuracy * 100, 2)
```

### 3.3 Why Field Accuracy, Not Binary Task Success

Binary task success (all checks pass = 1, else 0) is 0 for all systems on nearly all tasks
due to strict set-field completeness requirements. Field accuracy provides meaningful
differentiation and partial credit, consistent with QA evaluation practice.

---

## 4. Systems Evaluated

### 4.1 Large Single Agent (`large_single`)

- **Model**: Gemini 2.5 Flash via Google Cloud Vertex AI
- **Architecture**: Single ReAct agent with all source tools
- **System prompt**: generic baseline (see `agents/single_agent.py`)
- **Tool budget**: `max_agent_steps * 3` recursion limit

### 4.2 Small Single Agent (`small_single`)

- **Model**: Gemma 4-E4B via Ollama (local)
- **Architecture**: Same as large_single, same prompt
- **Tool budget**: same

### 4.3 Small Agentic Workflow (`small_agentic_workflow`)

- **Model**: Gemma 4-E4B for all nodes
- **Architecture**: 4-node LangGraph pipeline (see Section 5)
- **Prompts**: fully generic, no task-specific content

---

## 5. Workflow Architecture

### 5.1 Overview

```
Task Instruction (identical to single-agent input)
         │
         ▼
 ┌─────────────┐
 │   PLANNER   │  LLM call (no tools)
 │             │  → fields_to_produce, sub_questions, exclusion_reminders
 └──────┬──────┘
        ↓
 ┌─────────────┐
 │  COLLECTOR  │  ReAct agent (all tools)
 │             │  Reads EVERY source, writes structured evidence:
 │             │  KEY NUMBERS / RULES / ITEMS / NOISE
 └──────┬──────┘
        ↓
 ┌─────────────┐
 │   REASONER  │  ReAct agent (all tools — can re-read sources if needed)
 │             │  Applies rules to evidence, computes all fields
 │             │  Output: draft JSON + _evidence citations
 └──────┬──────┘
        ↓
 ┌─────────────┐
 │   VERIFIER  │  ReAct agent (run_calculation only)
 │             │  Re-derives numeric fields, checks set completeness
 │             │  Returns: {verdict: "approved"|"revise", issues: [...]}
 └──────┬──────┘
        │
   ┌────┴───────────────────┐
   │ verdict=revise          │ verdict=approved
   │ AND revision_count < 1  │ OR revision_count ≥ 1
   ↓                         ↓
COLLECTOR (revision pass) → FINAL OUTPUT (JSON)
REASONER  (revision pass)
```

**Max revisions**: 1 (controlled by `settings.max_workflow_revisions`)

### 5.2 State Schema

```python
class WorkflowState(TypedDict, total=False):
    task_instruction: str          # verbatim task instruction
    task_sources:     dict         # source_id → file path
    plan:             dict         # Planner output
    evidence:         str          # Collector's structured summary
    draft_answer:     dict         # Reasoner output (includes _evidence)
    verifier_feedback: dict        # {verdict, issues}
    revision_count:   int
    final_answer:     dict         # clean JSON without _evidence
    tool_log:         list[dict]
    error:            str | None
```

### 5.3 Node Prompts

All prompts are **fully generic** — no task-specific content, no domain references,
no pre-encoded answers. The same 4 prompts are used for all 10 tasks.

#### PLANNER
```
You are a task planner. Read the task instruction and produce a JSON plan.

Output only a JSON object with these keys:
  "fields_to_produce": list of output field names required by the task
  "sub_questions": list of {"field": ..., "question": ...} — one per field
  "exclusion_reminders": list of things the instruction says to exclude/ignore

No explanation outside the JSON.
```

#### COLLECTOR
```
You are a document reader. Your only job is to read every available source and
extract the most important facts.

Steps:
1. Call list_sources to get the full list of source IDs.
2. Read EVERY source using the matching tool (read_csv / read_pdf / read_docx /
   read_text_source / read_source). Do NOT skip any source.
3. After reading ALL sources, write a structured summary in this format:

=== KEY NUMBERS AND DATA ===
(all numeric values, dates, quantities, rates, thresholds found across sources;
 if a source contains both an included/limit quantity and an actual quantity for
 the same metric, state both and whether the actual exceeds the limit)

=== RULES AND POLICIES ===
(all eligibility criteria, calculation rules, exclusion rules, caps, approval
requirements)

=== ITEMS AND THEIR ATTRIBUTES ===
(for each entity / row / entry relevant to the task: list its key attributes
side by side so comparisons are easy)

=== OUT-OF-SCOPE / NOISE ===
(items clearly not relevant: wrong ID, wrong period, different entity, voided, etc.)

Do NOT answer the task — only extract and organize what the sources say.
```

#### REASONER
```
You are a precise analyst. Use the evidence notes provided. If a specific value
is missing or unclear in the evidence, you may re-read the relevant source using
the available tools. Follow these rules strictly.

━━ NUMERIC FIELDS ━━
For every numeric field:
1. Identify the BASE value from evidence (e.g., base fee, starting amount).
2. Identify ALL adjustments: overages, corrections, caps, deductions.
   - Overage formula: (actual_quantity - included_quantity) × unit_rate
   - Cap formula: min(computed_value, cap_limit)
   - Correction: replace original with corrected value before summing
3. Call run_calculation for each arithmetic step. Show the expression first.
4. Sum all components: call run_calculation("base + adj1 + adj2 + ...").

━━ SET / ARRAY FIELDS ━━
For every set field:
1. List ALL candidate items from the evidence (do not skip any).
2. For EACH candidate, apply EVERY relevant rule one by one:
   - "Does item X meet criterion A?" → yes/no + source citation
   - "Does item X meet criterion B?" → yes/no + source citation
3. Include the item ONLY if it passes all inclusion criteria.
4. Exclude the item if it fails any exclusion criterion.
5. Use short snake_case labels.

━━ OUTPUT ━━
Return one JSON object with all required fields.
Add an "_evidence" key mapping each field to its source citation.
No explanation outside the JSON.
```

#### VERIFIER
```
You are a strict verifier. Check the draft answer field by field.

For NUMERIC fields:
1. Re-read the evidence for base value AND all overages/corrections.
2. Re-compute from scratch with run_calculation. Does it match the draft?
3. If not, report arithmetic_error with the correct expression.

For SET/ARRAY fields:
1. List every item in the evidence that could belong to this field.
2. Check: is each gold-standard item present in the draft?
3. Check: does every draft item have clear evidence support?
4. Report missing_item or extra_item as appropriate.

Return JSON:
{"verdict": "approved", "issues": []}
OR
{"verdict": "revise", "issues": [
  {"field": "...",
   "type": "arithmetic_error | missing_item | extra_item | unsupported_value",
   "detail": "...",
   "correction_hint": "..."}
]}

Be specific: give the exact correct value or missing item in correction_hint.
No explanation outside the JSON.
```

### 5.4 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Reasoner gets all tools (not just run_calculation) | Allows Reasoner to re-read specific sources when Collector summary is incomplete; prevents empty answers on complex tasks |
| Collector notes actual-vs-limit comparisons | General heuristic: when a source has both an included limit and actual quantity for the same metric, the Collector explicitly notes whether actual exceeds the limit, helping the Reasoner identify overages without task-specific guidance |
| Planner is lightweight | The task instruction already lists required output fields; Planner mainly extracts exclusion reminders and sub-questions to focus Collector attention |
| Max 1 revision | Balances latency vs. quality; in practice the Verifier typically approves after the first Reasoner pass |

---

## 6. Results

### 6.1 Full 10-Task Evaluation

| Task | large_single | small_single | small_workflow | wf gain |
|------|------------|------------|--------------|---------|
| access_review_ar29 | 100.0% | 72.22% | 66.67% | −5.5% |
| budget_variance_bv22 | 95.65% | 82.61% | 86.96% | +4.3% |
| conference_expense_ce44 | 81.25% | 56.25% | 62.50% | +6.2% |
| incident_sla_ir42 | 95.45% | 68.18% | **95.45%** | +27.3% |
| initial_tr19_reimbursement | 95.00% | 30.00% | 50.00% | +20.0% |
| invoice_dispute_inv58 | 94.44% | 44.44% | 72.22% | +27.8% |
| payroll_correction_pc08 | 100.0% | 73.33% | **100.0%** | +26.7% |
| purchase_order_po91 | 93.33% | 60.00% | 73.33% | +13.3% |
| sla_compliance_sc11 | 100.0% | 81.25% | 81.25% | +0.0% |
| vendor_renewal_cb27 | 68.75% | 43.75% | 50.00% | +6.2% |
| **Average** | **92.39%** | **61.20%** | **73.84%** | **+12.6%** |

### 6.2 Summary Statistics

| Metric | Value |
|--------|-------|
| large_single avg | 92.39% |
| small_single avg | 61.20% |
| small_workflow avg | 73.84% |
| large–small gap | 31.2 pp |
| workflow–small gain | +12.6 pp |
| **Gap closed by workflow** | **40.5%** |
| Tasks where workflow ≥ small | 8 / 10 |
| Tasks where workflow matches large | 2 (IR-42, PC-08) |

### 6.3 Interpretation

- The workflow closes **40% of the large–small capability gap** using only generic prompts
  and the same local model as the single-agent baseline.
- On two tasks (IR-42 and PC-08), the small-model workflow **reaches or exceeds** the
  large-model single-agent score, demonstrating that architecture can fully compensate
  for model size in certain task types.
- Tasks with the largest gains share a pattern: multi-source policy application +
  set-field enumeration (IR-42 +27.3%, INV-58 +27.8%, PC-08 +26.7%, TR-19 +20%).
- The one regression (AR-29 −5.5%) and two neutral results suggest that some tasks
  are already near the small model's capability ceiling regardless of architecture.

---

## 7. Code Structure

```
final_project_v2/
├── data/
│   └── generated/hard_v1/
│       ├── tasks/                  # 10 × task JSON files
│       └── sources/                # 10 × source directories (CSV/MD/PDF/DOCX/TXT)
│
├── src/cs263_agent_eval/
│   ├── agents/
│   │   ├── single_agent.py         # build_single_agent(), build_baseline_prompt()
│   │   └── runner.py               # run_single_agent(), run_agentic_workflow()
│   │
│   ├── benchmark/
│   │   └── hard_tasks.py           # load_hard_task(), list_hard_task_ids()
│   │
│   ├── eval/
│   │   └── scoring.py              # score_prediction() → ScoreBreakdown
│   │
│   ├── tools/
│   │   └── local_tools.py          # make_source_tools(): list_sources, read_*, run_calculation, ...
│   │
│   ├── workflows/
│   │   └── small_agentic_workflow.py  # build_small_agentic_workflow() — 4-node LangGraph
│   │
│   ├── scripts/
│   │   └── run_hard_task.py        # CLI: --task-id, --system large_single|small_single|small_workflow
│   │
│   ├── model_factory.py            # get_vertex_llm(), get_small_ollama_llm()
│   ├── config.py                   # Settings (model names, temp, max_steps, max_revisions)
│   └── schemas.py                  # BenchmarkTask, ScoreBreakdown, RunRecord, AgentPrediction
│
├── WORKFLOW_DESIGN.md              # Architecture design rationale
└── PROJECT_STATUS.md               # This document
```

### 7.1 Key Entrypoints

**Run evaluation:**
```bash
# All 10 tasks, all 3 systems
PYTHONPATH=src python -m cs263_agent_eval.scripts.run_hard_task \
  --system large_single small_single small_workflow > results.json

# Single task, workflow only
PYTHONPATH=src python -m cs263_agent_eval.scripts.run_hard_task \
  --task-id hard_incident_sla_ir42 --system small_workflow
```

**Load and score a task manually:**
```python
from cs263_agent_eval.benchmark.hard_tasks import load_hard_task
from cs263_agent_eval.eval.scoring import score_prediction

task = load_hard_task("hard_incident_sla_ir42")
score = score_prediction(task, {"breached_sla": True, "credit_due": 500.0, ...})
print(score.score_percent)   # e.g. 95.45
```

### 7.2 Available Tools (per task)

Each task gets a set of tools built from its source manifest:

| Tool | Description |
|------|-------------|
| `list_sources` | List all source IDs and their file types |
| `read_source` | Read any source by ID (auto-detects format) |
| `read_text_source` | Read .txt or .md source |
| `read_csv` | Read CSV source |
| `read_pdf` | Read PDF source (regex-based text extraction) |
| `read_docx` | Read DOCX source (XML-based extraction) |
| `run_calculation` | Evaluate a safe arithmetic expression |
| `lookup_vendor_status` | Distractor tool (returns no useful data) |
| `search_employee_directory` | Distractor tool (returns no useful data) |
| `check_public_calendar` | Distractor tool (returns no useful data) |
| `estimate_shipping_cost` | Distractor tool (returns no useful data) |

Distractor tools test whether agents avoid irrelevant calls.

---

## 8. Configuration

`src/cs263_agent_eval/config.py` (via `.env`):

| Setting | Default | Description |
|---------|---------|-------------|
| `LARGE_VERTEX_MODEL` | `gemini-2.5-flash` | Large model via Vertex AI |
| `SMALL_OLLAMA_MODEL` | `gemma4:e4b` | Small model via Ollama |
| `MODEL_TEMPERATURE` | `0` | Deterministic inference |
| `MAX_AGENT_STEPS` | `20` | Max tool calls per agent node |
| `MAX_WORKFLOW_REVISIONS` | `1` | Max verifier-triggered revisions |
| `PROJECT_ID` | — | GCP project for Vertex AI |
| `LOCATION` | `us-central1` | GCP region |

---

## 9. API & Model Invocation

### 9.1 Large Model — Gemini 2.5 Flash via Vertex AI

**SDK**: `langchain-google-vertexai` (`ChatVertexAI`)

```python
# model_factory.py
from langchain_google_vertexai import ChatVertexAI

llm = ChatVertexAI(
    model_name="gemini-2.5-flash",   # LARGE_VERTEX_MODEL in .env
    project="<GCP_PROJECT_ID>",      # PROJECT_ID in .env
    location="us-central1",          # LOCATION in .env
    temperature=0,                   # MODEL_TEMPERATURE in .env
)
```

**Authentication**: Application Default Credentials (ADC). Run once:
```bash
gcloud auth application-default login
```

**Required GCP permissions**: `aiplatform.endpoints.predict` on the project.

**Invocation pattern** (via LangChain `create_agent`):
```python
# Each tool call = one Vertex AI API request
# Agent loop: LLM call → tool call → LLM call → ... → final answer
# Max calls per agent run ≈ MAX_AGENT_STEPS * 3 (recursion_limit)
result = agent.invoke(
    {"messages": [{"role": "user", "content": task.instruction}]},
    config={"recursion_limit": 60},   # 20 steps * 3
)
```

**Approximate API call count per task (single agent)**:
- Typical: 5–15 LLM calls (1 per ReAct step)
- Each source read = 1 tool call (no API cost, local)
- `run_calculation` = 1 tool call (no API cost, local eval)

---

### 9.2 Small Model — Gemma 4-E4B via Ollama

**SDK**: `langchain-ollama` (`ChatOllama`)

```python
# model_factory.py
from langchain_ollama import ChatOllama

llm = ChatOllama(
    model="gemma4:e4b",   # SMALL_OLLAMA_MODEL in .env
    temperature=0,
)
```

**Prerequisites**:
```bash
# Install Ollama: https://ollama.com
ollama pull gemma4:e4b        # download model (~4 GB)
ollama serve                  # start local server (default: localhost:11434)
```

**No API key required** — all inference is local via HTTP to `localhost:11434`.

**Invocation pattern**: same as large model (LangChain handles both identically).

**Performance characteristics**:
- Single agent: ~60–90 s per task (sequential tool use)
- Workflow: ~3–5× longer per task (4 node passes)

---

### 9.3 LangChain Agent Construction

Both single agent and each workflow node use the same builder:

```python
# agents/single_agent.py
from langchain.agents import create_agent

def build_single_agent(model, tools, system_prompt):
    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=system_prompt,
    )
```

`create_agent` produces a **ReAct-style tool-using agent** as a LangGraph runnable.
It binds tools to the model and creates the standard think→act→observe loop.

**Invocation**:
```python
result = agent.invoke(
    {"messages": [{"role": "user", "content": user_message}]},
    config={"recursion_limit": settings.max_agent_steps * 3},
)
# result["messages"] contains full tool call history
# result.get("structured_response") or last AIMessage = final text
```

---

### 9.4 Workflow Node Invocation Patterns

Each node is called differently based on its role:

#### Planner — direct LLM call (no tools)
```python
response = llm.invoke([
    SystemMessage(content=_PLANNER_SYSTEM),
    HumanMessage(content=state["task_instruction"]),
])
plan = parse_json_object(response.content)
```

#### Collector — ReAct agent, task instruction as user message
```python
# On first pass: task instruction only
# On revision pass: task instruction + verifier issues appended
user_msg = task_instruction + optional_issues_str
result = collector_agent.invoke({"messages": [{"role": "user", "content": user_msg}]})
evidence = _extract_evidence(result["messages"])  # tool call results
evidence += "\n\n=== COLLECTOR SUMMARY ===\n" + last_ai_text(result["messages"])
```

#### Reasoner — ReAct agent, task instruction + evidence as user message
```python
user_msg = (
    task_instruction
    + "\n\n[EVIDENCE FROM ALL SOURCES]\n" + evidence
    + optional_prev_draft          # on revision pass only
    + optional_issues_to_fix       # on revision pass only
)
result = reasoner_agent.invoke({"messages": [{"role": "user", "content": user_msg}]})
draft = parse_json_object(last_ai_text(result["messages"]))
```

#### Verifier — ReAct agent (calc tool only), task + evidence + draft
```python
user_msg = (
    task_instruction
    + "\n\n[EVIDENCE FROM ALL SOURCES]\n" + evidence
    + "\n\n[DRAFT ANSWER TO VERIFY]\n" + json.dumps(draft_clean)
)
result = verifier_agent.invoke({"messages": [{"role": "user", "content": user_msg}]})
feedback = parse_json_object(last_ai_text(result["messages"]))
# feedback = {"verdict": "approved"|"revise", "issues": [...]}
```

---

### 9.5 JSON Output Parsing

All nodes use a 3-tier fallback parser (`parse_json_object` in `runner.py`):

```python
def parse_json_object(content) -> dict:
    text = str(content).strip()
    # Tier 1: direct JSON parse
    try: return json.loads(text)
    except: pass
    # Tier 2: extract from ```json ... ``` fenced block
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try: return json.loads(match.group(1))
        except: pass
    # Tier 3: extract outermost {...} object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try: return json.loads(match.group(0))
        except: pass
    return {}   # fallback: empty dict
```

---

### 9.6 Tool Invocation (Local, Zero API Cost)

All tools are implemented locally in `tools/local_tools.py`.
Tool calls do **not** hit any external API — they read files from disk.

```python
tools = make_source_tools(task.sources)
# task.sources = {"source_id": "/absolute/path/to/file", ...}

# Tool call example (from LangChain message history):
# AIMessage.tool_calls = [{"name": "read_csv", "args": {"source_id": "usage_snapshot"}}]
# ToolMessage.content  = "account_id,product,...\n..."   (raw file content)
```

**`run_calculation`** uses Python `eval` with a restricted globals dict (no builtins,
only `round`, `min`, `max`, `abs`):

```python
@tool
def run_calculation(expression: str) -> str:
    safe_globals = {"__builtins__": {}, "round": round, "min": min, "max": max, "abs": abs}
    return str(eval(expression, safe_globals))
# Example: run_calculation("1200 + (132-100)*18 + (8-5)*90") → "2046"
```

---

### 9.7 LangGraph Workflow Invocation

```python
# runner.py — run_agentic_workflow()
from cs263_agent_eval.workflows.small_agentic_workflow import build_small_agentic_workflow

tools = make_source_tools(task.sources)
workflow = build_small_agentic_workflow(llm, tools)

initial_state = {
    "task_instruction": task.instruction,   # identical to single-agent input
    "task_sources": task.sources,
    "revision_count": 0,
    "tool_log": [],
}

result = workflow.invoke(initial_state)

final_answer = result.get("final_answer") or {}
# Fallback: if verifier never approved, use draft with _evidence stripped
if not final_answer:
    draft = result.get("draft_answer") or {}
    final_answer = {k: v for k, v in draft.items() if k != "_evidence"}
```

The compiled LangGraph workflow (`workflow.invoke(...)`) manages state transitions,
the conditional revision edge, and revision counting internally.
