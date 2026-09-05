"use client";

import { Header } from "@/components/layout/header";
import { MobileNavigation } from "@/components/layout/mobile-navigation";
import { Sidebar } from "@/components/layout/sidebar";
import { useDashboardPreferences } from "@/features/settings/dashboard-preferences";
import { useEffect, useState, type ReactNode } from "react";

export function DashboardShell({ children }: { children: ReactNode }) {
  const density = useDashboardPreferences((state) => state.density);
  const contentWidth = useDashboardPreferences((state) => state.contentWidth);
  const textSize = useDashboardPreferences((state) => state.textSize);
  const reduceMotion = useDashboardPreferences((state) => state.reduceMotion);
  useEffect(() => {
    void useDashboardPreferences.persist.rehydrate();
  }, []);
  const [navigationOpen, setNavigationOpen] = useState(false);

  useEffect(() => {
    const desktopViewport = window.matchMedia("(min-width: 1024px)");
    const closeDrawerAtDesktopWidth = () => {
      if (desktopViewport.matches) setNavigationOpen(false);
    };
    closeDrawerAtDesktopWidth();
    desktopViewport.addEventListener("change", closeDrawerAtDesktopWidth);
    return () =>
      desktopViewport.removeEventListener("change", closeDrawerAtDesktopWidth);
  }, []);

  return (
    <div
      className="fixed inset-0 flex min-h-0 w-full overflow-hidden overscroll-none bg-slate-50"
      data-dashboard-shell
      data-density={density}
      data-text-size={textSize}
      data-reduce-motion={reduceMotion}
    >
      <div className="hidden min-h-0 shrink-0 lg:flex">
        <Sidebar />
      </div>
      <MobileNavigation
        open={navigationOpen}
        onClose={() => setNavigationOpen(false)}
      />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <Header
          navigationOpen={navigationOpen}
          onOpenNavigation={() => setNavigationOpen(true)}
        />
        <main
          className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-y-contain"
          id="main-content"
        >
          <div
            className={`dashboard-content mx-auto w-full px-4 py-6 sm:px-7 sm:py-8 xl:px-10 ${contentWidth === "focused" ? "max-w-6xl" : "max-w-[1600px]"}`}
          >
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
