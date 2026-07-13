/**
 * Auth Store
 * ==========
 * Holds only in-memory user state. Access and refresh tokens are stored in
 * backend-issued httpOnly cookies and are not readable by JavaScript.
 */

import { create } from "zustand";
import type { User } from "@/types";

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  hasHydrated: boolean;
}

interface AuthActions {
  setSession: (user: User) => void;
  clearSession: () => void;
  markHydrated: () => void;
  updateUser: (user: Partial<User>) => void;
}

const initialState: AuthState = {
  user: null,
  isAuthenticated: false,
  hasHydrated: false,
};

export const useAuthStore = create<AuthState & AuthActions>()((set, get) => ({
  ...initialState,

  setSession: (user) => set({ user, isAuthenticated: true, hasHydrated: true }),

  clearSession: () => set({ ...initialState, hasHydrated: true }),

  markHydrated: () => set({ hasHydrated: true }),

  updateUser: (partial) => {
    const current = get().user;
    if (!current) return;
    set({ user: { ...current, ...partial } });
  },
}));

export const selectUser = (state: AuthState & AuthActions) => state.user;
export const selectIsAuthenticated = (state: AuthState & AuthActions) => state.isAuthenticated;
export const selectHasHydrated = (state: AuthState & AuthActions) => state.hasHydrated;
export const selectUserRole = (state: AuthState & AuthActions) => state.user?.role ?? null;
