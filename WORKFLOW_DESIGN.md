# Small-Model Agentic Workflow Design

## 1. Motivation

Single-agent baselines (both large and small) attempt to read sources, extract
rules, enumerate items, and compute answers in a single unstructured pass. Small
models fail primarily in three ways on hard multi-document tasks:

| Failure mode | Root cause |
|---|---|
| Incomplete source coverage | Agent stops reading after finding "enough" evidence |
| Missing set items | No explicit enumeration step; items added opportunistically |
| Arithmetic errors | Calculations happen mid-reasoning without verification |
| Policy misapplication | Rule extraction and rule application are tangled |

The workflow separates these concerns across four specialized nodes. Each node
receives the **same original task instruction** that the single agent receives,
plus the structured output of the preceding nodes as additional context.

---

## 2. Architecture Overview

```
Task Instruction (identical to single-agent input)
         │
         ▼
 ┌───────────────┐
 │   PLANNER     │  Reads the task. Produces an explicit reading plan:
 │               │  which sources to read and in what order, and a
 │               │  list of sub-questions mapped to output fields.
 └───────┬───────┘
         │  plan: {sources_to_check, sub_questions, fields_to_produce}
         ▼
 ┌───────────────┐
 │   COLLECTOR   │  Executes the plan. Calls list_sources and read_*
 │               │  tools to read EVERY source. Produces structured
 │               │  evidence notes keyed by field category.
 └───────┬───────┘
         │  collected_evidence: [{source_id, key_facts, rules, …}]
         ▼
 ┌───────────────┐
 │   REASONER    │  Receives evidence notes + plan. Applies rules
 │               │  to evidence. Enumerates each set field explicitly.
 │               │  Computes numeric fields step by step. Outputs
 │               │  a draft JSON answer with per-field evidence refs.
 └───────┬───────┘
         │  draft_answer: {field → value, _evidence: {field → citation}}
         ▼
 ┌───────────────┐
 │   VERIFIER    │  Checks every field in the draft against evidence
 │               │  notes. Identifies: unsupported values, missing
 │               │  set items, arithmetic inconsistencies. Returns
 │               │  verdict "approved" or "revise" with issue list.
 └───────┬───────┘
         │
    ┌────┴─────────────────────────────┐
    │ verdict == "revise"              │ verdict == "approved"
    │ AND revision_count < max         │
    ▼                                  ▼
 ┌────────┐                     ┌─────────────┐
 │COLLECT │ (targeted re-read)  │ FINAL OUTPUT│
 │ again  │ → REASONER again    │  (JSON)     │
 └────────┘                     └─────────────┘
```

**Max revisions**: 1 (controlled by `settings.max_workflow_revisions`).  
**Model**: small model (e.g., gemma4:e4b via Ollama) for all nodes.  
**Tools**: each node has access to the full tool set; Reasoner and Verifier
typically use only `run_calculation`; Collector uses all read tools.

---

## 3. State Schema

```python
class WorkflowState(TypedDict, total=False):
    task:               dict[str, Any]   # BenchmarkTask (includes instruction)
    plan:               dict[str, Any]   # output of Planner
    collected_evidence: list[dict]       # output of Collector
    draft_answer:       dict[str, Any]   # output of Reasoner (includes _evidence)
    verifier_feedback:  dict[str, Any]   # {verdict, issues: [{field, reason}]}
    revision_count:     int
    final_answer:       dict[str, Any]   # clean JSON without _evidence
    error:              str | None
```

The `task.instruction` field is the verbatim task instruction text—identical
to what the single agent receives as its user message.

---

## 4. Node Specifications and Prompts

All system prompts are domain-agnostic. The task instruction is always passed
as the user message content, identical to the single-agent setup.

---

### 4.1 Planner Node

**Role**: Decomposes the task into an explicit evidence-gathering plan before
any source is read. Forces the model to commit to a reading strategy up front,
preventing ad-hoc or incomplete source coverage.

**Input**
- User message: `task.instruction` (verbatim)
- No tools needed

**Output**
```json
{
  "sources_to_check": ["<source_id_1>", "..."],
  "sub_questions": [
    {"field": "<output_field>", "question": "<what to determine>"},
    "..."
  ],
  "fields_to_produce": ["<field_1>", "..."],
  "exclusion_criteria": ["<what to watch out for and exclude>"]
}
```

**System Prompt**

