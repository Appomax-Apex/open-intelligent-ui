import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const URL = "https://claude.ai/oauth/authorize?code=true&state=abc";

async function setup(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubEnv("NEXT_PUBLIC_OIUI_PLAN_SIGNIN", "1");
  vi.resetModules();
  vi.stubGlobal("fetch", fetchMock);
  const { ProviderKeysProvider, useProviderKeys } = await import("./provider-keys");
  const { PlanSignInDialog } = await import("./plan-signin-dialog");
  function Harness() {
    const { hasKeys } = useProviderKeys();
    return <><output data-testid="gate">{hasKeys ? "open" : "closed"}</output><PlanSignInDialog onClose={() => {}} /></>;
  }
  render(<ProviderKeysProvider><Harness /></ProviderKeysProvider>);
}
const json = (body: object, ok = true) => Promise.resolve({ ok, json: async () => body });

beforeEach(() => { HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); }; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("Sign in with Claude", () => {
  it("shows the link, takes the code and opens the chat gate", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/status")) return json({ signedIn: false, since: null });
      if (url.endsWith("/start")) return json({ url: URL });
      if (url.endsWith("/code")) return json({ signedIn: true, since: 1 });
      throw new Error(url);
    });
    await setup(fetchMock);
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Sign in with Claude");
    expect(screen.getByTestId("gate")).toHaveTextContent("closed");
    fireEvent.click(screen.getByRole("button", { name: "Sign in with Claude" }));
    const link = await screen.findByRole("link", { name: /Open the Claude sign-in page/ });
    expect(link).toHaveAttribute("href", URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.getByText("Approve the request in your browser, then paste the code it shows you.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: " abc#def " } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText(/Signed in with your Claude plan/);
    expect(screen.getByTestId("gate")).toHaveTextContent("open");
    expect(fetchMock).toHaveBeenCalledWith("/api/plan-signin/code", expect.objectContaining({
      method: "POST", body: JSON.stringify({ code: "abc#def" }), headers: { "x-oiui-signin": "1", "Content-Type": "application/json" },
    }));
  });

  it("says a refused code was refused and starts over", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/status")) return json({ signedIn: false, since: null });
      if (url.endsWith("/start")) return json({ url: URL });
      return json({ error: "That code was refused." }, false);
    });
    await setup(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: "Sign in with Claude" }));
    fireEvent.change(await screen.findByLabelText("Code"), { target: { value: "bad" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText("That code was refused.");
    expect(screen.getByTestId("gate")).toHaveTextContent("closed");
    expect(screen.getByRole("button", { name: "Sign in with Claude" })).toBeEnabled();
  });

  it("reads the agent's sign-in when it opens, and signs out", async () => {
    const fetchMock = vi.fn((url: string) => url.endsWith("/status") ? json({ signedIn: true, since: 1 }) : json({ signedIn: false, since: null }));
    await setup(fetchMock);
    await waitFor(() => expect(screen.getByTestId("gate")).toHaveTextContent("open"));
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Signed in with Claude");
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByTestId("gate")).toHaveTextContent("closed"));
  });
});
