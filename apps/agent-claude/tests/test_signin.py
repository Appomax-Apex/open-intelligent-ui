"""The sign-in drives `claude setup-token` in a pty: here a fake CLI that prints a link, reads a code
and prints a token. The real CLI is never run."""

import os

import pytest
from fastapi.testclient import TestClient

from oiui_claude import signin
from oiui_claude.credential import plan
from oiui_claude.main import SECRET_HEADER, create_app
from oiui_claude.signin import SignInError, SigningIn

from .conftest import FAKE_TOKEN, SECRET

URL = "https://claude.ai/oauth/authorize?code=true&client_id=fake&state=abc123&code_challenge=xyz"


def test_parsing_takes_the_hyperlink_target_not_the_wrapped_text():
    out = f"\x1b]8;;{URL}\x07{URL[:30]}\r\n{URL[30:]}\x1b]8;;\x07"
    assert signin.authorize_url_in(out) == URL
    assert signin.authorize_url_in("Opening browser…") is None


def test_parsing_sees_a_cursor_positioned_prompt_and_a_refusal():
    assert signin.wants_the_code("Paste\x1b[7Gcode\x1b[12Ghere\x1b[17Gif prompted >")
    assert not signin.wants_the_code("Opening browser")
    assert signin.refused_the_code("OAuth\x1b[7Gerror:\x1b[14GInvalid")


def test_parsing_finds_the_token_by_prefix_only_at_a_word_start():
    assert signin.token_in(f"token:\x1b[32m{FAKE_TOKEN}\x1b[0m\n") == FAKE_TOKEN
    assert signin.token_in(f"x{FAKE_TOKEN}") is None
    assert signin.token_in("sk-ant-oat01-short") is None


def test_a_full_sign_in_with_the_fake_cli(fake_cli):
    signing = SigningIn()
    assert signing.link(patience=20) == URL
    assert signing.finish("  good-code\n", patience_for_prompt=20, patience_for_token=20) == FAKE_TOKEN
    assert not signing.running
    assert not os.path.exists(signing._home)


def test_a_refused_code_says_so(fake_cli):
    signing = SigningIn()
    signing.link(patience=20)
    with pytest.raises(SignInError, match="refused"):
        signing.finish("bad-code", patience_for_prompt=20, patience_for_token=20)
    assert not signing.running


def test_the_cli_gets_no_credential(fake_cli, monkeypatch):
    # The fake exits without a link when any of these reach it, or when HOME is not its own.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-key")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("OIUI_AGENT_SECRET", SECRET)
    signing = SigningIn()
    assert signing.link(patience=20) == URL
    signing.stop()


def test_a_cli_that_prints_no_link_fails_cleanly(tmp_path, monkeypatch):
    silent = tmp_path / "claude"
    silent.write_text("#!/bin/sh\nexit 1\n")
    silent.chmod(0o755)
    monkeypatch.setenv("OIUI_CLAUDE_CLI", str(silent))
    with pytest.raises(SignInError, match="never offered a link"):
        SigningIn().link(patience=5)


class _Adapter:
    name = "fake"
    interrupted = 0

    async def interrupt(self, thread_id=None):
        self.interrupted += 1

    async def shutdown(self):
        pass

    async def run(self, input_data):
        if False:
            yield None


@pytest.fixture
def client():
    adapter = _Adapter()
    with TestClient(create_app(SECRET, adapter=adapter)) as client:
        client.adapter = adapter
        yield client


def headers():
    return {SECRET_HEADER: SECRET}


def test_routes_refuse_without_the_shared_secret(client):
    assert client.get("/health").status_code == 200
    for method, path in [("get", "/signin/status"), ("post", "/signin/start"), ("post", "/signout"), ("post", "/")]:
        assert getattr(client, method)(path).status_code == 401
        assert getattr(client, method)(path, headers={SECRET_HEADER: "wrong"}).status_code == 401


def test_sign_in_over_http_keeps_the_token_in_memory(client, fake_cli):
    assert client.get("/signin/status", headers=headers()).json() == {"signedIn": False, "since": None}
    started = client.post("/signin/start", headers=headers())
    assert started.json() == {"url": URL}
    done = client.post("/signin/code", json={"code": "good-code"}, headers=headers())
    assert done.status_code == 200 and done.json()["signedIn"] is True
    assert FAKE_TOKEN not in done.text
    status = client.get("/signin/status", headers=headers())
    assert status.json()["signedIn"] is True and FAKE_TOKEN not in status.text
    assert plan.run_env()["CLAUDE_CODE_OAUTH_TOKEN"] == FAKE_TOKEN
    assert client.adapter.interrupted == 1  # runs restart on the new credential
    assert client.post("/signout", headers=headers()).json()["signedIn"] is False
    assert not plan.signed_in


def test_a_code_without_a_started_sign_in_is_refused(client):
    assert client.post("/signin/code", json={"code": "good-code"}, headers=headers()).status_code == 409


def test_a_refused_code_over_http(client, fake_cli):
    client.post("/signin/start", headers=headers())
    refused = client.post("/signin/code", json={"code": "bad"}, headers=headers())
    assert refused.status_code == 400 and "refused" in refused.json()["error"]
    assert not plan.signed_in
