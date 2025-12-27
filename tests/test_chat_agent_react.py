import json
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import chat_agent as ca  # noqa: E402


class DummyLLM:
    """可注入的伪造 LLM，避免真实网络调用。"""

    def __init__(self) -> None:
        self.model_name = "dummy"
        self.bound_tools: list[Any] = []

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, *_args, **_kwargs):
        return AIMessage(content="ok")

    async def astream(self, *_args, **_kwargs):
        yield type("Chunk", (), {"content": "ok"})

    def with_structured_output(self, schema):
        class _Structured:
            async def ainvoke(self_inner, *_a, **_k):
                return schema()  # type: ignore[arg-type]

        return _Structured()


@tool
async def fake_device_prompt(
    prompt: str,
    session_id: str | None = None,
    target_device_id: str | None = None,
    system_prompt: str | None = None,
) -> str:
    """Mocked device_prompt tool for tests."""
    # 返回序列化 JSON，模拟设备应答
    return json.dumps({"answer": "ok", "topic_id": "T123"}, ensure_ascii=False)

fake_device_prompt.name = "device_prompt"


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    """全局打补丁，避免真实 LLM/设备调用。"""

    monkeypatch.setattr(ca, "_make_llm", lambda streaming=True: DummyLLM())
    monkeypatch.setattr(ca, "device_prompt", fake_device_prompt)
    monkeypatch.setattr(ca, "set_device_prompt_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(ca, "clear_device_prompt_context", lambda: None)
    yield


@pytest.mark.asyncio
async def test_plan_advances_and_observations_recorded(monkeypatch):
    """多步计划能推进 step_index，工具返回写入 observations。"""

    async def fake_plan(_state):
        return [
            ca.PlanStep(id="S1", type="device_action", goal="do something"),
            ca.PlanStep(id="S2", type="finalize", goal="wrap up"),
        ]

    async def fake_directive(step, state, user_goal, observations):
        return ca.DeviceActionDirective(
            tool_name="mock_tool",
            args={"path": "/tmp"},
            task="list files",
            success_criteria=["listed"],
        )

    async def fake_summary(_state, _goal):
        return "done"

    agent = ca.ChatAgent(max_tool_calls=3)
    monkeypatch.setattr(agent, "_generate_plan", fake_plan)
    monkeypatch.setattr(agent, "_decide_device_action", fake_directive)
    monkeypatch.setattr(agent, "_summarize_for_user", fake_summary)

    result = await agent.ainvoke(
        messages=[HumanMessage(content="列一下文件，然后告诉我结果")],
        session_id="S",
        target_device_id="D",
    )

    assert result["step_index"] >= 2
    assert len(result.get("observations", [])) == 1
    assert result.get("last_device_topic_id") == "T123"


def test_normalize_tool_calls_single_and_patch_defaults(monkeypatch):
    """单轮最多一个 tool_call，自动补齐缺失参数。"""
    agent = ca.ChatAgent(max_tool_calls=1)
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {"id": "1", "name": "device_prompt", "args": {"prompt": "a"}},
            {"id": "2", "name": "device_prompt", "args": {"prompt": "b"}},
        ],
    )
    state = {"session_id": "session-x", "target_device_id": "device-y"}

    agent._normalize_tool_calls(ai_msg, state)  # type: ignore[arg-type]

    assert len(ai_msg.tool_calls) == 1
    args = ai_msg.tool_calls[0]["args"]
    assert args["session_id"] == "session-x"
    assert args["target_device_id"] == "device-y"


@pytest.mark.asyncio
async def test_missing_info_prompts_user_without_ask_user_step(monkeypatch):
    """缺失信息时仍提示用户，但计划不包含 ask_user 步骤。"""

    async def fake_plan(_state):
        return [
            ca.PlanStep(id="S1", type="device_action", goal="list files"),
            ca.PlanStep(id="S2", type="ask_user", goal="should be filtered"),
            ca.PlanStep(id="S3", type="finalize", goal="wrap"),
        ]

    async def fake_directive(step, state, user_goal, observations):
        return ca.DeviceActionDirective(
            tool_name="mock_tool",
            args={"path": "/tmp"},
            task="list files",
            success_criteria=["listed"],
        )

    async def fake_summary(_state, _goal):
        return "summary"

    @tool
    async def empty_device_prompt(
        prompt: str,
        session_id: str | None = None,
        target_device_id: str | None = None,
        system_prompt: str | None = None,
    ) -> str:
        """Mocked device_prompt returning missing info hint."""
        return json.dumps({"answer": "list is empty, need path"}, ensure_ascii=False)

    empty_device_prompt.name = "device_prompt"

    monkeypatch.setattr(ca, "device_prompt", empty_device_prompt)

    agent = ca.ChatAgent(max_tool_calls=2)
    monkeypatch.setattr(agent, "_generate_plan", fake_plan)
    monkeypatch.setattr(agent, "_decide_device_action", fake_directive)
    monkeypatch.setattr(agent, "_summarize_for_user", fake_summary)

    result = await agent.ainvoke(
        messages=[HumanMessage(content="帮我看看设备日志目录")],
        session_id="S",
        target_device_id="D",
    )

    assert result["needs_user_input"] is True
    assert all(step["type"] != "ask_user" for step in result["plan"])


if __name__ == "__main__":
    import sys
    pytest.main([__file__, *sys.argv[1:]])
