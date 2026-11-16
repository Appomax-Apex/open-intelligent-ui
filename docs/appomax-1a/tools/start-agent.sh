#!/usr/bin/env bash
# Same agent environment as scripts/run-1a.sh, plus measurement proxies (usage on :8899, CONNECT host log on :8898).
set -euo pipefail
cd /workspaces/copilotkit-pilot/open-intelligent-ui/apps/agent
export PATH="$HOME/.local/bin:$PATH"
export DO_NOT_TRACK=1 COPILOTKIT_TELEMETRY_DISABLED=1 COPILOTKIT_TELEMETRY_SAMPLE_RATE=0
export SCARF_ANALYTICS=false NEXT_TELEMETRY_DISABLED=1 TURBO_TELEMETRY_DISABLED=1 LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
unset NEXT_PUBLIC_POSTHOG_KEY OPENAI_API_KEY ANTHROPIC_API_KEY TYPESAFE_API_KEY MCP_SERVER_URL
export ANTHROPIC_BASE_URL=http://127.0.0.1:8899
export HTTPS_PROXY=http://127.0.0.1:8898 HTTP_PROXY=http://127.0.0.1:8898 https_proxy=http://127.0.0.1:8898 http_proxy=http://127.0.0.1:8898
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
ANTHROPIC_API_KEY="$OIUI_ANTHROPIC_KEY" TYPESAFE_API_KEY="$JEV_TYPESAFE_KEY" LLM_MODEL=claude-sonnet-5-5 JEV_MODEL=jev-latest \
  exec uv run uvicorn main:app --host 127.0.0.1 --port 8123
