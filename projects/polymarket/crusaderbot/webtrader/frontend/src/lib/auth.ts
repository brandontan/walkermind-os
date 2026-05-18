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
  const [user, setUser] = useState<AuthUser | null>(null);

  const login = useCallback((token: string, userId: string, firstName: string) => {
    // Token is stored in React state only — never localStorage or sessionStorage
    setUser({ token, userId, firstName });
  }, []);

  const logout = useCallback(() => {
    setUser(null);
  }, []);

  return { user, login, logout };
}
