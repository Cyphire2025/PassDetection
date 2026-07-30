/**
 * Dashboard Header — Light Theme
 */

"use client";

import { LogOut } from "lucide-react";
import { useAuthStore, selectUser } from "@/stores/auth.store";
import { useLogout } from "@/features/auth/hooks/use-logout";
import { Button } from "@/components/ui";
import { truncate } from "@/lib/utils/format";
import { GlobalSearch } from "@/features/search/components/global-search";
import { NotificationBell } from "@/features/notifications/components/notification-bell";

interface HeaderProps {
  title?: string;
}

export function Header({ title }: HeaderProps) {
  const user = useAuthStore(selectUser);
  const { mutate: logout } = useLogout();

  const handleLogout = () => {
    logout();
  };


  return (
    <header className="flex h-[60px] shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 sm:px-6">
      {/* Page Title — set per-page via Header prop or left empty */}
      {title && (
        <h1 className="text-sm font-semibold text-slate-900">{title}</h1>
      )}
      {!title && <div />}

      <div className="mx-4 hidden min-w-0 flex-1 justify-center md:flex">
        <GlobalSearch />
      </div>

      {/* Right actions */}
      <div className="flex items-center gap-2">
        <NotificationBell />
        {user && (
          <div className="flex items-center gap-2.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5">
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
