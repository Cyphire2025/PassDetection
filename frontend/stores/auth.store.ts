/**
 * Auth Store
 * ==========
 * Holds only in-memory user state. Access and refresh tokens are stored in
 * backend-issued httpOnly cookies and are not readable by JavaScript.
 */

import { create } from "zustand";
import { expiredSessionSignInPath } from "@/features/auth/services/restoration-destination";
import type { AccessLevelAgencyChoice, User } from "@/types";
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
  restorationStatus: "restoring" | "authenticated" | "rejected" | "temporarily_unavailable";
  user: User | null;
  isAuthenticated: boolean;
  hasHydrated: boolean;
  sessionVersion: number;
  isChangingAccessLevel: boolean;
  accessLevelError: string | null;
  accessLevelAgencyChoice: AccessLevelAgencyChoice | null;
}

interface AuthActions {
  setAccessLevelAgencyChoice: (choice: AccessLevelAgencyChoice) => void;
  beginAccessLevelChange: () => void;
  failAccessLevelChange: (message: string, confirmedUser?: User) => void;
  markTemporarilyUnavailable: () => void;
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
  restorationStatus: "restoring",
  user: null,
  isAuthenticated: false,
  hasHydrated: false,
  sessionVersion: 0,
  isChangingAccessLevel: false,
  accessLevelError: null,
  accessLevelAgencyChoice: null,
};

export const useAuthStore = create<AuthState & AuthActions>()((set, get) => ({
  ...initialState,

  setAccessLevelAgencyChoice: (choice) => set({ accessLevelAgencyChoice: choice }),

  beginAccessLevelChange: () => set((state) => ({
    isChangingAccessLevel: true,
    accessLevelError: null,
    accessLevelAgencyChoice: null,
    sessionVersion: state.sessionVersion + 1,
  })),

  failAccessLevelChange: (message, confirmedUser) => set((state) => ({
    accessLevelError: message,
    ...(confirmedUser ? {
      user: confirmedUser,
      isChangingAccessLevel: false,
      sessionVersion: state.sessionVersion + 1,
    } : {}),
  })),

  setSession: (user) => {
    prepareSensitiveBrowserStateForUser(user.id);
    set((state) => ({
      user,
      isAuthenticated: true,
      restorationStatus: "authenticated",
      hasHydrated: true,
      sessionVersion: state.sessionVersion + 1,
      isChangingAccessLevel: false,
      accessLevelError: null,
      accessLevelAgencyChoice: null,
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
        || (current.user?.id ?? null) !== expectedUserId
      ) {
        return false;
      }
      set((state) => ({
        user: null,
        isAuthenticated: false,
        restorationStatus: "rejected",
        hasHydrated: true,
        sessionVersion: state.sessionVersion + 1,
        isChangingAccessLevel: false,
        accessLevelError: null,
        accessLevelAgencyChoice: null,
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
        const destination = reason === "session_expired"
          ? expiredSessionSignInPath(window.location.pathname, window.location.search)
          : `/login${params.size > 0 ? `?${params.toString()}` : ""}`;
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
  markTemporarilyUnavailable: () => {
    if (!get().isAuthenticated) {
      set({ restorationStatus: "temporarily_unavailable", hasHydrated: false });
    }
  },

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
