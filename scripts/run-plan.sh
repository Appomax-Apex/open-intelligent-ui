#!/usr/bin/env bash
# Run Open Intelligent UI on the owner's Claude plan: apps/agent-claude (Claude Agent SDK) on 127.0.0.1:8124 and the
# app in production mode on 127.0.0.1:3000 (APP_PORT to change). Sign in from the app ("Sign in with Claude"), or set
# the room secret CLAUDE_PLAN_TOKEN (from `claude setup-token`) to start signed in.
# Like scripts/run-1a.sh: credentials only inside the child that needs them, telemetry off, 127.0.0.1 only.
set -euo pipefail
: "${JEV_TYPESAFE_KEY:?room secret JEV_TYPESAFE_KEY is not in this runtime}"
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH" COREPACK_ENABLE_DOWNLOAD_PROMPT=0
MODEL="${OIUI_MODEL:-claude-sonnet-5-5}"
APP_PORT="${APP_PORT:-3000}" AGENT_PORT="${AGENT_PORT:-8124}"
# OIUI launch telemetry (docs/telemetry.md), Next.js, Turbo, LangSmith and @scarf/scarf: all off.
export DO_NOT_TRACK=1 COPILOTKIT_TELEMETRY_DISABLED=1 COPILOTKIT_TELEMETRY_SAMPLE_RATE=0
export NEXT_TELEMETRY_DISABLED=1 TURBO_TELEMETRY_DISABLED=1 LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
export SCARF_ANALYTICS=false
# Never a model key in this shell: the agent runs on the plan only, and refuses to start if it is given both.
# CLAUDE_PLAN_TOKEN is read once below, into the agent child only, and unset here.
PLAN_TOKEN="${CLAUDE_PLAN_TOKEN:-}"
unset NEXT_PUBLIC_POSTHOG_KEY OPENAI_API_KEY ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN CLAUDE_CODE_OAUTH_TOKEN \
  CLAUDE_PLAN_TOKEN TYPESAFE_API_KEY MCP_SERVER_URL
# A fresh random secret per start: only the app's server, which is given it, can run the agent or sign it in.
AGENT_SECRET="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
pnpm install --frozen-lockfile
pnpm --filter @repo/design-system build
(cd apps/agent-claude && uv sync --frozen)
LOG=.oiui-plan-logs; mkdir -p "$LOG"
# NEXT_PUBLIC_OIUI_PLAN_SIGNIN=1: the chat sends only when the agent is signed in with a Claude plan.
# Production mode (`next dev` needs more memory than this runtime has). A separate build directory, so a build here
# never replaces the one a running scripts/run-1a.sh app is serving.
export NEXT_DIST_DIR=.next-plan
(cd apps/app && env NEXT_PUBLIC_OIUI_PLAN_SIGNIN=1 pnpm exec next build) >"$LOG/app-build.log" 2>&1
# Agent: the plan token (if any), the shared secret and Jev's key exist only in this child's environment; the agent
# moves the token into memory and out of its environment at start.
( cd apps/agent-claude && exec env ${PLAN_TOKEN:+CLAUDE_PLAN_TOKEN="$PLAN_TOKEN"} OIUI_AGENT_SECRET="$AGENT_SECRET" \
    TYPESAFE_API_KEY="$JEV_TYPESAFE_KEY" JEV_MODEL=jev-latest OIUI_MODEL="$MODEL" \
    uv run --frozen uvicorn --factory oiui_claude.main:build --host 127.0.0.1 --port "$AGENT_PORT" --no-proxy-headers ) >"$LOG/agent.log" 2>&1 &
AGENT=$!
unset PLAN_TOKEN
# App: no model keys; the shared secret to reach the agent. RATE_LIMIT_ENABLED is read by api/copilotkit/route.ts.
( cd apps/app && exec env OIUI_AGENT=claude CLAUDE_AGENT_URL="http://127.0.0.1:$AGENT_PORT" OIUI_AGENT_SECRET="$AGENT_SECRET" \
    RATE_LIMIT_ENABLED=false pnpm exec next start -H 127.0.0.1 -p "$APP_PORT" ) >"$LOG/app.log" 2>&1 &
APP=$!
unset AGENT_SECRET
trap 'kill $AGENT $APP 2>/dev/null' EXIT INT TERM
echo "Plan sign-in build up: forward port $APP_PORT privately, open it, then Sign in with Claude. Logs in $LOG/."
wait
