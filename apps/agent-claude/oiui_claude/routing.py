# Adapted from CopilotKit/OpenIntelligentUI@8391a94 apps/agent/src/visualization_router.py (MIT, Copyright (c) Atai Barkai). Changes: JevVisualizationMiddleware's per-turn flow re-expressed for AG-UI input (no LangGraph state); the routing, the Jev call and the note are OIUI's own functions, imported and called unchanged.
"""Jev's visualization decision, once per user turn, for the Claude agent.

OIUI's LangGraph middleware asks Jev before the first model call of a turn, keeps the decision in
graph state, then on every model call appends Jev's note to the system prompt and removes the
render tools Jev did not choose. Here the same happens per AG-UI run:

- `routing_input` (OIUI's) decides whether this is a new turn and builds Jev's context;
- `aroute` (OIUI's) asks Jev;
- `routed_request` (OIUI's) builds the note and the filtered tool list from the decision.

The decision is kept per thread, keyed by the turn, so a client-tool continuation of the same turn
gets the same note and the same tools (the adapter restarts a query whose tools changed).
"""

from collections import OrderedDict
from types import SimpleNamespace

from . import oiui_tools  # noqa: F401  (puts OIUI's agent on sys.path first)
from langchain_core.messages import SystemMessage
from src.visualization_router import aroute, routed_request, routing_input

MAX_THREADS = 500
_ROLES = {"user": "human", "assistant": "ai"}


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            getattr(part, "text", None) or (part.get("text") if isinstance(part, dict) else None) or ""
            for part in content
        )
    return ""


def as_langchain_messages(messages):
    """The AG-UI thread in the shape OIUI's `routing_input` reads: `.type`, `.id`, `.content`."""
    return [
        SimpleNamespace(type=_ROLES[m.role], id=m.id, content=_text(m.content))
        for m in messages
        if m.role in _ROLES
    ]


class _Request:
    """Just enough of LangChain's ModelRequest for OIUI's `routed_request`."""

    def __init__(self, decision, tool_names, system=""):
        self.state = {"visualization_decision": decision}
        self.tools = [{"name": name} for name in tool_names]
        self.system_message = SystemMessage(content=system)

    def override(self, tools, system_message):
        routed = _Request(self.state["visualization_decision"], [t["name"] for t in tools])
        routed.system_message = system_message
        return routed


def apply(decision, tool_names):
    """(names of the tools kept, the note for the system prompt), as OIUI's middleware builds them."""
    if not decision:
        return list(tool_names), ""
    routed = routed_request(_Request(decision, tool_names))
    return [t["name"] for t in routed.tools], routed.system_message.content


class JevRouter:
    def __init__(self, route=aroute):
        self._route = route
        self._threads = OrderedDict()

    async def decision(self, thread_id, messages):
        """Jev's decision for this thread's current turn: asked once per turn, then reused."""
        held = self._threads.get(thread_id, {})
        state = {"messages": as_langchain_messages(messages), **held}
        pending = routing_input(state)
        if pending is None:
            return held.get("visualization_decision")
        turn, context = pending
        decision = await self._route(context)
        self._threads[thread_id] = {"visualization_turn": turn, "visualization_decision": decision}
        self._threads.move_to_end(thread_id)
        while len(self._threads) > MAX_THREADS:
            self._threads.popitem(last=False)
        return decision
