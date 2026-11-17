import { describe, expect, it } from "vitest";
import { buildRuntimeOptions } from "../copilotkit-runtime-options";
import { planAgent } from "../plan-agent";

describe("Claude plan agent selection", () => {
  it("keeps the LangGraph agent unless OIUI_AGENT=claude", () => {
    expect(planAgent({ NODE_ENV: "test" } as NodeJS.ProcessEnv)).toBeNull();
    expect(planAgent({ NODE_ENV: "test", OIUI_AGENT: "langgraph" } as NodeJS.ProcessEnv)).toBeNull();
  });
  it("needs the shared secret and defaults to 127.0.0.1:8124", () => {
    expect(() => planAgent({ NODE_ENV: "test", OIUI_AGENT: "claude" } as NodeJS.ProcessEnv)).toThrow();
    expect(planAgent({ NODE_ENV: "test", OIUI_AGENT: "claude", OIUI_AGENT_SECRET: "s" } as NodeJS.ProcessEnv)).toEqual({
      url: "http://127.0.0.1:8124", headers: { "x-oiui-agent-secret": "s" },
    });
  });
  it("gives the agent its secret header and no browser keys", () => {
    const options = buildRuntimeOptions({ langgraphUrl: "http://127.0.0.1:8124", agentHeaders: { "x-oiui-agent-secret": "s" } });
    const agent = options.agents.default as unknown as { url: string; headers: Record<string, string> };
    expect(agent.url).toBe("http://127.0.0.1:8124");
    expect(agent.headers).toEqual({ "x-oiui-agent-secret": "s" });
  });
});
