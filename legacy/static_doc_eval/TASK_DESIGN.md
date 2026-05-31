# Benchmark Task Design

> Describes the methodology used to construct and calibrate the hard and medium
> multi-document workflow tasks for the CS263 agent evaluation benchmark.

---

## 1. Design Goals

Each task must:

1. **Require multi-source reasoning** — no single source contains all the
   information needed to answer the task.
2. **Be deterministic and verifiable** — the gold answer is uniquely derivable
   from the sources without ambiguity.
3. **Avoid embedded answer hints** — source data must not contain columns or
   fields that directly reveal the answer (e.g., `eligible = true/false`).
4. **Test realistic enterprise workflows** — tasks are drawn from recognizable
   business processes: SLA reviews, expense claims, vendor renewals, payroll
   corrections, etc.
5. **Include noise and distractors** — sources contain rows and documents that
   look plausible but are out of scope.

---

## 2. Task Structure

### 2.1 Task JSON Schema

```json
{
  "task_id": "hard_<domain>_<id>",
  "task_family": "multi_app_workflow",
  "difficulty": "hard" | "medium",
  "instruction": "<verbatim instruction passed to agent>",
  "allowed_tools": ["list_sources", "read_csv", ...],
  "source_manifest": "sources/<task_id>/source_manifest.json",
  "gold_output": { "<field>": <value>, ... },
  "evaluation_criteria": {
    "exact_fields": [...],
    "numeric_tolerances": { "<field>": 0.01, ... },
    "set_fields": [...],
    "set_aliases": { "<field>": { "<canonical>": ["alias1", ...] } },
    "scoring_notes": "..."
  }
}
```

### 2.2 Source Files

Each task has 3–8 source files in mixed formats:

| Format | Typical content |
|--------|----------------|
| CSV | Transactional data: expense lines, incident logs, invoice items, customer tiers |
| Markdown | Policies, contracts, SLA rules, eligibility criteria |
| TXT | Approval memos, email context, correction notes |
| PDF | Packet summaries (used sparingly for format diversity) |
| DOCX | Approval documents, ops notes |

---

## 3. Anti-Hint Principles

The most critical design rule: **source data must not contain answer keys**.

### 3.1 Forbidden patterns

| Pattern | Why forbidden | Correct alternative |
|---------|--------------|---------------------|
| `qualifying_alert = true/false` column | Directly answers which alert to use | Remove the column; model must infer from environment/description |
| `eligible_for_credit = true/false` column | Directly answers who gets credit | Remove; model must cross-reference tier + status + policy |
| `include_in_renewal = true/false` column | Directly answers what to count | Remove; model must apply contract scope rules |
| `notes: "Noise row from prior trip"` | Explicitly labels noise | Use neutral notes or no notes |
| `notes: "Start clock here"` | Directly answers SLA start | Remove; model must read environment + incident policy |

### 3.2 Permitted guidance

Notes columns are retained only when they explain *why* a record exists,
not *what to do* with it.

**Current example (PC-08 correction entries):**

```
notes: "Rate miscalculation identified in payroll audit"   ← factual cause, permitted
notes: "Duplicate of C1"                                   ← factual label, permitted
notes: "Different employee correction included in batch"   ← factual context, permitted
```

Models still need the policy file to decide how to handle each entry;
the notes alone cannot answer the task.

**Prohibited notes content:**
- Direct include/exclude decisions (`"Noise row"`, `"Start clock here"`)
- Eligibility conclusions (`"Sandbox seats are not billable"`, `"Gold but not affected"`)

**The test**: if a model reads only the notes column (without the policy file),
can it answer the task's key fields? If yes, the notes are too helpful.

### 3.3 Distractor tools

The allowed tools list includes several tools that return no useful data:
`lookup_vendor_status`, `search_employee_directory`, `check_public_calendar`,
`estimate_shipping_cost`. These test whether agents make unnecessary tool calls.
Models should recognize these are irrelevant and not waste tool budget on them.

---

## 4. Output Field Design

### 4.1 Field type selection