```
You are a task planning specialist. You will receive a task instruction that
asks you to review source documents and return a structured JSON answer.

Before reading any sources, produce a reading and analysis plan in JSON.

Your plan must include:

1. "sources_to_check": a list of all source IDs you intend to read. Because
   you have not yet called list_sources, write ["ALL"] to indicate that every
   available source must be read without exception.

2. "sub_questions": for each output field the task requires, state one concrete
   question that, when answered, produces the field value. Derive the fields
   from the task instruction.

3. "fields_to_produce": the complete list of JSON field names the task requires
   in the final output.

4. "exclusion_criteria": identify categories of data or records that the task
   instruction says should be excluded or ignored. List them explicitly so the
   evidence collector knows what to filter.

Do not read any sources yet. Do not produce any field values. Output only the
plan JSON, with no explanation outside the JSON.
```

---

### 4.2 Collector Node

**Role**: Exhaustive evidence gathering. Reads every available source and
produces structured notes organized by field category. The Collector's contract
is completeness: it must not skip any source.

**Input**
- User message:
  ```
  {task.instruction}

  [READING PLAN]
  {plan as JSON}

  Use list_sources first to discover all available sources. Then read every
  source. Record evidence relevant to each planned sub-question.
  ```
- Tools: `list_sources`, `read_source`, `read_text_source`, `read_csv`,
  `read_pdf`, `read_docx`, `run_calculation`

**Output**
```json
[
  {
    "source_id": "...",
    "file_type": "...",
    "key_facts": ["<fact 1>", "..."],
    "rules_or_policies": ["<rule 1>", "..."],
    "items_in_scope": ["<item>", "..."],
    "items_out_of_scope": ["<item with reason>", "..."],
    "relevant_to_fields": ["<field_name>", "..."]
  },
  "..."
]
```

**System Prompt**

```
You are an evidence collector. Your job is to read every available source
document for the task and record the evidence you find. You must not skip
any source.

Process:
1. Call list_sources to get the complete list of available source IDs.
2. Read EVERY source using the appropriate tool (read_csv for CSV files,
   read_pdf for PDFs, read_docx for Word files, read_text_source or
   read_source for text and markdown). Do not skip any source, even if
   it appears unrelated at first glance.
3. For each source, record:
   - Key facts, data points, identifiers, dates, and amounts
   - Rules, policies, thresholds, or constraints stated
   - Which items or records appear to be in scope vs excluded
   - Which output fields this source is relevant to

You may use run_calculation to verify arithmetic you observe in the sources.

Output your notes as a JSON array. One object per source. Do not draw
conclusions or produce field values yet—only record what each source says.
Do not output anything outside the JSON array.
```

---

### 4.3 Reasoner Node

**Role**: Applies rules to evidence to produce a draft answer. Enumerates
every set field explicitly by going item-by-item rather than relying on
recall. Performs all arithmetic in explicit steps with run_calculation.

**Input**
- User message:
  ```
  {task.instruction}

  [EVIDENCE NOTES]
  {collected_evidence as JSON}

  Using only the evidence above, produce the required JSON answer.
  ```
- Tools: `run_calculation`

**Output**
```json
{
  "<field_1>": <value>,
  "<field_2>": <value>,
  "...",
  "_evidence": {
    "<field_1>": "<source_id + brief citation>",
    "<field_2>": "<source_id + brief citation>",
    "..."
  }
}
```

**System Prompt**

```
You are a policy analyst and calculation specialist. You will receive a task
instruction, structured evidence notes gathered from all source documents, and
must produce a JSON answer.

Rules for producing the answer:

NUMERIC FIELDS
- Do not compute in your head. Use run_calculation for every arithmetic
  operation, no matter how simple.
- Show the calculation expression before calling the tool.
- Apply corrections, caps, and exceptions found in the evidence before
  finalizing each number.

SET / ARRAY FIELDS
- Go through every item mentioned in the evidence notes one by one.
- For each item, explicitly decide: is this item in scope or excluded?
  State your reason before adding or excluding it.
- Do not add items that are not mentioned in the evidence. Do not omit
  items that are clearly in scope.
- Use short, consistent snake_case labels for all array items.

EXCLUSION AND NOISE
- Apply exclusion criteria from the evidence (wrong period, different
  entity, noise rows, voided entries, etc.) before counting or summing.
- Never include excluded items in numeric totals.

OUTPUT FORMAT
- Output a single JSON object.
- Include all fields the task requires.
- Add an "_evidence" key mapping each field to a brief source citation.
- No explanation outside the JSON.
```

---

### 4.4 Verifier Node

**Role**: Acts as a second pass critic. Checks every field in the draft answer
against the collected evidence. Approves the answer if all fields are grounded
and complete, or returns a structured issue list for revision.

**Input**
- User message:
  ```
  {task.instruction}

  [EVIDENCE NOTES]
  {collected_evidence as JSON}

  [DRAFT ANSWER]
  {draft_answer as JSON}

  Check the draft answer field by field. Return a verification report.
  ```
