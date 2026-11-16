// Adapted from CopilotKit/OpenIntelligentUI@8391a94 apps/app/src/components/chat/provider-keys.tsx (MIT, Copyright (c) Atai Barkai). Changes: hasKeys is true when NEXT_PUBLIC_OIUI_SERVER_KEYS=1 (server keys).
"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

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
};
const ProviderKeysContext = createContext<ProviderKeysContextValue | null>(null);

/**
 * Appomax: a private deployment where the agent holds the provider keys (server keys). Set at build time; the chat then
 * sends without browser keys, and the agent answers with its own key. Browser keys still override when entered.
 */
const SERVER_KEYS = process.env.NEXT_PUBLIC_OIUI_SERVER_KEYS === "1";

export function ProviderKeysProvider({ children }: { children: ReactNode }) {
  // Deliberately memory-only: never put credentials in browser storage or agent state.
  const [keys, setKeys] = useState<ProviderKeys | null>(null);
  const [session, setSession] = useState(0);
  const [draft, setDraft] = useState("");
  const [keysOpen, setKeysOpen] = useState(false);
  const newChat = () => { setDraft(""); setSession((value) => value + 1); };
  return (
    <ProviderKeysContext.Provider value={{
      headers: keys ? { "x-openai-api-key": keys.openai, "x-jev-api-key": keys.jev } : undefined,
      hasKeys: SERVER_KEYS || keys !== null,
      session,
      save: (value) => { setKeys(value); setKeysOpen(false); setSession((value) => value + 1); },
      clear: () => { setKeys(null); newChat(); },
      newChat, draft, setDraft, keysOpen, setKeysOpen,
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
