"""Jev's per-turn decision, ported from OIUI's LangGraph middleware to AG-UI runs."""

from ag_ui.core import AssistantMessage, EventType, RunAgentInput, Tool, ToolMessage, UserMessage

from oiui_claude import routing
from oiui_claude.agent import NOT_SIGNED_IN, OIUIClaudeAdapter
from oiui_claude.credential import plan

from .conftest import FAKE_TOKEN

BROWSER_TOOLS = ["generateSandboxedUi", "barChart", "pieChart", "render_a2ui", "someAppTool"]


def decision(choice):
    renderer = {"text": "text", "table": "a2ui"}.get(choice, "open_generative_ui")
    return {"renderer": renderer, "visualization": choice, "confidence": 0.9, "source": "jev"}


class FakeJev:
    def __init__(self, choice="line_chart"):
        self.calls = []
        self.choice = choice

    async def __call__(self, context):
        self.calls.append(context)
        return decision(self.choice)


def user(id, text):
    return UserMessage(id=id, role="user", content=text)


async def test_jev_is_asked_once_per_turn():
    jev = FakeJev()
    router = routing.JevRouter(route=jev)
    first = [user("u1", "Plot sales by month")]
    assert (await router.decision("t", first))["visualization"] == "line_chart"
    # A client-tool continuation of the same turn reuses the decision.
    continuation = [*first, AssistantMessage(id="a1", role="assistant", content="Here"), ToolMessage(id="m", role="tool", tool_call_id="c", content="ok")]
    await router.decision("t", continuation)
    assert len(jev.calls) == 1
    assert jev.calls[0] == [{"role": "human", "content": "Plot sales by month"}]
    # A new user message is a new turn, even with the same words.
    await router.decision("t", [*continuation, user("u2", "Plot sales by month")])
    assert len(jev.calls) == 2
    # Threads are separate.
    await router.decision("other", first)
    assert len(jev.calls) == 3


def test_apply_keeps_only_the_render_tool_jev_chose():
    kept, note = routing.apply(decision("bar_chart"), BROWSER_TOOLS)
    assert kept == ["generateSandboxedUi", "someAppTool"]
    assert "renderer=open_generative_ui; visualization=bar_chart" in note
    kept, note = routing.apply(decision("table"), BROWSER_TOOLS)
    assert kept == ["render_a2ui", "someAppTool"]
    assert "copilotkit://open-generative-ui-tables" in note
    kept, note = routing.apply(decision("text"), BROWSER_TOOLS)
    assert kept == ["someAppTool"]
    kept, note = routing.apply(decision("animated_route"), BROWSER_TOOLS)
    assert "get_trip_stop_images" in note and "Leaflet" in note
    assert routing.apply(None, BROWSER_TOOLS) == (BROWSER_TOOLS, "")


def run_input(messages, tools=BROWSER_TOOLS):
    return RunAgentInput(
        thread_id="t1", run_id="r1", state=None, context=[], forwarded_props={"model": "claude-opus-5-5"},
        tools=[Tool(name=n, description=n, parameters={"type": "object", "properties": {}}) for n in tools],
        messages=messages,
    )


async def collect(adapter, data):
    return [event async for event in adapter.run(data)]


async def test_not_signed_in_ends_the_run_with_a_sign_in_message():
    jev = FakeJev()
    events = await collect(OIUIClaudeAdapter(router=routing.JevRouter(route=jev)), run_input([user("u1", "hi")]))
    assert [e.type for e in events] == [EventType.RUN_STARTED, EventType.RUN_ERROR]
    assert events[1].message == NOT_SIGNED_IN
    assert jev.calls == []


async def test_a_jev_failure_is_reported_as_oiui_words_it():
    async def failing(context):
        raise ValueError("Jev visualization routing is unavailable or timed out. Please retry.")

    plan.set(FAKE_TOKEN)
    events = await collect(OIUIClaudeAdapter(router=routing.JevRouter(route=failing)), run_input([user("u1", "hi")]))
    assert events[-1].type == EventType.RUN_ERROR and "Jev" in events[-1].message


async def test_the_run_gets_jevs_note_and_tools_and_no_browser_overrides(monkeypatch):
    plan.set(FAKE_TOKEN)
    adapter = OIUIClaudeAdapter(router=routing.JevRouter(route=FakeJev("bar_chart")))
    seen = {}

    async def fake_query(self, input_data, fit_results=False):
        # Where OpenBot's adapter would start Claude Code: record what it would be started with.
        options = self.build_options(input_data, input_data.thread_id)
        seen["tools"] = [t.name for t in input_data.tools]
        seen["props"] = input_data.forwarded_props
        seen["options"] = options
        from ag_ui.core import RunFinishedEvent
        yield RunFinishedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id)

    monkeypatch.setattr(OIUIClaudeAdapter, "_run_query", fake_query)
    events = await collect(adapter, run_input([user("u1", "Compare revenue by region")]))
    assert events[-1].type == EventType.RUN_FINISHED
    assert seen["tools"] == ["generateSandboxedUi", "someAppTool"]
    assert seen["props"] == {}
    options = seen["options"]
    assert options.model == "claude-sonnet-5-5"  # the browser's forwarded model is ignored
    assert options.system_prompt.startswith("\nYou are Open Generative UI")
    assert "visualization=bar_chart" in options.system_prompt
    assert set(options.mcp_servers) == {"ag_ui", "oiui"}
    assert "mcp__ag_ui__*" in options.allowed_tools and "mcp__oiui__*" in options.allowed_tools
    assert options.tools == [] and options.permission_mode == "dontAsk"
    # Only the offered browser tools and the oiui tools pass the PreToolUse hook.
    hook = options.hooks["PreToolUse"][0].hooks[0]
    assert await hook({"tool_name": "mcp__ag_ui__generateSandboxedUi"}, "x", None) == {}
    assert await hook({"tool_name": "mcp__oiui__get_trip_stop_images"}, "x", None) == {}
    for refused in ("Bash", "WebFetch", "Read", "mcp__ag_ui__barChart"):
        result = await hook({"tool_name": refused}, "x", None)
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


async def test_oiui_tools_reach_the_existing_python_functions():
    from oiui_claude import oiui_tools

    server = oiui_tools.oiui_server()
    assert server["name"] == "oiui"
    assert oiui_tools.oiui_tool_names() == {
        "mcp__oiui__query_data", "mcp__oiui__get_trip_stop_images", "mcp__oiui__plan_visualization",
    }
    planned = oiui_tools._as_sdk_tool(oiui_tools.plan_visualization)
    result = await planned.handler({"approach": "A bar chart", "technology": "SVG", "key_elements": ["bars", "axis"]})
    assert result["content"][0]["text"].startswith("Plan: A bar chart\nTech: SVG")
    data = await oiui_tools._as_sdk_tool(oiui_tools.query_data).handler({"query": "x"})
    assert '"is_sample": true' in data["content"][0]["text"]
    bad = await oiui_tools._as_sdk_tool(oiui_tools.get_trip_stop_images).handler({"wikipedia_titles": []})
    assert bad["is_error"] is True
