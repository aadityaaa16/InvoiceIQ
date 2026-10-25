import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { api, refreshAccessToken, tokens, type Role, type User } from "./api";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (form: Record<string, string>) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const loadUser = useCallback(async () => {
    const { data } = await api.get<User>("/auth/me");
    setUser(data);
  }, []);

  const logout = useCallback(() => {
    tokens.clear();
    setUser(null);
  }, []);

  // On page load: the access token (memory) is gone, but a refresh token may exist.
  useEffect(() => {
    (async () => {
      if (tokens.hasRefresh() && (await refreshAccessToken())) await loadUser().catch(logout);
      setLoading(false);
    })();
    window.addEventListener("auth:logout", logout);
    return () => window.removeEventListener("auth:logout", logout);
  }, [loadUser, logout]);

  const login = async (email: string, password: string) => {
    const { data } = await api.post("/auth/login", { email, password });
    tokens.set(data.access_token, data.refresh_token);
    await loadUser();
  };

  const register = async (form: Record<string, string>) => {
    const { data } = await api.post("/auth/register", form);
    tokens.set(data.access_token, data.refresh_token);
    await loadUser();
  };

  return <AuthContext.Provider value={{ user, loading, login, register, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

/** Route guard. The backend enforces roles too; this only hides what users can't use. */
export function RequireAuth({ roles }: { roles?: Role[] }) {
  const { user, loading } = useAuth();
  if (loading) return <p className="center">Loading…</p>;
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />;
  return <Outlet />;
}
