# Adapted from Appomax-Apex/openbot@68fe3277 desktop/src-tauri/src/plan.rs (MIT, Copyright (c) 2026 CopilotKit). Changes: ported from Rust to Python (pty module instead of portable-pty); runs the installed `claude` CLI at its absolute path with its own temporary HOME and CLAUDE_CONFIG_DIR instead of the bundled CLI in a container; no transcript file.
"""Signing in to a Claude plan by driving Anthropic's own `claude setup-token`.

The CLI does the OAuth: it prints the consent URL, takes the code the browser shows back on its
stdin, exchanges it and prints a plan token. It is run under a pty because it draws a terminal
(given plain pipes it writes nothing and waits), with its own empty HOME and CLAUDE_CONFIG_DIR so it
never reads or writes this machine's Claude Code login, and with no API key in its environment.

The parsing is pure and kept apart from the running, because the output of a human-facing CLI is
the thing most likely to change without warning.
"""

import fcntl
import os
import pty
import re
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import threading
import time

from .credential import PLAN_TOKEN_PREFIX

PATIENCE_FOR_THE_LINK = 90.0
PATIENCE_FOR_THE_PERSON = 600.0
PATIENCE_FOR_THE_TOKEN = 120.0

_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_OTHER_ESC = re.compile(r"\x1b[ -/]*[0-~]?")
_OSC8 = re.compile(r"\x1b\]8;[^;\x07\x1b]*;([^\x07\x1b]*)(?:\x07|\x1b\\)")
_TOKEN_CHAR = re.compile(r"[A-Za-z0-9_-]")


class SignInError(Exception):
    """A sentence the person can act on. Never holds the CLI's output."""


def plain(output):
    """Everything the terminal drew, with the escapes taken out."""
    return _OTHER_ESC.sub("", _OSC.sub("", _CSI.sub("", output)))


def authorize_url_in(output):
    """The consent URL, from the OSC-8 hyperlink target, which is intact.

    The visible copy is wrapped to the terminal's width, with line breaks spliced into the query
    string, so a URL read from it opens and then fails. When the CLI prints no hyperlink, a URL that
    is whole on one plain line is accepted.
    """
    for match in _OSC8.finditer(output):
        uri = match.group(1).strip()
        if "/oauth/authorize" in uri:
            return uri
    for line in plain(output).splitlines():
        found = re.search(r"https://\S+/oauth/authorize\?\S+", line)
        if found:
            return found.group(0)
    return None


def _squashed(output):
    # The CLI positions words with cursor escapes rather than spaces, so compare without spaces.
    return "".join(plain(output).split())


def wants_the_code(output):
    return "Pastecodehere" in _squashed(output)


def refused_the_code(output):
    squashed = _squashed(output)
    return "OAuthError:" in squashed or "OAutherror:" in squashed


def token_in(output):
    """The plan token, scanned for by prefix, not by position."""
    text = plain(output)
    start = 0
    while True:
        at = text.find(PLAN_TOKEN_PREFIX, start)
        if at < 0:
            return None
        start = at + 1
        if at > 0 and _TOKEN_CHAR.match(text[at - 1]):
            continue
        end = at
        while end < len(text) and _TOKEN_CHAR.match(text[end]):
            end += 1
        if end - at > 30:
            return text[at:end]


def claude_cli():
    """The installed `claude` CLI, as an absolute path (OIUI_CLAUDE_CLI overrides, for tests)."""
    found = os.environ.get("OIUI_CLAUDE_CLI") or shutil.which("claude")
    if not found:
        raise SignInError("The Claude CLI is not installed on this machine, so the sign-in cannot start.")
    return os.path.realpath(found)


class SigningIn:
    """A sign-in in progress: the CLI is running and waits for the code from the browser."""

    def __init__(self, cli=None):
        self._home = tempfile.mkdtemp(prefix="oiui-claude-signin-")
        config = os.path.join(self._home, ".claude")
        os.makedirs(config, mode=0o700)
        master, slave = pty.openpty()
        # Wide, so neither the URL nor the prompt is wrapped.
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 48, 200, 0, 0))
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self._home,
            "CLAUDE_CONFIG_DIR": config,
            "TERM": "xterm-256color",
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DO_NOT_TRACK": "1",
        }
        try:
            self._process = subprocess.Popen(
                [cli or claude_cli(), "setup-token"],
                stdin=slave, stdout=slave, stderr=slave,
                env=env, cwd=self._home, start_new_session=True, close_fds=True,
            )
        except OSError:
            os.close(master)
            os.close(slave)
            shutil.rmtree(self._home, ignore_errors=True)
            raise SignInError("The sign-in did not start. Try again.") from None
        os.close(slave)
        self._master = master
        self._output = []
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self.started = time.time()

    def _read(self):
        while True:
            try:
                chunk = os.read(self._master, 8192)
            except OSError:
                break
            if not chunk:
                break
            with self._lock:
                self._output.append(chunk.decode("utf-8", "replace"))

    def _seen(self):
        with self._lock:
            return "".join(self._output)

    def _wait_for(self, found, patience):
        began = time.monotonic()
        while time.monotonic() - began < patience:
            value = found(self._seen())
            if value:
                return value
            if self._process.poll() is not None:
                time.sleep(0.15)  # The last write and the exit race; the token is written first.
                return found(self._seen())
            time.sleep(0.1)
        return None

    def link(self, patience=PATIENCE_FOR_THE_LINK):
        url = self._wait_for(authorize_url_in, patience)
        if not url:
            self.stop()
            raise SignInError("The sign-in never offered a link to open. Try again.")
        return url

    def finish(self, code, patience_for_prompt=PATIENCE_FOR_THE_PERSON, patience_for_token=PATIENCE_FOR_THE_TOKEN):
        """Type the code, then wait for the token. Returns the token; always stops the CLI."""
        try:
            if not self._wait_for(lambda seen: wants_the_code(seen) or None, patience_for_prompt):
                raise SignInError("The sign-in stopped before it asked for the code. Start it again.")
            # The code, then Enter as its own keypress after a pause: the CLI turns on bracketed
            # paste, and a return in the same write as a long code is taken as part of the paste.
            os.write(self._master, code.strip().encode())
            time.sleep(0.25)
            os.write(self._master, b"\r")
            outcome = self._wait_for(
                lambda seen: ("token", token_in(seen)) if token_in(seen) else (("refused", None) if refused_the_code(seen) else None),
                patience_for_token,
            )
            if outcome and outcome[0] == "token":
                return outcome[1]
            if outcome:
                raise SignInError("That code was refused. A code works once and not for long: start the sign-in again and paste the fresh code.")
            raise SignInError("That sign-in did not finish. Start it again and approve the request in your browser.")
        finally:
            self.stop()

    def stop(self):
        if self._process.poll() is None:
            try:
                os.killpg(self._process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self._process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self._process.wait()
        try:
            os.close(self._master)
        except OSError:
            pass
        with self._lock:
            self._output.clear()  # It can hold the token.
        shutil.rmtree(self._home, ignore_errors=True)

    @property
    def running(self):
        return self._process.poll() is None
