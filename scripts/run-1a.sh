#!/usr/bin/env bash
# Run Open Intelligent UI as shipped. Keys mapped only inside child processes; telemetry off; 127.0.0.1 only.
# Appomax Build 1A. No app code is changed; this only starts the agent and the app with the right environment.
set -euo pipefail
: "${OIUI_ANTHROPIC_KEY:?room secret OIUI_ANTHROPIC_KEY is not in this runtime}"
: "${JEV_TYPESAFE_KEY:?room secret JEV_TYPESAFE_KEY is not in this runtime}"
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH" COREPACK_ENABLE_DOWNLOAD_PROMPT=0
MODEL="${OIUI_MODEL:-claude-sonnet-5-5}"   # OIUI default is chat-latest (OpenAI); claude-* selects Anthropic
# OIUI launch telemetry (docs/telemetry.md), Next.js telemetry, LangSmith tracing: all off.
export DO_NOT_TRACK=1 COPILOTKIT_TELEMETRY_DISABLED=1 COPILOTKIT_TELEMETRY_SAMPLE_RATE=0
export NEXT_TELEMETRY_DISABLED=1 TURBO_TELEMETRY_DISABLED=1 LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
# @scarf/scarf (a CopilotKit dependency) reports installs; DO_NOT_TRACK=1 already stops it, this says so explicitly.
export SCARF_ANALYTICS=false
unset NEXT_PUBLIC_POSTHOG_KEY OPENAI_API_KEY ANTHROPIC_API_KEY TYPESAFE_API_KEY MCP_SERVER_URL
pnpm install --frozen-lockfile
# The app imports @repo/design-system from its dist/, which only the app's own build script builds: build it first.
pnpm --filter @repo/design-system build
(cd apps/agent && uv sync)
LOG=.oiui-1a-logs; mkdir -p "$LOG"
# Production mode by default: `next dev` compiles each page on first request and needs more memory than this runtime's
# ~6 GB cgroup leaves (it was OOM-killed mid-compile). OIUI_DEV=1 runs the dev server instead.
if [ "${OIUI_DEV:-0}" = 1 ]; then APP_CMD="pnpm exec next dev -H 127.0.0.1 -p 3000"; else
  (cd apps/app && env LANGGRAPH_DEPLOYMENT_URL=http://127.0.0.1:8123 pnpm exec next build) >"$LOG/app-build.log" 2>&1
  APP_CMD="pnpm exec next start -H 127.0.0.1 -p 3000"
fi
# Agent: the keys exist only in this child's environment (apps/agent reads os.environ; no .env file is written).
( cd apps/agent && exec env ANTHROPIC_API_KEY="$OIUI_ANTHROPIC_KEY" TYPESAFE_API_KEY="$JEV_TYPESAFE_KEY" \
    LLM_MODEL="$MODEL" JEV_MODEL=jev-latest \
    uv run uvicorn main:app --host 127.0.0.1 --port 8123 ) >"$LOG/agent.log" 2>&1 &
AGENT=$!
# App: no keys. RATE_LIMIT_ENABLED is read by apps/app/src/app/api/copilotkit/route.ts.
( cd apps/app && exec env LANGGRAPH_DEPLOYMENT_URL=http://127.0.0.1:8123 RATE_LIMIT_ENABLED=false \
    $APP_CMD ) >"$LOG/app.log" 2>&1 &
APP=$!
trap 'kill $AGENT $APP 2>/dev/null' EXIT INT TERM
echo "1A up: forward port 3000 privately. Logs in $LOG/."
wait
