# Adapted from Appomax-Apex/openbot@68fe3277 agent-claude-sdk/src/main.py (MIT, Copyright (c) 2026 CopilotKit). Changes: one AG-UI endpoint for Open Intelligent UI; the credential check moved to credential.py; the shared-secret header is OIUI's; sign-in routes that drive `claude setup-token` and keep the plan token in memory.
"""Open Intelligent UI's agent on the Claude Agent SDK, on 127.0.0.1:8124.

Every route but /health needs the shared secret the run script gives this process and the app's
server (`x-oiui-agent-secret`), so only the app's server can run the agent or sign it in.

- POST /            AG-UI run (the chat).
- POST /signin/start  starts `claude setup-token` and returns the URL to approve in a browser.
- POST /signin/code   {code}: hands the code to the CLI and waits for the plan token.
- GET  /signin/status {signedIn, since}
- POST /signout       forgets the token.

The token is never returned, logged or written to a file. At start, CLAUDE_PLAN_TOKEN (a room
secret) signs the agent in.
"""

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager

from ag_ui_claude_sdk import add_claude_fastapi_endpoint
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .credential import OWN_SECRETS, plan, take_credentials_from_environment
from .signin import SignInError, SigningIn

logger = logging.getLogger(__name__)
SECRET_HEADER = "x-oiui-agent-secret"
NO_STORE = {"Cache-Control": "no-store"}


def _start_up():
    token = take_credentials_from_environment()
    secret = (os.environ.get("OIUI_AGENT_SECRET") or "").strip()
    for name in OWN_SECRETS:
        os.environ.pop(name, None)
    if len(secret) < 32:
        raise SystemExit("OIUI_AGENT_SECRET (at least 32 characters) is required; scripts/run-plan.sh sets one.")
    if token:
        plan.set(token)
    return secret


def create_app(secret, adapter=None):
    from .agent import OIUIClaudeAdapter

    adapter = adapter or OIUIClaudeAdapter()

    @asynccontextmanager
    async def lifespan(app):
        yield
        if app.state.signing is not None:
            app.state.signing.stop()
        await adapter.shutdown()

    app = FastAPI(lifespan=lifespan)
    app.state.adapter = adapter
    app.state.signing = None
    app.state.signing_lock = asyncio.Lock()

    async def restart_runs():
        # Running queries hold the old credential; new ones read the new one in build_options.
        await adapter.interrupt()

    @app.middleware("http")
    async def only_the_app_server(request: Request, call_next):
        if request.url.path != "/health":
            client = request.client.host if request.client else ""
            offered = (request.headers.get(SECRET_HEADER) or "").strip()
            if client not in ("127.0.0.1", "::1", "testclient") or not hmac.compare_digest(
                offered.encode(), secret.encode()
            ):
                return JSONResponse({"error": "unauthorised"}, status_code=401, headers=NO_STORE)
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"ok": True, "harness": "claude-agent-sdk"}

    @app.get("/signin/status")
    async def status():
        return JSONResponse({"signedIn": plan.signed_in, "since": plan.since}, headers=NO_STORE)

    @app.post("/signin/start")
    async def start():
        async with app.state.signing_lock:
            if app.state.signing is not None:
                await asyncio.to_thread(app.state.signing.stop)
                app.state.signing = None
            try:
                signing = await asyncio.to_thread(SigningIn)
                url = await asyncio.to_thread(signing.link)
            except SignInError as error:
                return JSONResponse({"error": str(error)}, status_code=502, headers=NO_STORE)
            app.state.signing = signing
        return JSONResponse({"url": url}, headers=NO_STORE)

    class Code(BaseModel):
        code: str = Field(min_length=1, max_length=4096)

    @app.post("/signin/code")
    async def code(body: Code):
        async with app.state.signing_lock:
            signing, app.state.signing = app.state.signing, None
            if signing is None:
                return JSONResponse({"error": "Start the sign-in first."}, status_code=409, headers=NO_STORE)
            try:
                token = await asyncio.to_thread(signing.finish, body.code)
                plan.set(token)
            except SignInError as error:
                return JSONResponse({"error": str(error)}, status_code=400, headers=NO_STORE)
            except ValueError:
                return JSONResponse({"error": "The sign-in did not return a Claude plan token. Start it again."}, status_code=400, headers=NO_STORE)
            finally:
                token = None
        await restart_runs()
        return JSONResponse({"signedIn": True, "since": plan.since}, headers=NO_STORE)

    @app.post("/signout")
    async def signout():
        async with app.state.signing_lock:
            if app.state.signing is not None:
                await asyncio.to_thread(app.state.signing.stop)
                app.state.signing = None
        plan.clear()
        await restart_runs()
        return JSONResponse({"signedIn": False, "since": None}, headers=NO_STORE)

    add_claude_fastapi_endpoint(app=app, adapter=adapter, path="/")

    return app


def build():
    """The app, for `uvicorn --factory oiui_claude.main:build`."""
    return create_app(_start_up())
