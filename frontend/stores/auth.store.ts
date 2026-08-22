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
import {
  requestQueueSafeSignOutReview,
} from "@/features/auth/services/queue-safe-sign-out-events";
import {
  unavailableBrowserAttendanceQueueSnapshot,
  type AttendanceQueueLogoutDisposition,
} from "@/features/tour-operations/services/attendance-queue-safety-contract";

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
      queueDisposition?: AttendanceQueueLogoutDisposition;
      revokeServerSession?: boolean;
      loginReason?: "password_changed";
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
      queueDisposition = "block",
      revokeServerSession = true,
      loginReason,
    } = {},
  ) => {
    const authentication = get();
    const expectedUserId = authentication.user?.id ?? null;
    const expectedSessionVersion = authentication.sessionVersion;

    const finishSessionClear = async () => {
      const current = get();
      if (
        current.sessionVersion !== expectedSessionVersion
        || current.user?.id !== expectedUserId
      ) {
        return false;
      }
      set((state) => ({
        user: null,
        isAuthenticated: false,
        hasHydrated: true,
        sessionVersion: state.sessionVersion + 1,
      }));
      const cleanup = Promise.all([
        revokeServerSession ? clearServerSessionCookies() : Promise.resolve(),
        clearSensitiveBrowserState(reason, notifyOtherTabs),
      ]);

      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        const params = new URLSearchParams();
        if (reason === "session_expired") params.set("reason", "session_expired");
        if (loginReason) params.set("reason", loginReason);
        if (window.location.pathname.startsWith("/coordinator")) {
          params.set("from", `${window.location.pathname}${window.location.search}`);
        }
        const destination = `/login${params.size > 0 ? `?${params.toString()}` : ""}`;
        window.location.replace(destination);
      }
      await cleanup;
      return true;
    };

    if (reason !== "logout" || !expectedUserId || typeof window === "undefined") {
      await finishSessionClear();
      return;
    }

    try {
      const { runAttendanceQueueLogoutBoundary } = await import(
        "@/features/tour-operations/services/attendance-scan-queue"
      );
      if (
        get().sessionVersion !== expectedSessionVersion
        || get().user?.id !== expectedUserId
      ) {
        return;
      }
      const boundary = await runAttendanceQueueLogoutBoundary(
        expectedUserId,
        queueDisposition,
        finishSessionClear,
      );
      if (!boundary.allowed) requestQueueSafeSignOutReview(boundary.snapshot);
    } catch (error) {
      if (queueDisposition === "discard") throw error;
      requestQueueSafeSignOutReview(
        unavailableBrowserAttendanceQueueSnapshot(expectedUserId),
      );
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
