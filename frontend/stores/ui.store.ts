/**
 * UI Store — Zustand
 * ==================
 * Manages ephemeral UI state that is shared across components
 * but does NOT need to be persisted or fetched from server.
 *
 * Examples: sidebar open/collapsed, global loading indicators.
 */

import { create } from "zustand";

interface UIState {
  isSidebarCollapsed: boolean;
  isGlobalLoading: boolean;
}

interface UIActions {
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setGlobalLoading: (loading: boolean) => void;
}

export const useUIStore = create<UIState & UIActions>((set) => ({
  isSidebarCollapsed: false,
  isGlobalLoading: false,

  toggleSidebar: () =>
    set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed })),

  setSidebarCollapsed: (collapsed) =>
    set({ isSidebarCollapsed: collapsed }),

  setGlobalLoading: (loading) =>
    set({ isGlobalLoading: loading }),
}));

// ── Selectors ─────────────────────────────────────────────────────────────────

export const selectSidebarCollapsed = (s: UIState & UIActions) =>
  s.isSidebarCollapsed;
export const selectGlobalLoading = (s: UIState & UIActions) =>
  s.isGlobalLoading;
