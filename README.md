# CS263 Agent Workflow Evaluation

本项目用于评估 single-agent 和 agentic workflow 在 hard 多步任务上的表现差异。

计划比较三套系统：

1. 使用 Google Cloud Vertex Gemini 的较大闭源 single agent。
2. 使用本地 Ollama Gemma 的 small single agent。
3. 使用本地 Ollama Gemma，并由 Planner、Collector、Reasoner、Verifier 组成的 agentic workflow。

项目使用 `uv` 管理 Python 依赖。

```bash
uv sync
uv run check-models
```

已有 `.env` 应包含 `PROJECT_ID`，也可以包含 `GOOGLE_API_KEY`。Vertex 调用方式沿用旧项目已验证的接口形状：

```python
ChatVertexAI(
    model_name=...,
    project=PROJECT_ID,
    location=...,
    temperature=0,
)
```

注意：本项目只借鉴旧项目的模型接口调用方式，不复用旧项目的数据、任务、source、gold label、prompt 或实验结果。
