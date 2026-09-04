// Minimal Studio auth state for C1-T9.
//
// The server remains the auth authority: every privileged Studio API call
// requires HTTP Basic credentials and the server enforces them (401 +
// Basic realm challenge, fail-closed 503 when unconfigured). This context
// only holds the administrator's credentials for the tab session
// (sessionStorage: survives reloads and Studio deep-links, cleared when the
// tab closes, never localStorage) so the Studio shell can attach
// `Authorization: Basic ...` to its own fetches. Credentials are never
// logged and never used for any authorization decision in the browser.

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { basicAuthHeader } from "./basic-auth";

export interface StudioStatus {
  schema: string;
  version: string;
  admin_user: string;
  upstream: { reachable: boolean };
}

const toBasic = basicAuthHeader;

interface StudioAuth {
  username: string | null;
  login: (username: string, password: string) => Promise<StudioStatus>;
  logout: () => void;
  authHeader: () => string | null;
  authedFetch: (path: string) => Promise<StudioStatus>;
}

const StudioAuthContext = createContext<StudioAuth | null>(null);

const STORAGE_KEY = "chronicle.studio-credentials";

function readStored(): { username: string; password: string } | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { username?: unknown; password?: unknown };
    if (typeof parsed.username === "string" && typeof parsed.password === "string") {
      return { username: parsed.username, password: parsed.password };
    }
    return null;
  } catch {
    return null;
  }
}

export function StudioAuthProvider({ children }: { children: ReactNode }) {
  const [credentials, setCredentials] = useState<{ username: string; password: string } | null>(() =>
    typeof sessionStorage === "undefined" ? null : readStored(),
  );

  const login = useCallback(async (username: string, password: string): Promise<StudioStatus> => {
    const response = await fetch("/api/v1/studio/status", {
      method: "GET",
      headers: { Accept: "application/json", Authorization: toBasic(username, password) },
      credentials: "same-origin",
    });
    if (!response.ok) {
      let code = "request_failed";
      try {
        const payload = (await response.json()) as { error?: { code?: string } };
        if (payload?.error?.code) code = payload.error.code;
      } catch {
        // Keep the transport-level code; the body was unusable.
      }
      throw new Error(code === "unauthorized" ? "unauthorized" : `studio status HTTP ${response.status}`);
    }
    const status = (await response.json()) as StudioStatus;
    setCredentials({ username, password });
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ username, password }));
    } catch {
      // Session persistence is best-effort; the in-memory credentials above
      // still authenticate this page lifetime.
    }
    return status;
  }, []);

  const logout = useCallback(() => {
    setCredentials(null);
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // Already logged out in memory; storage cleanup is best-effort.
    }
  }, []);

  const authHeader = useCallback(
    () => (credentials ? toBasic(credentials.username, credentials.password) : null),
    [credentials],
  );

  const authedFetch = useCallback(
    async (path: string): Promise<StudioStatus> => {
      const header = credentials ? toBasic(credentials.username, credentials.password) : null;
      const response = await fetch(path, {
        method: "GET",
        headers: {
          Accept: "application/json",
          ...(header ? { Authorization: header } : {}),
        },
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error(`studio request HTTP ${response.status}`);
      return (await response.json()) as StudioStatus;
    },
    [credentials],
  );

  const value = useMemo<StudioAuth>(
    () => ({
      username: credentials?.username ?? null,
      login,
      logout,
      authHeader,
      authedFetch,
    }),
    [credentials, login, logout, authHeader, authedFetch],
  );
  return <StudioAuthContext.Provider value={value}>{children}</StudioAuthContext.Provider>;
}

export function useStudioAuth(): StudioAuth {
  const auth = useContext(StudioAuthContext);
  if (!auth) throw new Error("useStudioAuth must be used inside StudioAuthProvider");
  return auth;
}

export { basicAuthHeader } from "./basic-auth";
