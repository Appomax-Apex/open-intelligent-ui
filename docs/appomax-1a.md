# Appomax 1A: Open Intelligent UI as shipped, 10 test prompts

Run on 2026-11-16 against the fork at upstream 8391a94 (branch `appomax/1a-run`). No app code was changed. Per-prompt data: [appomax-1a/record.csv](appomax-1a/record.csv). Screenshots: `appomax-1a/shots/<nn>-1440.png` and `<nn>-390.png`. Measurement tools: `appomax-1a/tools/`.

## How it was run

- **Script:** the environment of `scripts/run-1a.sh`. The agent and app were started from equivalent wrappers (`tools/start-agent.sh`, `tools/start-app.sh`) so that measurement proxies could be added to the agent.
- **Model:** `claude-sonnet-5-5` (Anthropic) for the agent, through the server key (`LLM_MODEL`). Jev (`jev-latest`, api.typesafe.ai) chose the visualization type.
- **Telemetry off:**
  - `DO_NOT_TRACK=1`, `COPILOTKIT_TELEMETRY_DISABLED=1`, `COPILOTKIT_TELEMETRY_SAMPLE_RATE=0`.
  - `NEXT_TELEMETRY_DISABLED=1`, `SCARF_ANALYTICS=false`.
  - LangSmith tracing off.
  - `NEXT_PUBLIC_POSTHOG_KEY` unset.
- **Network:** everything bound to 127.0.0.1. There was no tunnel and no public URL.
- **Run-mode change, not a code change:** the app ran as a production build (`next build`, then `next start -H 127.0.0.1 -p 3000`). With other work running on the box, `next dev` (and the first `next build` attempts) were killed for lack of memory (cgroup limit 5.97 GB). The owner approved production mode. On the idle box the build passed first time and nothing more was killed.
- **Build prerequisite:** `@repo/design-system` must be built first (`pnpm --filter @repo/design-system build`). Without it the app fails with `Can't resolve '@repo/design-system'`. `run-1a.sh` now does this.
- **Sending prompts (harness, not app code):**
  - As shipped, the chat blocks every send until the user types OpenAI and Jev keys into the "API keys" dialog (`components/chat/key-gated-chat-view.tsx`), even when the server has keys.
  - A BYOK session would also switch the model to OpenAI `chat-latest`.
  - Keys must not be entered there. So the Playwright harness calls CopilotKit's own submit handler (the `onSubmitMessage` that the gate wraps). That is the same call the chat makes after the gate, and the server's Claude key is used.
  - Prompts 1–5 use the `prompt` text from `demo-data.ts` verbatim.
  - Each prompt ran in a new browser context, which is a new chat.
- **Measurement:**
  - **Tokens:** a local pass-through proxy on `ANTHROPIC_BASE_URL` (127.0.0.1:8899) logs only the model name and the `usage` block of each response.
  - **Agent's outbound HTTPS:** a CONNECT proxy (`HTTPS_PROXY`, 127.0.0.1:8898) logs only host, port and bytes.
  - **Connections:** `ss -tnp` snapshots every 3 s.
  - **Browser:** Playwright logs every request to a host other than 127.0.0.1. It times AG-UI events by tee-ing the `/api/copilotkit` stream in the page: first `TEXT_MESSAGE_CONTENT` or `TOOL_CALL_*`, and `RUN_FINISHED` or `RUN_ERROR`.
  - **Screenshots** were taken 15 s after the run ended.
- **Prices** (claude-api skill), per million tokens: $2 input, $10 output, $2.50 cache write (5 min), $0.10 cache read.

## Results

| # | Prompt | Display | Result | Cost | TTFT / total |
|---|---|---|---|---|---|
| 01 | demo-pitch-roll-yaw | sandbox | **failed**, nothing rendered | $0.350 | 3.5 s / 253.6 s |
| 02 | split | sandbox | **failed**, nothing rendered | $0.088 | 41.5 s / 48.2 s |
| 03 | trip | sandbox | **failed**, nothing rendered | $0.260 | 4.2 s / 220.0 s |
| 04 | map | sandbox (map) | **failed**: photos fetched, no map | $0.182 | 2.8 s / 111.4 s |
| 05 | probability | sandbox | **failed**, nothing rendered | $0.119 | 66.3 s / 80.4 s |
| 06 | weekly OEE table | text | answered: asks for data, no table | $0.040 | 3.6 s / 6.5 s |
| 06b | chart availability (follow-up) | none | **failed**: Anthropic 400 | $0.000 | – / 1.9 s |
| 07 | downtime Pareto | text | answered: asks for data, no chart | $0.038 | 3.0 s / 6.0 s |
| 08 | energy trend | text | answered: asks for data, no chart | $0.040 | 3.8 s / 6.9 s |
| 09 | bearing-set calculator | sandbox | **failed**, nothing rendered | $0.201 | 3.3 s / 125.5 s |
| 10 | recycle compression flow | sandbox | **failed**, nothing rendered | $0.195 | 3.9 s / 106.5 s |

"Total" is time until `RUN_FINISHED` or `RUN_ERROR`. For the failed sandbox runs that is the moment the error appeared.

## What worked

- **App and agent:** the production build, the app, the agent, Jev routing and the Claude calls all ran.
- **Outbound traffic:** server-side, only the expected provider hosts were contacted. No request went to telemetry.copilotkit.ai, PostHog, LangSmith or Scarf.
- **No invented plant data (06, 07, 08):**
  - The model said it has no MES, historian, CMMS or meter data for K-401 or the compressor area.
  - It asked for data, or offered a template clearly labelled as illustrative.
  - It invented no numbers. The 1A expectation ("a table/chart of invented numbers") did not happen; the model declined instead.
