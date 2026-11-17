"""OIUI's own backend tools, served to Claude as an in-process SDK MCP server named `oiui`.

The tools are OIUI's (apps/agent/src), imported and called as they are: nothing is rewritten here.
Each is a LangChain tool; its description and argument schema become the MCP tool's.

Ported: query_data, get_trip_stop_images, plan_visualization.
Not ported: generate_form, the todo tools, deepagents' subagents, skills and file tools.
"""

import asyncio
import json
import os
import sys
import types
from contextvars import ContextVar

from claude_agent_sdk import create_sdk_mcp_server, tool

OIUI_AGENT_DIR = os.environ.get(
    "OIUI_AGENT_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "agent")),
)
if OIUI_AGENT_DIR not in sys.path:
    sys.path.insert(0, OIUI_AGENT_DIR)

# OIUI's `src.credentials` carries browser (BYOK) keys and imports CopilotKit and LangSmith. This
# agent has no browser keys: Jev uses the server's TYPESAFE_API_KEY, exactly what OIUI does when
# `current_credentials` is None. A stand-in module with only that variable lets the router and the
# tools be imported without CopilotKit.
if "src.credentials" not in sys.modules:
    _shim = types.ModuleType("src.credentials")
    _shim.current_credentials = ContextVar("provider_credentials", default=None)
    sys.modules["src.credentials"] = _shim

from src.plan import plan_visualization  # noqa: E402
from src.prompt import SYSTEM_PROMPT  # noqa: E402,F401
from src.query import query_data  # noqa: E402
from src.trip_images import get_trip_stop_images  # noqa: E402

SERVER_NAME = "oiui"
TOOL_PREFIX = f"mcp__{SERVER_NAME}__"
LANGCHAIN_TOOLS = (query_data, get_trip_stop_images, plan_visualization)


def _schema(lc_tool):
    schema = lc_tool.tool_call_schema.model_json_schema()
    return {
        "type": "object",
        "properties": schema.get("properties", {}),
        "required": schema.get("required", []),
    }


def _as_sdk_tool(lc_tool):
    @tool(lc_tool.name, lc_tool.description, _schema(lc_tool))
    async def run(args):
        try:
            result = await asyncio.to_thread(lc_tool.invoke, args)
        except Exception as error:  # A tool's own error message is for the model; never a traceback.
            return {"content": [{"type": "text", "text": f"{type(error).__name__}: {error}"}], "is_error": True}
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {"content": [{"type": "text", "text": text}]}

    return run


def oiui_server():
    return create_sdk_mcp_server(SERVER_NAME, "1.0.0", tools=[_as_sdk_tool(t) for t in LANGCHAIN_TOOLS])


def oiui_tool_names():
    return {f"{TOOL_PREFIX}{t.name}" for t in LANGCHAIN_TOOLS}
