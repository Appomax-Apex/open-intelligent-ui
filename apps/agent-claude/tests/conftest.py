import os
from pathlib import Path

import pytest

FAKE_CLI = str(Path(__file__).parent / "fixtures" / "fake_claude")
FAKE_TOKEN = "sk-ant-oat01-FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE_fake-token"
SECRET = "s" * 40


@pytest.fixture(autouse=True)
def clean_plan():
    from oiui_claude.credential import plan

    plan.clear()
    yield
    plan.clear()


@pytest.fixture
def fake_cli(monkeypatch):
    monkeypatch.setenv("OIUI_CLAUDE_CLI", FAKE_CLI)
    return FAKE_CLI
