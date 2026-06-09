import { createContext, useCallback, useContext, useState } from "react";

export interface AuthUser {
  token: string;
  userId: string;
  firstName: string;
}

interface AuthContextType {
  user: AuthUser | null;
  login: (token: string, userId: string, firstName: string) => void;
  logout: () => void;
}

const STORAGE_KEY = "crusaderbot_auth";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Decode the `exp` claim from a JWT without verifying the signature. */
function jwtExp(token: string): number | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const decoded = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    return typeof decoded.exp === "number" ? decoded.exp : null;
  } catch {
    return null;
  }
}

/** Return true if the token is still valid (exp > now + 60s buffer). */
function isTokenValid(token: string): boolean {
  const exp = jwtExp(token);
  if (exp === null) return false;
  return exp > Math.floor(Date.now() / 1000) + 60;
}

function saveToStorage(user: AuthUser): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
  } catch {
    // Private browsing or storage quota — silently ignore.
  }
}

function clearStorage(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

/** Load persisted auth from localStorage. Returns null if absent or expired. */
function loadFromStorage(): AuthUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AuthUser;
    if (!parsed.token || !parsed.userId) return null;
    if (!isTokenValid(parsed.token)) {
      clearStorage();
      return null;
    }
    return parsed;
  } catch {
    clearStorage();
    return null;
  }
}

// ── Context ───────────────────────────────────────────────────────────────────

// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext<AuthContextType>({
  user: null,
  login: () => {},
  logout: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

export function useAuthState() {
  // Hydrate from localStorage on first render — user stays logged in across
  // page refreshes until the JWT expires (24h) or they explicitly log out.
  const [user, setUser] = useState<AuthUser | null>(loadFromStorage);

  const login = useCallback((token: string, userId: string, firstName: string) => {
    const next: AuthUser = { token, userId, firstName };
    saveToStorage(next);
    setUser(next);
  }, []);

  const logout = useCallback(() => {
    clearStorage();
    setUser(null);
  }, []);

  return { user, login, logout };
}
