/**
 * Auth Store — Zustand
 * ====================
 * Manages authentication state globally.
 *
 * Responsibilities:
 *   - Store the current user and tokens
 *   - Persist access token to localStorage
 *   - Provide login / logout actions
 *
 * Used by the API client interceptor to inject auth headers.
 * Server Components read session from cookies (Phase 2).
 */

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { User, AuthTokens } from "@/types";

interface AuthState {
  user: User | null;
  tokens: AuthTokens | null;
  isAuthenticated: boolean;
}

interface AuthActions {
  setSession: (user: User, tokens: AuthTokens) => void;
  clearSession: () => void;
  updateUser: (user: Partial<User>) => void;
}

const initialState: AuthState = {
  user: null,
  tokens: null,
  isAuthenticated: false,
};

export const useAuthStore = create<AuthState & AuthActions>()(
  persist(
    (set, get) => ({
      ...initialState,

      setSession: (user, tokens) =>
        set({ user, tokens, isAuthenticated: true }),

      clearSession: () => set(initialState),

      updateUser: (partial) => {
        const current = get().user;
        if (!current) return;
        set({ user: { ...current, ...partial } });
      },
    }),
    {
      name: "passdetection-auth",
      storage: createJSONStorage(() => localStorage),
      // Only persist user identity — tokens are managed server-side in Phase 2
      partialize: (state) => ({
        user: state.user,
        tokens: state.tokens,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);

// ── Selectors (avoid inline selectors in components) ──────────────────────────

export const selectUser = (state: AuthState & AuthActions) => state.user;
export const selectIsAuthenticated = (state: AuthState & AuthActions) =>
  state.isAuthenticated;
export const selectUserRole = (state: AuthState & AuthActions) =>
  state.user?.role ?? null;
