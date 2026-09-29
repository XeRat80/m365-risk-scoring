"use client";

import {useCallback, useMemo, useState, useSyncExternalStore} from "react";

export type Session = {
  token: string;
  tenant: string;
  role: "admin" | "analyst";
};

const SESSION_KEY = "m365-risk-session";
const SESSION_EVENT = "m365-risk-session-change";

function subscribe(onStoreChange: () => void) {
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(SESSION_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(SESSION_EVENT, onStoreChange);
  };
}

function read() {
  return window.localStorage.getItem(SESSION_KEY);
}

function parse(value: string | null): Session | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as Partial<Session>;
    if (
      typeof parsed.token !== "string" ||
      typeof parsed.tenant !== "string" ||
      (parsed.role !== "admin" && parsed.role !== "analyst")
    ) {
      return null;
    }
    return parsed as Session;
  } catch {
    return null;
  }
}

export function useRiskSession() {
  const serialized = useSyncExternalStore(subscribe, read, () => null);
  const stored = useMemo(() => parse(serialized), [serialized]);
  const [override, setOverride] = useState<Session | null>();
  const session = override === undefined ? stored : override;

  const login = useCallback((token: string, tenant: string, role: string) => {
    const next = {token, tenant, role: role === "admin" ? "admin" : "analyst"} satisfies Session;
    window.localStorage.setItem(SESSION_KEY, JSON.stringify(next));
    setOverride(next);
    window.dispatchEvent(new Event(SESSION_EVENT));
  }, []);

  const logout = useCallback(() => {
    window.localStorage.removeItem(SESSION_KEY);
    setOverride(null);
    window.dispatchEvent(new Event(SESSION_EVENT));
  }, []);

  return {session, login, logout};
}
