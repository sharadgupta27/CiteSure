import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { setAuthToken, setUnauthorizedHandler, type Schemas } from "../api/client";
import { fetchMe, login as apiLogin, register as apiRegister } from "../api/hooks";

type User = Schemas["User"];

interface AuthValue {
  user: User | null;
  /** True while the stored token is being validated at startup. */
  loading: boolean;
  signIn: (email: string, password: string, createAccount: boolean) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);
const STORAGE_KEY = "citesure.token";

// localStorage can be blocked (private windows, strict settings): the app must still work for the session.
function readStoredToken(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}
function storeToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(STORAGE_KEY, token);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(() => readStoredToken() !== null);

  const signOut = useCallback(() => {
    setAuthToken(null);
    storeToken(null);
    setUser(null);
    queryClient.clear(); // never keep one user's answers or documents in memory for the next login
  }, [queryClient]);

  useEffect(() => {
    setUnauthorizedHandler(signOut);
    return () => setUnauthorizedHandler(null);
  }, [signOut]);

  useEffect(() => {
    const stored = readStoredToken();
    if (!stored) return;
    setAuthToken(stored);
    fetchMe()
      .then(setUser)
      .catch(() => {
        setAuthToken(null);
        storeToken(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const signIn = useCallback(async (email: string, password: string, createAccount: boolean) => {
    const response = await (createAccount ? apiRegister(email, password) : apiLogin(email, password));
    setAuthToken(response.access_token);
    storeToken(response.access_token);
    setUser(response.user);
  }, []);

  const value = useMemo(() => ({ user, loading, signIn, signOut }), [user, loading, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
