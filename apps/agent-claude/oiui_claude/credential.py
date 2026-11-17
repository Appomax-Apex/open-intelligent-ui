# Adapted from Appomax-Apex/openbot@68fe3277 agent-claude-sdk/src/main.py (MIT, Copyright (c) 2026 CopilotKit). Changes: the plan token lives in process memory (from a sign-in or CLAUDE_PLAN_TOKEN) instead of the environment; ANTHROPIC_API_KEY is removed from this process so no child inherits it; an isolated CLAUDE_CONFIG_DIR for the SDK runs.
"""The one credential this agent runs on: a Claude plan token, held in memory.

Anthropic resolves `ANTHROPIC_API_KEY` ahead of `CLAUDE_CODE_OAUTH_TOKEN`, so a process given both
silently bills the key and the plan goes unused. This agent runs on the plan only:

- It refuses to start when an API key and a plan token are both in its environment.
- It takes `ANTHROPIC_API_KEY` (and the other ways to point Claude Code at a key) out of its own
  environment at start, so the Claude Code process the SDK spawns, which inherits `os.environ`,
  can never see one.
- The plan token is never left in the environment either. It is held here, in memory, and handed
  to each SDK run in `ClaudeAgentOptions.env` only.
"""

import os
import tempfile
import threading
import time

PLAN_TOKEN_PREFIX = "sk" + "-ant-oat"

# Environment names that would make Claude Code use something other than the plan token.
API_CREDENTIALS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
# Names a plan token can arrive under at start.
PLAN_TOKEN_NAMES = ("CLAUDE_PLAN_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
# Secrets of this service itself that no child process needs.
OWN_SECRETS = ("OIUI_AGENT_SECRET",)


class BothCredentials(SystemExit):
    pass


def take_credentials_from_environment(environ=os.environ):
    """Check and empty the environment; return the plan token from it, if any.

    Refuses both an API key and a plan token. Whatever is found is removed from `environ`, so no
    child process inherits it.
    """
    key = (environ.get("ANTHROPIC_API_KEY") or "").strip()
    plan = next(((environ.get(name) or "").strip() for name in PLAN_TOKEN_NAMES if (environ.get(name) or "").strip()), "")
    if key and plan:
        raise BothCredentials(
            "Both ANTHROPIC_API_KEY and a Claude plan token are set. Anthropic prefers the key, "
            "so the plan would be ignored. This agent runs on the plan only: unset ANTHROPIC_API_KEY."
        )
    for name in (*API_CREDENTIALS, *PLAN_TOKEN_NAMES):
        environ.pop(name, None)
    return plan or None


class PlanCredential:
    """The plan token in memory, and when it was set. Never logged, never returned to a browser."""

    def __init__(self):
        self._lock = threading.Lock()
        self._token = None
        self._since = None
        self._listeners = []
        # Claude Code's own config for the SDK runs, never the machine's ~/.claude.
        self.config_dir = tempfile.mkdtemp(prefix="oiui-claude-config-")
        self.work_dir = tempfile.mkdtemp(prefix="oiui-claude-cwd-")

    def __repr__(self):
        return f"PlanCredential(signed_in={self.signed_in})"

    @property
    def signed_in(self):
        return self._token is not None

    @property
    def since(self):
        return self._since

    def set(self, token):
        token = (token or "").strip()
        if not token.startswith(PLAN_TOKEN_PREFIX):
            raise ValueError("That is not a Claude plan token.")
        with self._lock:
            self._token = token
            self._since = time.time()
        self._changed()

    def clear(self):
        with self._lock:
            self._token = None
            self._since = None
        self._changed()

    def on_change(self, listener):
        self._listeners.append(listener)

    def _changed(self):
        for listener in self._listeners:
            listener()

    def run_env(self):
        """What an SDK run's Claude Code process is given on top of the (cleaned) environment."""
        with self._lock:
            token = self._token
        if token is None:
            raise PermissionError("Not signed in with Claude.")
        env = {
            "CLAUDE_CODE_OAUTH_TOKEN": token,
            "CLAUDE_CONFIG_DIR": self.config_dir,
            # Claude Code's own telemetry, error reports, update checks and other non-essential traffic: off.
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
            "DISABLE_AUTOUPDATER": "1",
            "DO_NOT_TRACK": "1",
        }
        # Jev's key is this process's, not Claude Code's: blank it for the child.
        env["TYPESAFE_API_KEY"] = ""
        return env


plan = PlanCredential()
