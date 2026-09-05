"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export interface DashboardPreferences {
  density: "comfortable" | "compact";
  contentWidth: "focused" | "wide";
  textSize: "standard" | "large";
  reduceMotion: boolean;
  sidebarCollapsed: boolean;
}

export const DEFAULT_DASHBOARD_PREFERENCES: DashboardPreferences = {
  density: "comfortable",
  contentWidth: "wide",
  textSize: "standard",
  reduceMotion: false,
  sidebarCollapsed: false,
};

type PreferenceStore = DashboardPreferences & {
  update: (patch: Partial<DashboardPreferences>) => void;
  reset: () => void;
};

/** Only presentation preferences are persisted; never operational records or identity. */
export const useDashboardPreferences = create<PreferenceStore>()(
  persist(
    (set) => ({
      ...DEFAULT_DASHBOARD_PREFERENCES,
      update: (patch) => set(patch),
      reset: () => set(DEFAULT_DASHBOARD_PREFERENCES),
    }),
    {
      name: "passdetection-dashboard-preferences",
      version: 1,
      storage: createJSONStorage(() => localStorage),
      skipHydration: true,
      partialize: ({
        density,
        contentWidth,
        textSize,
        reduceMotion,
        sidebarCollapsed,
      }) => ({
        density,
        contentWidth,
        textSize,
        reduceMotion,
        sidebarCollapsed,
      }),
      merge: (saved, current) => {
        const value = saved as Partial<DashboardPreferences> | undefined;
        return {
          ...current,
          density: value?.density === "compact" ? "compact" : "comfortable",
          contentWidth: value?.contentWidth === "focused" ? "focused" : "wide",
          textSize: value?.textSize === "large" ? "large" : "standard",
          reduceMotion: value?.reduceMotion === true,
          sidebarCollapsed: value?.sidebarCollapsed === true,
        };
      },
    },
  ),
);