**Exact fields** (numeric or boolean): used when the answer is unambiguous and
directly computable.
- Must have a `numeric_tolerance` (default 0.01) for float fields to handle
  floating-point rounding.
- Boolean fields have no tolerance.
- String exact fields (e.g., `approval_required_from`) should be avoided in
  favor of set fields, since models use different phrasings for the same role.

**Set fields** (arrays): used for enumeration of items that require reasoning.
- Each expected item generates two check types:
  - `contains`: is this item present in the model's answer?
  - `no_unexpected_items`: does the model include only items supported by evidence?
- The `no_unexpected_items` check penalizes over-inclusive answers.

### 4.2 Set alias design

Aliases capture reasonable label variations that reflect correct reasoning but
different phrasing. Design principles:

- **Aliases should cover what models naturally output** — run a trial evaluation,
  collect model outputs, and add all semantically correct variants.
- **Aliases should NOT cover incorrect reasoning** — if a model outputs a wrong
  item, do not add it as an alias just to improve scores.
- **Aliases are normalized** using `_normalize_label()`: lowercased,
  non-alphanumeric characters replaced with underscores, consecutive underscores
  collapsed.

**Alias breadth by field type:**

| Field type | Alias breadth | Rationale |
|------------|--------------|-----------|
| Excluded rows/alerts/lines | Broad — include row IDs AND descriptions | Models may use "n1" or "prior_invoice_line" for the same thing |
| Denied items / risk flags | Moderate — include common rephrasing | Models use different category names for the same policy violation |
| Customer/vendor names | Narrow — canonical + obvious abbreviations | These are proper nouns, not categories |

### 4.3 Field semantics and the excluded vs. denied distinction

Two field types that frequently confuse models:

- **excluded_rows / excluded_alerts / excluded_lines**: rows that do **not
  belong** to this case at all (wrong claim ID, different entity, prior batch,
  voided entries). Their amounts must not appear in calculations.

- **denied_items / denied_corrections / dispute_items**: items that **do belong**
  to this case but are rejected by policy (alcohol in a meal receipt, commute,
  premium WiFi). Their amounts are specifically deducted from totals.

These two concepts must be in separate fields and never overlap. Confusing them
is a common small-model failure mode.

---

## 5. Noise Item Design

Noise items test whether agents correctly scope their analysis.

### 5.1 Noise types

| Noise type | Example | What it tests |
|------------|---------|---------------|
| Wrong entity | Different employee's correction in same batch export | Agent must filter by employee ID |
| Wrong period | Q4 2025 data in a Q1 2026 report | Agent must apply period constraint |
| Wrong invoice | INV-57 line in an INV-58 review | Agent must match by invoice number |
| Prior batch | MP-07 entry in an MP-08 batch | Agent must check batch ID |
| Staging event | Staging alert in a production incident log | Agent must read environment field |
| Different department | Finance row in an Engineering budget request | Agent must scope by department |

### 5.2 Noise calibration

- Hard tasks: 3–5 noise items across sources; noise items require reasoning to
  identify (e.g., different employee + correct correction type looks very plausible).
- Medium tasks: 1–2 noise items; noise is somewhat easier to spot (wrong claim
  ID, different department).

Noise items should **not** be labeled as noise in source files. Identifying
them is part of the task.

---

## 6. Numeric Field Design

### 6.1 Calculation complexity by difficulty

| Difficulty | Calculation pattern | Example |
|------------|---------------------|---------|
| Easy | Base lookup (1 source) | Read the base fee |
| Medium | 1–2 step derivation | Hourly rate × hours = total |
| Hard | Multi-step with corrections + caps | Base + overage − correction, capped per day |

### 6.2 Multi-step calculation patterns

**Overage pattern** (requires cross-document join):
```
actual_qty (from usage CSV) - included_qty (from pricing CSV) = overage_qty
overage_cost = overage_qty × per_unit_rate (from pricing CSV)
total = base_fee + overage_cost
```
This is the hardest pattern because it requires the model to link two separate
source files. Small models (4B) consistently fail this without explicit guidance.

**Cap pattern** (daily/per-item limit):
```
raw_total = sum(eligible items)
capped = min(raw_total, cap_limit)
denied = raw_total - capped
```

