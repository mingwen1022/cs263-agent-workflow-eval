# Tau2 Retail Data Manifest

The new evaluation track uses tau2-bench retail data natively. We do not convert
tau2 tasks into the old `BenchmarkTask` JSON format.

## Source

Repository clone:

```text
third_party/tau2-bench
```

Copied retail data for this project:

```text
data/tau2/domains/retail
```

## Retail Data Files

Required files copied from tau2:

- `db.json`: retail environment database. Current clone has 50 products, 500 users, and 1000 orders.
- `policy.md`: domain policy shown to the agent.
- `tasks.json`: 114 retail tasks.
- `split_tasks.json`: train/test/base splits. Current clone has train=74, test=40, base=114.
- `audio_difficulty.json`: retail voice metadata; not needed for text eval, kept for completeness.
- `task_issues/`: known task issue metadata from tau2.
- `tasks_voice.json`: voice task set; not needed for the first text-only run, kept with the copied domain data.

Required tau2 code remains in:

- `third_party/tau2-bench/src/tau2/domains/retail/data_model.py`
- `third_party/tau2-bench/src/tau2/domains/retail/tools.py`
- `third_party/tau2-bench/src/tau2/domains/retail/environment.py`
- `third_party/tau2-bench/src/tau2/domains/retail/utils.py`
- `third_party/tau2-bench/src/tau2/runner/`
- `third_party/tau2-bench/src/tau2/evaluator/`
- `third_party/tau2-bench/src/tau2/user/`
- `data/tau2/user_simulator/`

## Retail 50 Subset

Config:

```text
configs/tau2/retail_50.json
```

The first run should use the first 50 task IDs from the `base` split:

```text
0, 1, 2, 3, 4, 6, 7, 8, 10, 11,
13, 14, 15, 16, 19, 20, 21, 22, 23, 24,
25, 28, 29, 30, 31, 34, 35, 37, 41, 43,
44, 46, 47, 48, 50, 52, 54, 57, 58, 59,
63, 66, 67, 69, 72, 73, 75, 76, 78, 80
```

## Model Choice

User simulator is fixed to Vertex Gemini 3 Flash Preview:

```text
vertex_ai/gemini-3-flash-preview
```

Keep the user simulator fixed across all agent systems. The main experimental
variable should be the agent implementation/model.

Use:

```json
{"temperature": 0.0, "max_tokens": 2048}
```

In smoke tests, `max_tokens=256` was too small for Gemini 3 Flash Preview
because reasoning tokens consumed the output budget and LiteLLM returned
`content=None`. `max_tokens=2048` produced normal user text.

## First Expected Command Shape

Once tau2 dependencies are installed, the native CLI shape is:

```bash
TAU2_DATA_DIR=data \
tau2 run \
  --domain retail \
  --agent llm_agent \
  --agent-llm <agent_model> \
  --user user_simulator \
  --user-llm vertex_ai/gemini-3-flash-preview \
  --user-llm-args '{"temperature": 0.0, "max_tokens": 2048}' \
  --task-ids 0,1,2,3,4,6,7,8,10,11,13,14,15,16,19,20,21,22,23,24,25,28,29,30,31,34,35,37,41,43,44,46,47,48,50,52,54,57,58,59,63,66,67,69,72,73,75,76,78,80 \
  --num-trials 1 \
  --seed 300 \
  --save-to tau2_retail_50_large_single
```

For local Ollama/small-single, we should first verify LiteLLM model naming and
tool-calling support. If LiteLLM cannot tool-call through Ollama reliably, the
next step is a custom tau2 `HalfDuplexAgent` adapter around the existing
LangChain/Ollama single agent.
