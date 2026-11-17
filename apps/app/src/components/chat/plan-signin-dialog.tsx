// Adapted from CopilotKit/OpenIntelligentUI@8391a94 apps/app/src/components/chat/provider-keys-dialog.tsx (MIT, Copyright (c) Atai Barkai). Changes: a "Sign in with Claude" dialog in the same style: start the sign-in, open the link, paste the code back; wording from Appomax-Apex/openbot@68fe3277 desktop/src/ProviderPicker.tsx (MIT, Copyright (c) 2026 CopilotKit).
"use client";

import { useEffect, useRef, useState } from "react";
import { useProviderKeys } from "./provider-keys";
import "./provider-keys.css";

type Step = "idle" | "starting" | "approve" | "finishing";
const SIGNIN_HEADERS = { "x-oiui-signin": "1" };

async function post(action: string, body?: object, signal?: AbortSignal) {
  const response = await fetch(`/api/plan-signin/${action}`, {
    method: "POST",
    headers: body ? { ...SIGNIN_HEADERS, "Content-Type": "application/json" } : SIGNIN_HEADERS,
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
    signal,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : "The sign-in did not work. Try again.");
  return data;
}

export function PlanSignInDialog({ onClose, disabled = false }: { onClose: () => void; disabled?: boolean }) {
  const { signedIn, setSignedIn, newChat, refreshSignIn } = useProviderKeys();
  const dialog = useRef<HTMLDialogElement>(null);
  const request = useRef<AbortController | null>(null);
  const [step, setStep] = useState<Step>("idle");
  const [url, setUrl] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [justSignedIn, setJustSignedIn] = useState(false);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    // The agent forgets a sign-in when it restarts: ask it, not this page's memory.
    void refreshSignIn();
    return () => {
      request.current?.abort();
      opener?.focus();
    };
  }, [refreshSignIn]);

  const run = async (action: () => Promise<void>) => {
    const controller = new AbortController();
    request.current = controller;
    setError(null);
    try {
      await action();
    } catch (problem) {
      if (!controller.signal.aborted) setError(problem instanceof Error ? problem.message : "The sign-in did not work. Try again.");
    }
    return controller;
  };

  const start = () => run(async () => {
    setStep("starting");
    setUrl(null);
    setCode("");
    try {
      const data = await post("start", undefined, request.current?.signal);
      setUrl(data.url);
      setStep("approve");
    } catch (problem) {
      setStep("idle");
      throw problem;
    }
  });

  const submit = () => run(async () => {
    if (!code.trim()) return;
    setStep("finishing");
    try {
      await post("code", { code: code.trim() }, request.current?.signal);
      setSignedIn(true);
      setJustSignedIn(true);
      setStep("idle");
      setUrl(null);
      setCode("");
    } catch (problem) {
      // A code works once: the sign-in has to start again.
      setStep("idle");
      setUrl(null);
      throw problem;
    }
  });

  const signOut = () => run(async () => {
    await post("signout", undefined, request.current?.signal);
    setSignedIn(false);
    setJustSignedIn(false);
    newChat();
  });

  const busy = step === "starting" || step === "finishing" || disabled;
  return (
    <dialog ref={dialog} className="provider-keys-dialog" aria-labelledby="plan-signin-title" onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <h2 id="plan-signin-title">{signedIn ? "Signed in with Claude" : "Sign in with Claude"}</h2>
      {signedIn ? (
        <p role="status" aria-live="polite">{justSignedIn ? "Signed in with your Claude plan. Your message is ready to send." : "Signed in with your Claude plan."} Answers use your plan’s usage limits.</p>
      ) : (
        <p>This app answers with your Claude plan (Pro or Max). Your sign-in stays on this app’s server, in memory, until it restarts or you sign out.</p>
      )}
      {!signedIn && step === "approve" && url && (
        <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <p>
            <a href={url} target="_blank" rel="noopener noreferrer">Open the Claude sign-in page ↗</a>
          </p>
          <p>Approve the request in your browser, then paste the code it shows you.</p>
          <label htmlFor="plan-signin-code">Code</label>
          <input id="plan-signin-code" type="text" maxLength={4096} autoComplete="off" spellCheck={false} autoCapitalize="none" value={code} onChange={(event) => { setCode(event.target.value); setError(null); }} disabled={busy} />
          {error && <p role="alert">{error}</p>}
          <div className="provider-keys-actions">
            <button type="button" onClick={onClose}>Cancel</button>
            <button type="submit" className="provider-keys-save" disabled={busy || !code.trim()}>Submit</button>
          </div>
        </form>
      )}
      {!signedIn && step === "finishing" && <p role="status" aria-live="polite">Finishing the sign-in…</p>}
      {(signedIn || step === "idle" || step === "starting") && (
        <>
          {error && <p role="alert">{error}</p>}
          {step === "starting" && <p role="status" aria-live="polite">Starting the sign-in…</p>}
          <div className="provider-keys-actions">
            {signedIn && <button type="button" disabled={busy} onClick={() => void signOut()}>Sign out</button>}
            <button type="button" onClick={onClose}>{signedIn ? "Done" : "Cancel"}</button>
            {!signedIn && <button type="button" className="provider-keys-save" disabled={busy} onClick={() => void start()}>Sign in with Claude</button>}
          </div>
        </>
      )}
    </dialog>
  );
}