**Correction pattern** (receipt amendments):
```
corrected_amount = submitted_amount - non_reimbursable_component
apply_cap_to: corrected_amount (not original)
```

These patterns often appear in combination, which is what makes hard tasks hard.

---

## 7. Difficulty Calibration

### 7.1 Target accuracy ranges

| Difficulty | large_single | small_single | large–small gap |
|------------|-------------|-------------|----------------|
| Easy | ~100% | ~100% | ~0% |
| **Medium** | **~87–90%** | **~64–70%** | **~20–25%** |
| **Hard** | **~88–95%** | **~60–65%** | **~28–35%** |

### 7.2 Calibration process

1. **Design task and gold output** — manually verify the gold is correct by
   tracing through each source file.
2. **Run gold test** — `score_prediction(task, task.gold_output)` must return
   100%. This catches schema mismatches and alias gaps.
3. **Run trial evaluation** — test on `large_single` and `small_single`.
4. **Identify alias gaps** — collect model outputs for each field; add aliases
   for correct reasoning expressed with different labels.
5. **Identify structural issues** — if both models score identically (0% gap),
   it usually means:
   a. The task is too easy (both get 100%), or
   b. Both models fail on the same alias gap (neither can identify a field).
6. **Adjust task content or aliases** — add noise items to increase difficulty;
   broaden aliases to fix false failures.
7. **Re-run and iterate** — repeat steps 3–6 until target ranges are met.

### 7.3 Anti-cheating rules during calibration

- Aliases may only be added for labels that represent **correct reasoning** —
  a model that outputs the right answer with a different label gets credit.
- Aliases must **not** be added for labels that represent incorrect reasoning —
  even if many models output a wrong label, the scoring must penalize it.
- Task instructions and source content must **not** be changed to match what
  specific models prefer to output — only expand aliases, never encode answers.
- Numeric examples in workflow prompts must use **generic placeholder values**,
  not values from any specific task.

---

## 8. Hard Task Profiles

10 tasks across 6 enterprise domains:

| Task | Domain | Sources | Checks | Key difficulty |
|------|--------|---------|--------|----------------|
| hard_incident_sla_ir42 | Ops/SLA | 7 | 22 | 4-way customer eligibility, alert exclusion reasoning |
| hard_initial_tr19_reimbursement | Finance/Expense | 8 | 20 | Two receipt corrections, hotel cap + workshop cap, 8 denied items |
| hard_vendor_renewal_cb27 | Procurement | 8 | 16 | Multi-table cost join (base + seat overage + storage overage) |
| hard_purchase_order_po91 | Procurement | 5 | 15 | Policy category distinction (support vs support_upgrade) |
| hard_conference_expense_ce44 | Finance/Expense | 4 | 16 | Sponsorship deduction, above-cap conference registration |
| hard_invoice_dispute_inv58 | AP/Finance | 5 | 18 | PO vs invoice 3-way mismatch (qty + rate + unauthorized fee) |
| hard_access_review_ar29 | IT Security | 4 | 18 | Prior violation history affects PII access decision |
| hard_sla_compliance_sc11 | Customer Success | 4 | 16 | Monthly credit cap applied across multiple incidents |
| hard_budget_variance_bv22 | Finance/Budget | 4 | 23 | Per-department 5% threshold, cross-department transfer rules |
| hard_payroll_correction_pc08 | HR/Payroll | 5 | 15 | Prior-batch cross-reference, commission type exclusion |

---

## 9. Medium Task Profiles

11 tasks across 8 domains, designed to be simpler versions of the hard patterns:

