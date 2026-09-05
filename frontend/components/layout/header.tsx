/**
 * Dashboard Header — Light Theme
 */

"use client";

import { Button } from "@/components/ui";
import { useLogout } from "@/features/auth/hooks/use-logout";
import { NotificationBell } from "@/features/notifications/components/notification-bell";
import { GlobalSearch } from "@/features/search/components/global-search";
import { truncate } from "@/lib/utils/format";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { ChevronRight, LogOut, Menu } from "lucide-react";
import { usePathname } from "next/navigation";

interface HeaderProps {
  title?: string;
  navigationOpen?: boolean;
  onOpenNavigation?: () => void;
}

export function Header({
  title,
  navigationOpen = false,
  onOpenNavigation,
}: HeaderProps) {
  const pathname = usePathname();
  const section = pathname.split("/")[1]?.replaceAll("-", " ") ?? "Workspace";
  const user = useAuthStore(selectUser);
  const { mutate: logout } = useLogout();

  const handleLogout = () => {
    logout();
  };

  return (
    <header className="flex h-[68px] shrink-0 items-center justify-between gap-3 border-b border-slate-200/70 bg-white px-4 sm:px-7">
      {/* Page Title — set per-page via Header prop or left empty */}
      <div className="flex min-w-0 items-center gap-2">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onOpenNavigation}
          aria-label="Open navigation"
          aria-expanded={navigationOpen}
          aria-controls="mobile-dashboard-navigation"
          data-mobile-navigation-trigger
          className="shrink-0 text-slate-600 lg:hidden"
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </Button>
        {(title || section) && (
          <div className="hidden items-center gap-2 text-xs sm:flex">
            <span className="text-slate-400">Workspace</span>
            <ChevronRight className="h-3 w-3 text-slate-300" />
            <span className="truncate font-medium capitalize text-slate-700">
              {title || section}
            </span>
          </div>
        )}
      </div>

      <div className="min-w-0 flex-1 justify-center flex">
        <GlobalSearch />
      </div>

      {/* Right actions */}
      <div className="flex items-center gap-2">
        <NotificationBell />
        {user && (
          <div className="flex items-center gap-2.5 px-2 py-1.5">
            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-[10px] font-bold text-white">
              {user.full_name.charAt(0).toUpperCase()}
            </div>
            <div className="hidden sm:block leading-tight">
              <p className="text-xs font-medium text-slate-800">
                {truncate(user.full_name, 22)}
              </p>
              <p className="text-[10px] text-slate-500 capitalize">
                {user.role.replace(/_/g, " ")}
              </p>
            </div>
          </div>
        )}

        <Button
          variant="ghost"
          size="icon"
          onClick={handleLogout}
          aria-label="Sign out"
          className="text-slate-400 hover:text-slate-900"
        >
          <LogOut className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>
    </header>
  );
}
