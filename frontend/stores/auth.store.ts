/**
 * Auth Store
 * ==========
 * Holds only in-memory user state. Access and refresh tokens are stored in
 * backend-issued httpOnly cookies and are not readable by JavaScript.
 */

import { create } from "zustand";
import type { User } from "@/types";
import {
  clearServerSessionCookies,
  clearSensitiveBrowserState,
  prepareSensitiveBrowserStateForUser,
  type SensitiveStateResetReason,
} from "@/features/auth/services/session-state";

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  hasHydrated: boolean;
  sessionVersion: number;
}

interface AuthActions {
  setSession: (user: User) => void;
  clearSession: (
    reason?: SensitiveStateResetReason,
    options?: {
      notifyOtherTabs?: boolean;
      revokeServerSession?: boolean;
    },
  ) => Promise<void>;
  markHydrated: () => void;
  updateUser: (user: Partial<User>) => void;
}

const initialState: AuthState = {
  user: null,
  isAuthenticated: false,
  hasHydrated: false,
  sessionVersion: 0,
};

export const useAuthStore = create<AuthState & AuthActions>()((set, get) => ({
  ...initialState,

  setSession: (user) => {
    prepareSensitiveBrowserStateForUser(user.id);
    set((state) => ({
      user,
      isAuthenticated: true,
      hasHydrated: true,
      sessionVersion: state.sessionVersion + 1,
    }));
  },

  clearSession: async (
    reason = "logout",
    {
      notifyOtherTabs = true,
      revokeServerSession = true,
    } = {},
  ) => {
    set((state) => ({
      user: null,
      isAuthenticated: false,
      hasHydrated: true,
      sessionVersion: state.sessionVersion + 1,
    }));
    await Promise.all([
      revokeServerSession ? clearServerSessionCookies() : Promise.resolve(),
      clearSensitiveBrowserState(reason, notifyOtherTabs),
    ]);

    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      const destination = reason === "session_expired"
        ? "/login?reason=session_expired"
        : "/login";
      window.location.replace(destination);
    }
  },

  markHydrated: () => set({ hasHydrated: true }),

  updateUser: (partial) => {
    const current = get().user;
    if (!current) return;
    if (partial.id && partial.id !== current.id) return;
    set({ user: { ...current, ...partial } });
  },
}));

export const selectUser = (state: AuthState & AuthActions) => state.user;
export const selectIsAuthenticated = (state: AuthState & AuthActions) => state.isAuthenticated;
export const selectHasHydrated = (state: AuthState & AuthActions) => state.hasHydrated;
export const selectUserRole = (state: AuthState & AuthActions) => state.user?.role ?? null;
