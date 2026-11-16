"""The plan token is the only credential: both refused, the API key never reaches Claude Code."""

import os

import pytest

from oiui_claude import credential
from oiui_claude.credential import BothCredentials, plan, take_credentials_from_environment

from .conftest import FAKE_TOKEN, SECRET


def test_refuses_an_api_key_and_a_plan_token_together():
    env = {"ANTHROPIC_API_KEY": "sk-ant-api03-key", "CLAUDE_PLAN_TOKEN": FAKE_TOKEN}
    with pytest.raises(SystemExit) as refused:
        take_credentials_from_environment(env)
    assert isinstance(refused.value, BothCredentials)
    assert "sk-ant" not in str(refused.value)


def test_refuses_an_api_key_with_the_oauth_variable_too():
    with pytest.raises(BothCredentials):
        take_credentials_from_environment({"ANTHROPIC_API_KEY": "k", "CLAUDE_CODE_OAUTH_TOKEN": FAKE_TOKEN})


def test_start_up_refuses_both(monkeypatch):
    from oiui_claude import main

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-key")
    monkeypatch.setenv("CLAUDE_PLAN_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("OIUI_AGENT_SECRET", SECRET)
    with pytest.raises(SystemExit):
        main._start_up()


def test_an_api_key_alone_is_removed_and_never_used():
    env = {"ANTHROPIC_API_KEY": "sk-ant-api03-key", "ANTHROPIC_BASE_URL": "https://x", "PATH": "/bin"}
    assert take_credentials_from_environment(env) is None
    assert env == {"PATH": "/bin"}


def test_the_plan_token_is_taken_out_of_the_environment():
    env = {"CLAUDE_PLAN_TOKEN": f"  {FAKE_TOKEN}\n"}
    assert take_credentials_from_environment(env) == FAKE_TOKEN
    assert env == {}


def test_start_up_signs_in_from_the_room_secret_and_cleans_the_environment(monkeypatch):
    from oiui_claude import main

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_PLAN_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("OIUI_AGENT_SECRET", SECRET)
    assert main._start_up() == SECRET
    assert plan.signed_in
    for name in ("CLAUDE_PLAN_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "OIUI_AGENT_SECRET"):
        assert name not in os.environ


def test_a_non_plan_token_is_refused():
    with pytest.raises(ValueError):
        plan.set("sk-ant-api03-not-a-plan-token")
    assert not plan.signed_in


def test_repr_never_shows_the_token():
    plan.set(FAKE_TOKEN)
    assert FAKE_TOKEN not in repr(plan)


def test_run_env_needs_a_sign_in():
    with pytest.raises(PermissionError):
        plan.run_env()


def _claude_code_env(options):
    """The environment the SDK starts Claude Code with (subprocess_cli.py: os.environ, then options.env)."""
    return {**{k: v for k, v in os.environ.items() if k != "CLAUDECODE"}, **options.env}


def test_the_sdk_process_gets_the_plan_token_and_no_api_key(monkeypatch):
    from ag_ui.core import RunAgentInput, UserMessage

    from oiui_claude.agent import OIUIClaudeAdapter

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-key")
    take_credentials_from_environment()  # what start-up does
    plan.set(FAKE_TOKEN)
    adapter = OIUIClaudeAdapter()
    run = RunAgentInput(
        thread_id="t", run_id="r", state=None, tools=[], context=[], forwarded_props={},
        messages=[UserMessage(id="u1", role="user", content="hi")],
    )
    options = adapter.build_options(run, "t")
    env = _claude_code_env(options)
    assert "ANTHROPIC_API_KEY" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == FAKE_TOKEN
    assert env["CLAUDE_CONFIG_DIR"] == plan.config_dir
    assert os.path.expanduser("~") not in env["CLAUDE_CONFIG_DIR"]
    # Built-in tools off; only this app's MCP servers.
    assert options.tools == []
    assert options.setting_sources == []
    assert set(options.mcp_servers) == {"oiui"}
    assert options.model == "claude-sonnet-5-5"
