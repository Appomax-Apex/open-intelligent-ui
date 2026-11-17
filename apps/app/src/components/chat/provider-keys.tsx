// Adapted from CopilotKit/OpenIntelligentUI@8391a94 apps/app/src/components/chat/provider-keys.tsx (MIT, Copyright (c) Atai Barkai). Changes: hasKeys is true when NEXT_PUBLIC_OIUI_SERVER_KEYS=1 (server keys); with NEXT_PUBLIC_OIUI_PLAN_SIGNIN=1 hasKeys is whether the agent is signed in with a Claude plan (planSignIn, signedIn, setSignedIn, refreshSignIn); a failed status check keeps the last answer and retries, and focus re-checks.
"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type ProviderKeys = { openai: string; jev: string };
type ProviderKeysContextValue = {
  headers: Record<string, string> | undefined;
  hasKeys: boolean;
  session: number;
  save: (keys: ProviderKeys) => void;
  clear: () => void;
  newChat: () => void;
  draft: string;
  setDraft: (value: string) => void;
  keysOpen: boolean;
  setKeysOpen: (value: boolean) => void;
  /** Appomax: the app runs on the Claude plan agent; the gate is its sign-in, not browser keys. */
  planSignIn: boolean;
  signedIn: boolean;
  setSignedIn: (value: boolean) => void;
  refreshSignIn: () => Promise<void>;
};
const ProviderKeysContext = createContext<ProviderKeysContextValue | null>(null);

/**
 * Appomax: a private deployment where the agent holds the provider keys (server keys). Set at build time; the chat then
 * sends without browser keys, and the agent answers with its own key. Browser keys still override when entered.
 */
const SERVER_KEYS = process.env.NEXT_PUBLIC_OIUI_SERVER_KEYS === "1";
/** Appomax: set at build time when the app runs on the Claude plan agent (scripts/run-plan.sh). */
export const PLAN_SIGNIN = process.env.NEXT_PUBLIC_OIUI_PLAN_SIGNIN === "1";

export function ProviderKeysProvider({ children }: { children: ReactNode }) {
  // Deliberately memory-only: never put credentials in browser storage or agent state.
  const [keys, setKeys] = useState<ProviderKeys | null>(null);
  const [session, setSession] = useState(0);
  const [draft, setDraft] = useState("");
  const [keysOpen, setKeysOpen] = useState(false);
  const newChat = () => { setDraft(""); setSession((value) => value + 1); };
  const [signedIn, setSignedIn] = useState(false);
  const refreshSignIn = useCallback(async () => {
    if (!PLAN_SIGNIN) return;
    // A failed check (a tunnel hiccup, an HTML error page) keeps the last answer and retries; only the
    // agent's own answer changes it.
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const response = await fetch("/api/plan-signin/status", { cache: "no-store" });
        const data = await response.json();
        if (response.ok && typeof data?.signedIn === "boolean") {
          setSignedIn(data.signedIn);
          return;
        }
      } catch {
        // retry below
      }
      await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)));
    }
  }, []);
  useEffect(() => {
    void refreshSignIn();
    const onFocus = () => { void refreshSignIn(); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refreshSignIn]);
  return (
    <ProviderKeysContext.Provider value={{
      headers: keys ? { "x-openai-api-key": keys.openai, "x-jev-api-key": keys.jev } : undefined,
      hasKeys: PLAN_SIGNIN ? signedIn : SERVER_KEYS || keys !== null,
      session,
      save: (value) => { setKeys(value); setKeysOpen(false); setSession((value) => value + 1); },
      clear: () => { setKeys(null); newChat(); },
      newChat, draft, setDraft, keysOpen, setKeysOpen,
      planSignIn: PLAN_SIGNIN, signedIn, setSignedIn, refreshSignIn,
    }}>
      {children}
    </ProviderKeysContext.Provider>
  );
}

export function useProviderKeys() {
  const value = useContext(ProviderKeysContext);
  if (!value) throw new Error("ProviderKeysProvider is required");
  return value;
}