| Task | Domain | Sources | Checks | Key difficulty |
|------|--------|---------|--------|----------------|
| medium_incident_sla_mi01 | Ops/SLA | 3 | 14 | 3-customer tier check + staging vs production alert |
| medium_expense_claim_me07 | Finance/Expense | 2 | 8 | Daily meal cap + commute exclusion + WiFi denial |
| medium_vendor_selection_mv14 | Procurement | 2 | 9 | 3-criterion filter (SLA, region, contract length) |
| medium_access_request_ma03 | IT Security | 2 | 7 | Role-based permission matrix (3 requests, 1 wrong employee) |
| medium_invoice_review_mi22 | AP/Finance | 2 | 8 | PO match + unauthorized surcharge |
| medium_leave_request_ml09 | HR | 3 | 7 | Days threshold → approval type + accrual check |
| medium_budget_request_mb16 | Finance/Budget | 2 | 7 | Category approval tiers + 2 noise rows |
| medium_payroll_review_mp12 | HR/Payroll | 2 | 10 | Commission type exclusion + wrong-employee noise |
| medium_support_sla_ms08 | Customer Success | 2 | 9 | P1/P2/P3 response time SLA check |
| medium_contract_amendment_mc19 | Procurement | 2 | 9 | Manager vs VP approval tiers across 4 amendment types |
| medium_onboarding_check_mo05 | HR | 2 | 10 | Pre-start vs within-5-days mandatory split |

---

## 10. Observed Failure Modes by Model Type

### 10.1 Small model (Gemma 4-E4B) consistent failures

| Failure mode | Example | Root cause |
|---|---|---|
| Multi-document join | CB-27: reads base fee 1200 but misses seat overage | Cannot reliably cross-reference values across two CSV files |
| Set field incompleteness | TR-19: lists commute, wifi, gift but misses meal_cap_excess | Does not systematically apply each policy rule to each item |
| Policy tier misapplication | IR-42: misses Silver and Bronze tier exclusions | Does not verify every customer against every criterion |
| Label format deviation | Uses "overtime_c1" instead of "c1_overtime" | Composite label construction differs from expected format |
| Arithmetic without caps | Sums raw amounts without applying daily/per-item caps | Skips the correction/cap step in multi-step calculations |

### 10.2 Large model (Gemini 2.5 Flash) consistent failures

| Failure mode | Example | Risk flags |
|---|---|---|
| Over-inclusive set fields | CB-27: lists 17 ignored_inputs instead of 6 | Fails `no_unexpected_items` check |
| Missing risk flags | CB-27: omits discount_deadline and standard_sla_gap | Risk flags require synthesizing info from 2+ sources |
| Arithmetic errors under complexity | TR-19: computes net-after-tax instead of gross correction | Misinterprets field semantics under cognitive load |
| Verbose label concatenation | IR-42: uses "s1_staging_alert" instead of "s1" | Occurs when prompted with overly detailed formatting instructions |

### 10.3 Workflow failure modes (vs single small agent)

The multi-stage workflow (Planner → Collector → Reasoner → Verifier) helps on
hard tasks (+12.6% average gain) but can hurt on medium/easy tasks (-6.4%).

| Workflow failure pattern | When it occurs |
|---|---|
| Collector summary incomplete | Complex tasks with 6+ sources; model stops before reading all |
| Reasoner label drift | Simpler tasks where single-pass agent is already accurate; extra pass introduces different phrasing |
| Verifier false approval | Verifier cannot re-derive multi-document join independently |
| Empty draft answer | Extremely complex numeric reasoning; Reasoner fails to produce parseable JSON |

**Key finding**: workflow architecture has a task complexity threshold. Below the
threshold, single-pass agents are more reliable. Above the threshold, systematic
evidence collection and verification provide clear benefits.

---

## 11. Workflow Prompt Design Constraints

All four workflow node prompts (Planner, Collector, Reasoner, Verifier) must be:

1. **Domain-agnostic** — no references to specific task types, domains, or field names
2. **Task-agnostic** — no numeric values, entity names, or other task-specific content
3. **No embedded answers** — prompts may not give calculation examples using values from any benchmark task
4. **Generic by construction** — the same 4 prompts are used for all 10 hard + 11 medium tasks

Violation of these constraints would invalidate the comparison: if a workflow
prompt contains task-specific hints, the workflow advantage is not attributable
to architecture but to information leakage.

The key test: could the same 4 prompts be deployed on a completely new task domain
(e.g., healthcare claims, legal document review) and still provide the same
structural benefit? The current prompts are designed to pass this test.
