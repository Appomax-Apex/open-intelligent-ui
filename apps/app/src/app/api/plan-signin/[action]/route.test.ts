// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "./route";

const SECRET = "x".repeat(40);
const params = (action: string) => ({ params: Promise.resolve({ action }) });
const post = (action: string, body?: object, signin = true) => POST(new Request(`http://localhost/api/plan-signin/${action}`, {
  method: "POST",
  headers: signin ? { "x-oiui-signin": "1" } : {},
  body: body ? JSON.stringify(body) : undefined,
}), params(action));

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("Claude plan sign-in proxy", () => {
  it("is off unless the app runs on the Claude plan agent", async () => {
    vi.stubEnv("OIUI_AGENT", "");
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    expect((await GET(new Request("http://localhost/api/plan-signin/status"), params("status"))).status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("sends the shared secret to the agent only, and passes back only the named fields", async () => {
    vi.stubEnv("OIUI_AGENT", "claude"); vi.stubEnv("OIUI_AGENT_SECRET", SECRET); vi.stubEnv("CLAUDE_AGENT_URL", "http://127.0.0.1:8124/");
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ signedIn: true, since: 1, token: "sk-ant-oat01-should-never-pass" }));
    vi.stubGlobal("fetch", fetchMock);
    const response = await post("code", { code: "  the-code " });
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8124/signin/code", expect.objectContaining({
      method: "POST", body: JSON.stringify({ code: "the-code" }), redirect: "error", cache: "no-store",
      headers: { "x-oiui-agent-secret": SECRET, "Content-Type": "application/json" },
    }));
    const text = await response.text();
    expect(JSON.parse(text)).toEqual({ signedIn: true, since: 1 });
    expect(text).not.toContain("sk-ant");
    expect(text).not.toContain(SECRET);
  });
  it("returns the sign-in URL from start", async () => {
    vi.stubEnv("OIUI_AGENT", "claude"); vi.stubEnv("OIUI_AGENT_SECRET", SECRET);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ url: "https://claude.ai/oauth/authorize?x=1" })));
    expect(await (await post("start")).json()).toEqual({ url: "https://claude.ai/oauth/authorize?x=1" });
  });
  it("refuses a POST without the same-site header, an empty code and unknown actions", async () => {
    vi.stubEnv("OIUI_AGENT", "claude"); vi.stubEnv("OIUI_AGENT_SECRET", SECRET);
    const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
    expect((await post("start", undefined, false)).status).toBe(403);
    expect((await post("code", { code: "  " })).status).toBe(400);
    expect((await post("delete")).status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
