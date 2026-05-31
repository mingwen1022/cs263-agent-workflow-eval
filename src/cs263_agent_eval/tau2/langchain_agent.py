"""LangChain-backed tau2 agent adapter.

Tau2 should remain responsible for environment tool execution and evaluation.
This adapter therefore does not use LangChain's full agent loop. It uses a
LangChain chat model with bound tool schemas and returns exactly one tau2
assistant message per turn: either a text reply or tool call(s).
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage as LCSystemMessage,
    ToolMessage as LCToolMessage,
)

from cs263_agent_eval.config import settings
from tau2.agent.base_agent import HalfDuplexAgent


TAU2_LANGCHAIN_AGENT_NAME = "langchain_llm_agent"

AGENT_INSTRUCTION = """
You are a customer service agent that helps the user according to the <policy> provided below.
In each turn you can either:
- Send a message to the user.
- Make a tool call.
You cannot do both at the same time.

Use tools when policy compliance or account/order state requires verification or mutation.
Be concise, helpful, and grounded in the policy and tool results.
""".strip()

SYSTEM_PROMPT = """
<instructions>
{agent_instruction}
</instructions>
<policy>
{domain_policy}
</policy>
""".strip()


def _strip_vertex_prefix(model_name: str | None) -> str:
    if not model_name:
        return settings.large_vertex_model
    return model_name.removeprefix("vertex_ai/")


def _vertex_location(model_name: str, llm_args: dict[str, Any]) -> str:
    if llm_args.get("location"):
        return str(llm_args["location"])
    if model_name.startswith("gemini-3"):
        return "global"
    return os.getenv("LOCATION") or settings.location


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _usage_from_ai_message(message: AIMessage) -> Optional[dict[str, Any]]:
    usage = getattr(message, "usage_metadata", None)
    if not usage:
        return None
    return dict(usage)


class LangChainTau2AgentState:
    """Mutable state for a single tau2 conversation."""

    def __init__(self, messages: list[Any]):
        self.messages = messages


class LangChainTau2Agent(HalfDuplexAgent[LangChainTau2AgentState]):
    """Half-duplex tau2 agent implemented with a LangChain chat model."""

    def __init__(
        self,
        tools: list[Any],
        domain_policy: str,
        llm: str,
        llm_args: Optional[dict[str, Any]] = None,
    ):
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.tools = tools
        self.domain_policy = domain_policy
        self.llm = llm
        self.llm_args = dict(llm_args or {})
        self._model = self._build_model()
        self._bound_model = self._model.bind_tools(self._tool_schemas())

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(
            domain_policy=self.domain_policy,
            agent_instruction=AGENT_INSTRUCTION,
        )

    def _build_model(self):
        if self.llm.startswith("ollama/"):
            from langchain_ollama import ChatOllama

            model_name = self.llm.removeprefix("ollama/")
            kwargs: dict[str, Any] = {"model": model_name}
            if self.llm_args.get("temperature") is not None:
                kwargs["temperature"] = self.llm_args["temperature"]
            if self.llm_args.get("num_predict") is not None:
                kwargs["num_predict"] = self.llm_args["num_predict"]
            return ChatOllama(**kwargs)

        from langchain_google_vertexai import ChatVertexAI

        model_name = _strip_vertex_prefix(self.llm)
        kwargs = {
            "model": model_name,
            "project": settings.project_id or os.getenv("VERTEXAI_PROJECT"),
            "location": _vertex_location(model_name, self.llm_args),
            "temperature": self.llm_args.get("temperature", settings.temperature),
            "max_tokens": self.llm_args.get("max_tokens"),
        }
        if self.llm_args.get("seed") is not None:
            kwargs["seed"] = self.llm_args["seed"]
        return ChatVertexAI(**{key: value for key, value in kwargs.items() if value is not None})

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [tool.openai_schema for tool in self.tools]

    def get_init_state(self, message_history: Optional[list[Any]] = None) -> LangChainTau2AgentState:
        from tau2.agent.base_agent import is_valid_agent_history_message

        if message_history is None:
            message_history = []
        assert all(is_valid_agent_history_message(m) for m in message_history), (
            "Message history must contain only AssistantMessage, UserMessage, or ToolMessage to Agent."
        )
        return LangChainTau2AgentState(messages=list(message_history))

    def generate_next_message(
        self, message: Any, state: LangChainTau2AgentState
    ) -> tuple[Any, LangChainTau2AgentState]:
        from tau2.data_model.message import MultiToolMessage

        if isinstance(message, MultiToolMessage):
            state.messages.extend(message.tool_messages)
        else:
            state.messages.append(message)

        started = time.perf_counter()
        lc_messages = [LCSystemMessage(content=self.system_prompt)]
        lc_messages.extend(self._to_langchain_messages(state.messages))
        ai_message = self._bound_model.invoke(lc_messages)
        generation_seconds = time.perf_counter() - started

        assistant_message = self._to_tau2_assistant_message(ai_message, generation_seconds)
        state.messages.append(assistant_message)
        return assistant_message, state

    def stop(self, message: Any = None, state: Any = None) -> None:
        return None

    def _to_langchain_messages(self, messages: list[Any]) -> list[BaseMessage]:
        from tau2.data_model.message import AssistantMessage, ToolMessage, UserMessage

        converted: list[BaseMessage] = []
        for message in messages:
            if isinstance(message, UserMessage):
                converted.append(HumanMessage(content=message.content or ""))
            elif isinstance(message, AssistantMessage):
                tool_calls = []
                if message.tool_calls:
                    tool_calls = [
                        {"name": call.name, "args": call.arguments, "id": call.id}
                        for call in message.tool_calls
                    ]
                converted.append(
                    AIMessage(content=message.content or "", tool_calls=tool_calls)
                )
            elif isinstance(message, ToolMessage):
                converted.append(
                    LCToolMessage(
                        content=message.content or "",
                        tool_call_id=message.id,
                    )
                )
        return converted

    def _to_tau2_assistant_message(self, message: AIMessage, generation_seconds: float):
        from tau2.data_model.message import AssistantMessage, ToolCall

        tau2_tool_calls = []
        for tool_call in getattr(message, "tool_calls", None) or []:
            call_id = tool_call.get("id") or f"lc_{len(tau2_tool_calls)}"
            tau2_tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=tool_call["name"],
                    arguments=tool_call.get("args") or {},
                )
            )

        if tau2_tool_calls:
            content = None
            tool_calls = tau2_tool_calls
        else:
            content = _content_to_text(message.content)
            tool_calls = None

        return AssistantMessage(
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            cost=0.0,
            usage=_usage_from_ai_message(message),
            raw_data={
                "langchain_response_metadata": getattr(message, "response_metadata", {}),
                "langchain_id": getattr(message, "id", None),
                "content": _content_to_text(message.content),
                "tool_calls": [
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in tau2_tool_calls
                ],
            },
            generation_time_seconds=generation_seconds,
        )

    def set_seed(self, seed: int) -> None:
        self.llm_args["seed"] = seed
        self._model = self._build_model()
        self._bound_model = self._model.bind_tools(self._tool_schemas())


def create_langchain_tau2_agent(
    tools: list[Any],
    domain_policy: str,
    llm: str,
    llm_args: Optional[dict[str, Any]] = None,
    **_: Any,
) -> Any:
    return LangChainTau2Agent(
        tools=tools,
        domain_policy=domain_policy,
        llm=llm,
        llm_args=llm_args,
    )


def register_langchain_tau2_agent() -> None:
    from tau2.registry import registry

    if registry.get_agent_factory(TAU2_LANGCHAIN_AGENT_NAME) is None:
        registry.register_agent_factory(
            create_langchain_tau2_agent,
            TAU2_LANGCHAIN_AGENT_NAME,
        )
