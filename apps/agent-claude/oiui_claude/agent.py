# Adapted from Appomax-Apex/openbot@68fe3277 agent-claude-sdk/src/adapter.py (MIT, Copyright (c) 2026 CopilotKit). Changes: an OIUI subclass of its adapter; the model-endpoint PreToolUse hook widened to the in-process `oiui` tools; Jev routing, OIUI system prompt, plan token env and isolated Claude Code config.
"""Open Intelligent UI's agent on the Claude Agent SDK, signed in with a Claude plan.

OpenBot's adapter (adapter.py, replay.py) does the AG-UI work: each query replays the thread, the
browser's tools (generateSandboxedUi, barChart, A2UI, ...) are offered through the `ag_ui` MCP
server and handed back to the browser. On top of it, this adds what OIUI's LangGraph agent had:

- OIUI's system prompt;
- Jev's per-turn visualization decision (routing.py): its note goes into the system prompt and the
  render tools it did not choose are not offered;
- OIUI's backend tools as the in-process `oiui` MCP server (oiui_tools.py);
- the plan token, from memory, with an isolated CLAUDE_CONFIG_DIR (credential.py).

Claude Code's built-in tools are all off (no Bash, Read, Write, Web*, Agent...): `tools=[]`, no
settings files, strict MCP config, and a PreToolUse hook that denies anything but this run's
browser tools and the `oiui` tools.
"""

import logging
import os

from ag_ui.core import RunErrorEvent, RunStartedEvent
from claude_agent_sdk import HookMatcher

from . import oiui_tools, routing
from .adapter import AG_UI_TOOL_PREFIX, OpenBotClaudeAgentAdapter
from .credential import plan

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5-5"
NOT_SIGNED_IN = "Sign in with Claude first: this app runs on your Claude plan."


def model_name():
    return (os.environ.get("OIUI_MODEL") or DEFAULT_MODEL).strip()


class OIUIClaudeAdapter(OpenBotClaudeAgentAdapter):
    def __init__(self, credential=plan, router=None, **kwargs):
        super().__init__(
            name="oiui",
            # The model endpoint mode: no forwarded props (the browser cannot change the model or
            # the budget), no shared state tool, no built-in tools.
            model_only=True,
            options={"model": model_name(), "system_prompt": oiui_tools.SYSTEM_PROMPT},
            **kwargs,
        )
        self._credential = credential
        self._router = router or routing.JevRouter()
        self._notes = {}

    async def run(self, input_data):
        thread_id, run_id = input_data.thread_id, input_data.run_id
        if not self._credential.signed_in:
            yield RunStartedEvent(thread_id=thread_id, run_id=run_id)
            yield RunErrorEvent(message=NOT_SIGNED_IN, code="OIUI_NOT_SIGNED_IN")
            return
        try:
            decision = await self._router.decision(thread_id, input_data.messages)
        except ValueError as error:  # OIUI's router words its own failures for the person.
            yield RunStartedEvent(thread_id=thread_id, run_id=run_id)
            yield RunErrorEvent(message=str(error), code="OIUI_JEV_FAILED")
            return
        kept, note = routing.apply(decision, [t.name for t in input_data.tools or []])
        self._notes[thread_id] = note
        input_data = input_data.model_copy(
            update={
                "forwarded_props": {},
                "tools": [t for t in input_data.tools or [] if t.name in kept],
            }
        )
        async for event in super().run(input_data):
            yield event

    def build_options(self, input_data=None, thread_id=None):
        options = super().build_options(input_data, thread_id)
        options.model = model_name()
        note = self._notes.get(thread_id, "")
        if note and isinstance(options.system_prompt, str):
            options.system_prompt = options.system_prompt + note
        # The plan token and an isolated Claude Code config; never an API key (credential.py
        # removed every one from this process's environment at start).
        options.env = {**(options.env or {}), **self._credential.run_env()}
        options.cwd = self._credential.work_dir
        options.tools = []
        options.setting_sources = []
        options.strict_mcp_config = True
        options.permission_mode = "dontAsk"
        options.mcp_servers = {**(options.mcp_servers or {}), oiui_tools.SERVER_NAME: oiui_tools.oiui_server()}
        options.allowed_tools = [*options.allowed_tools, f"{oiui_tools.TOOL_PREFIX}*"]
        offered = {f"{AG_UI_TOOL_PREFIX}{t.name}" for t in (input_data.tools if input_data else None) or []}
        offered |= oiui_tools.oiui_tool_names()

        async def only_offered(hook_input, tool_use_id, context):
            if hook_input.get("tool_name") in offered:
                return {}
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Only this app's tools can be used here.",
                }
            }

        options.hooks["PreToolUse"] = [HookMatcher(hooks=[only_offered])]
        return options

    def forget(self, thread_id):
        self._notes.pop(thread_id, None)