- **Tool calls before the failure:**
  - `read_file` of the agent's `advanced-visualization` skill (01, 03, 04, 09, 10).
  - `get_trip_stop_images` (04): 6 Wikipedia + 6 Wikimedia Commons lookups, server-side.

## What failed

1. **Every sandbox visual (01–05, 09, 10).**
   - Jev routed to Open Generative UI and the model streamed a `generateSandboxedUi` call, between 5k and 27k output tokens.
   - In the AG-UI stream every `TOOL_CALL_ARGS` delta arrived **twice**. Seen in the browser, e.g. `{"initi`, `{"initi`, `alHeigh`, `alHeigh`.
   - As a result:
     - The runtime logged `[OpenGenerativeUI] JSON parse error in streaming args`, and the sandbox never rendered.
     - The client's follow-up run sent the corrupted tool call back. The agent crashed in `ag_ui_langgraph` `agui_messages_to_langchain` with `JSONDecodeError: Extra data`, the socket closed, and the UI showed "Something interrupted the answer".
   - This is the Claude path through LangGraph and AG-UI. The template's default is OpenAI. No three.js, Leaflet, USGS tiles or CDN library was ever loaded.
2. **Multi-turn (06b).**
   - The second turn of the same chat got an Anthropic 400: "Invalid `signature` in `thinking` block. The block is bound to a different conversation … The `system` prompt and the `tools` list both differ."
   - Jev appends a per-turn note to the system prompt and filters the tool list per turn. Sonnet 5.5's preserved thinking rejects the earlier thinking block because of that. Every follow-up turn in a chat will fail this way.
3. **Send is blocked without BYOK keys.** As shipped, a user cannot use the server's Claude key from the UI at all (see How it was run).
4. **Display is not as expected.** 06, 07 and 08 gave text, not a table or chart. I did not record Jev's decision for these turns; the model asked for the missing data instead of drawing.

## Cost per turn

11 turns (10 prompts plus the 06 follow-up). 16 Anthropic calls; 1 returned HTTP 400.

- **Mean:** $0.137 per turn.
- **Max:** $0.350 (01).
- **Total:** **$1.51** for Anthropic.
- **By turn type:**
  - Sandbox attempts: $0.09–0.35 each, all wasted, because the output was never shown.
  - Text answers: about $0.04 each, about 17k input tokens each.
- **No prompt caching:** cache reads were 0 throughout. Each call pays for the roughly 17k-token system prompt and tool list again.
- **Jev (TypeSafe):** 11 calls, one per user turn. The cost is not measured: its URL is hard-coded in the agent and the call is TLS, so only the calls were counted.

## What is sent outside

| Host | From | What, when | User data? |
|---|---|---|---|
| api.anthropic.com | agent (Python) | Every model call: system prompt, tools, full chat history; 16 calls | **Yes**: prompts and history |
| api.typesafe.ai (Jev) | agent | Once per user turn, about 3 KB up: the last 4 messages, up to 6,000 characters each, to choose the visualization | **Yes**: prompt text |
| en.wikipedia.org, commons.wikimedia.org | agent | Prompt 04 only: page-summary and image-metadata lookups for the trip stops (Wikimedia, via text-lb.eqsin) | Place names chosen by the model |
| fonts.googleapis.com, fonts.gstatic.com | browser | Every page load (layout.tsx) | No prompt data; normal browser metadata (IP address, user agent) |

- **Not seen:** telemetry.copilotkit.ai, PostHog, LangSmith, Scarf. The Next.js server made no outbound connection at all.
- **Not exercised, because no sandbox rendered:**
  - The sandbox CSP allows cdnjs.cloudflare.com, esm.sh, cdn.jsdelivr.net and unpkg.com for scripts.
  - It allows basemap.nationalmap.gov, upload.wikimedia.org and thumb.wikimedia.org for images.
  - Expect those hosts once rendering works.

## Notes for 1B

- **Tool-argument streaming:**
  - Duplicated argument deltas make large tool-call arguments unusable on Claude in this stack.
  - A native build must assemble tool-call arguments once and check the JSON before acting on it.
  - It should not trust a client to send the tool call back.
- **Keep the system prompt and tools fixed across turns.**
  - Put per-turn routing hints in a later system or user message, not in the top-level system prompt or the tool list.
  - Otherwise Sonnet 5.5 rejects the second turn because of preserved thinking. This also gives prompt caching, which is $0.10 instead of $2 per million on the roughly 17k repeated tokens.
- **Cost of generated sandboxes:** the model writes the whole widget as tool output, 5k–27k tokens and 50–250 s per visual. Before the first visible event, TTFT reached 41–66 s when no skill file was read first.
- **Plant questions:** with no data tool, the model correctly refused to invent values. 1B needs real data tools for OEE, downtime and energy, or these stay text.
- **The UI's key gate and the BYOK switch to OpenAI** must go in a server-key deployment.
- **Memory:** `next dev` does not fit next to other work in a ~6 GB runtime; production build and start do.
- **Outbound list for an on-premises build:** Anthropic, TypeSafe, Wikipedia/Wikimedia (trip photos), Google Fonts (self-host them), plus the CDN and tile hosts above.