- Tools: `run_calculation` (for arithmetic re-verification)

**Output**
```json
{
  "verdict": "approved" | "revise",
  "issues": [
    {
      "field": "<field_name>",
      "type": "missing_item" | "unsupported_value" | "arithmetic_error" | "extra_item",
      "detail": "<specific description of the problem>",
      "correction_hint": "<what the correct value or approach should be>"
    }
  ]
}
```

**System Prompt**

```
You are a verification specialist. You will receive a task instruction,
structured evidence notes, and a draft answer. Your job is to verify that
every field in the draft answer is correct and complete.

For each field in the draft answer, check:

NUMERIC FIELDS
- Re-derive the value using run_calculation with the numbers from the
  evidence notes. Does the result match the draft?
- Were all corrections, caps, and exclusions applied correctly?
- Report "arithmetic_error" if the number is wrong.

SET / ARRAY FIELDS
- Go through the evidence notes and list every item that should appear
  in this field. Does the draft include all of them?
- Does the draft include any items that are NOT supported by evidence?
- Report "missing_item" if something was omitted.
- Report "extra_item" if something was added without evidence.

UNSUPPORTED VALUES
- Can every value be traced to a specific piece of evidence?
- Report "unsupported_value" if a value cannot be verified.

OUTPUT
- If all fields are correct: return {"verdict": "approved", "issues": []}
- If any problem is found: return {"verdict": "revise", "issues": [...]}
  with a specific, actionable correction_hint for each issue.
- Output only the JSON verification report. No explanation outside the JSON.
```

---

### 4.5 Revision Logic

After the Verifier returns a `"revise"` verdict, the workflow re-enters the
Collector node with targeted guidance, then re-runs the Reasoner.

**Collector (revision pass) input**
- User message:
  ```
  {task.instruction}

  [PREVIOUS EVIDENCE NOTES]
  {collected_evidence as JSON}

  [ISSUES FROM VERIFIER]
  {verifier_feedback.issues as JSON}

  Re-read any sources needed to address the issues above. Then append new
  or corrected findings to the evidence notes and return the updated set.
  ```

**Reasoner (revision pass) input**
- User message:
  ```
  {task.instruction}

  [UPDATED EVIDENCE NOTES]
  {collected_evidence as JSON}

  [PREVIOUS DRAFT]
  {draft_answer as JSON}

  [ISSUES TO FIX]
  {verifier_feedback.issues as JSON}

  Produce a corrected JSON answer addressing all reported issues. Apply
  the same calculation and enumeration discipline as before.
  ```

The revision loop runs at most `settings.max_workflow_revisions` times
(default: 1). After the limit, the Verifier's current best answer is used
as the final output.

---

## 5. Final Output Assembly

Before returning the final answer, strip the `_evidence` key so the output
matches the same schema as the single-agent baseline:

```python
final_answer = {k: v for k, v in draft_answer.items() if k != "_evidence"}
```

The final answer is scored by the same `score_prediction` function used for
the single-agent runs, with no modifications.

---

## 6. Design Rationale Summary

| Node | Addresses single-agent failure |
|---|---|
| Planner | Forces upfront commitment to reading all sources and mapping fields to sub-questions |
| Collector | Guarantees exhaustive source coverage; separates reading from reasoning |
| Reasoner | Explicit item-by-item enumeration for sets; forced calculator use for numerics |
| Verifier | Independent cross-check catches missing items and arithmetic errors before output |
| Revision loop | One targeted correction pass for issues the first pass missed |

The overall design follows **separation of concerns**: each node has a single
clearly-defined responsibility, which is a task that small models handle reliably
when focused. The combination of specialized nodes is expected to achieve field
accuracy approaching the large single-agent baseline at significantly lower
per-call cost.

---

## 7. Implementation Notes

The skeleton in `src/cs263_agent_eval/workflows/small_agentic_workflow.py`
maps directly to this design:

| Skeleton node | Design node |
|---|---|
| `planner_node` | Planner (§4.1) |
| `collector_node` | Collector (§4.2) |
| `reasoner_node` | Reasoner (§4.3) |
| `verifier_node` | Verifier (§4.4) |
| `route_after_verifier` | Revision routing (§4.5) |

Each node function should:
1. Build a LangChain `ChatOllama` (or equivalent) call using the system
   prompt defined above for that node.
2. Attach the appropriate tools via `bind_tools`.
3. Invoke the model with the user message constructed from `WorkflowState`.
4. Parse the model's JSON output and update the relevant state keys.

The `task.instruction` field (identical to single-agent input) is always the
base of the user message. Node-specific context (plan, evidence, draft) is
appended below a clearly labelled section header so the model can distinguish
between the original task and the workflow context.
