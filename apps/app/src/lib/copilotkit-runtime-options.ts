// Adapted from CopilotKit/OpenIntelligentUI@8391a94 apps/app/src/lib/copilotkit-runtime-options.ts (MIT, Copyright (c) Atai Barkai). Changes: agentHeaders, so the Claude plan agent (an AG-UI endpoint like the LangGraph one) gets the app server's shared secret.
import { LangGraphHttpAgent } from "@copilotkit/runtime/langgraph";

import type { ProviderHeaders } from "./provider-keys";

class CredentialSafeLangGraphAgent extends LangGraphHttpAgent {
  protected override requestInit(input: Parameters<LangGraphHttpAgent["requestInit"]>[0]): RequestInit {
    // Custom credential headers survive cross-origin fetch redirects. Fail closed.
    return { ...super.requestInit(input), redirect: "error" };
  }
}

export interface RuntimeOptionsEnv {
  langgraphUrl?: string;
  mcpServerUrl?: string;
  providerHeaders?: ProviderHeaders;
  /** Appomax: headers for the agent itself (the Claude plan agent's shared secret). Never browser keys. */
  agentHeaders?: Record<string, string>;
}

// Normalize Render's fromService hostport (bare host:port) into a full URL
export function normalizeLanggraphUrl(raw?: string): string {
  if (!raw) return "http://localhost:8123";
  return raw.startsWith("http") ? raw : `http://${raw}`;
}

export function buildRuntimeOptions(env: RuntimeOptionsEnv) {
  return {
    agents: {
      default: new CredentialSafeLangGraphAgent({
        url: normalizeLanggraphUrl(env.langgraphUrl),
        // The class is an AG-UI HttpAgent: it posts RunAgentInput to `url`, which is all the Claude
        // plan agent needs too.
        ...((env.providerHeaders || env.agentHeaders) && { headers: { ...env.providerHeaders, ...env.agentHeaders } }),
      }),
    },
    a2ui: { injectA2UITool: true },
    openGenerativeUI: true as const,
    ...(env.mcpServerUrl && {
      mcpApps: {
        servers: [{
          type: "http" as const,
          url: env.mcpServerUrl,
          serverId: "example_mcp_app",
        }],
      },
    }),
  };
}
