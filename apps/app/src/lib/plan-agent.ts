/**
 * Appomax: the Claude plan agent (apps/agent-claude), selected with OIUI_AGENT=claude.
 *
 * Server-only. The shared secret (OIUI_AGENT_SECRET, a random value the run script makes) goes to
 * the agent on every request from this app's server and never to a browser.
 */
export const AGENT_SECRET_HEADER = "x-oiui-agent-secret";

export type PlanAgent = { url: string; headers: Record<string, string> };

export function planAgent(env: NodeJS.ProcessEnv = process.env): PlanAgent | null {
  if (env.OIUI_AGENT !== "claude") return null;
  const secret = env.OIUI_AGENT_SECRET?.trim();
  if (!secret) throw new Error("OIUI_AGENT=claude needs OIUI_AGENT_SECRET");
  return {
    url: (env.CLAUDE_AGENT_URL || "http://127.0.0.1:8124").replace(/\/$/, ""),
    headers: { [AGENT_SECRET_HEADER]: secret },
  };
}
