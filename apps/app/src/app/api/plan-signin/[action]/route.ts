/**
 * Appomax: the "Sign in with Claude" screen's server side. Proxies to the Claude plan agent's
 * /signin routes with the shared secret, which the browser never sees.
 *
 *   GET  /api/plan-signin/status          -> { signedIn, since }
 *   POST /api/plan-signin/start           -> { url }   (the page to approve the request on)
 *   POST /api/plan-signin/code  { code }  -> { signedIn, since }
 *   POST /api/plan-signin/signout         -> { signedIn: false }
 *
 * Only the fields named above are passed back; the plan token never leaves the agent. A POST must
 * carry `x-oiui-signin: 1`, which a page on another site cannot send without a CORS preflight that
 * this route never answers, so another site cannot start or end a sign-in.
 */
import { planAgent } from "@/lib/plan-agent";

const reply = (body: object, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
const AGENT_PATHS: Record<string, string> = { start: "/signin/start", code: "/signin/code", signout: "/signout" };

async function call(path: string, init: RequestInit = {}, timeoutMs = 30_000) {
  const agent = planAgent();
  if (!agent) return reply({ error: "This app is not set up to sign in with Claude." }, 404);
  try {
    const response = await fetch(`${agent.url}${path}`, {
      ...init,
      headers: { ...agent.headers, ...(init.body ? { "Content-Type": "application/json" } : {}) },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(timeoutMs),
    });
    const data = await response.json().catch(() => ({}));
    const body: Record<string, unknown> = {};
    if (typeof data.signedIn === "boolean") body.signedIn = data.signedIn;
    if (typeof data.since === "number" || data.since === null) body.since = data.since;
    if (typeof data.url === "string" && data.url.startsWith("https://")) body.url = data.url;
    if (!response.ok) body.error = typeof data.error === "string" ? data.error : "The sign-in did not work. Try again.";
    return reply(body, response.ok ? 200 : response.status === 401 ? 502 : response.status);
  } catch {
    return reply({ error: "Could not reach the agent. Try again." }, 502);
  }
}

export async function GET(_request: Request, { params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  if (action !== "status") return reply({ error: "Not found" }, 404);
  return call("/signin/status");
}

export async function POST(request: Request, { params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  if (request.headers.get("x-oiui-signin") !== "1") return reply({ error: "Forbidden" }, 403);
  const path = AGENT_PATHS[action];
  if (!path) return reply({ error: "Not found" }, 404);
  if (action !== "code") return call(path, { method: "POST" }, 120_000);
  const body = await request.json().catch(() => null);
  const code = typeof body?.code === "string" ? body.code.trim() : "";
  if (!code || code.length > 4096) return reply({ error: "Paste the code your browser showed you." }, 400);
  // The agent waits for Anthropic to exchange the code (up to two minutes).
  return call(path, { method: "POST", body: JSON.stringify({ code }) }, 180_000);
}
