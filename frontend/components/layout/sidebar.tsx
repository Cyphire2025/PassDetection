/**
 * Sidebar Navigation — Light Theme
 */

"use client";

import type React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  FileText,
  Link2,
  Settings,
  ChevronLeft,
  ChevronRight,
  Shield,
  BarChart3,
  Bell,
  ClipboardList,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { useUIStore, selectSidebarCollapsed } from "@/stores/ui.store";
import { ROUTES } from "@/constants/routes";
import { Button } from "@/components/ui";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import type { UserRole } from "@/types";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  roles?: UserRole[];
}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard",    href: ROUTES.dashboard.root,       icon: LayoutDashboard },
  { label: "Passports",    href: ROUTES.dashboard.passports,  icon: FileText },
  { label: "Upload Links", href: ROUTES.dashboard.uploadLinks, icon: Link2 },
  { label: "Admin",        href: ROUTES.dashboard.admin,       icon: Shield, roles: ["super_admin", "agency_admin"] },
  { label: "Analytics",    href: ROUTES.dashboard.analytics,   icon: BarChart3, roles: ["super_admin", "agency_admin"] },
  { label: "Audit Logs",   href: ROUTES.dashboard.auditLogs,   icon: ClipboardList, roles: ["super_admin", "agency_admin"] },
  { label: "Notifications", href: ROUTES.dashboard.notifications, icon: Bell },
  { label: "Settings",     href: ROUTES.dashboard.settings,   icon: Settings },
];

export function Sidebar() {
  const pathname        = usePathname();
  const isCollapsed     = useUIStore(selectSidebarCollapsed);
  const toggleSidebar   = useUIStore((s) => s.toggleSidebar);
  const role            = useAuthStore(selectUserRole);
  const visibleItems    = NAV_ITEMS.filter((item) => !item.roles || (role && item.roles.includes(role)));

  return (
    <aside
      className={cn(
        "relative flex h-full flex-col border-r border-slate-200 bg-white",
        "transition-all duration-300 ease-in-out",
        isCollapsed ? "w-16" : "w-60"
      )}
      aria-label="Main navigation"
    >
      {/* Brand */}
      <div className="flex h-[60px] items-center border-b border-slate-200 px-4 shrink-0">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-blue-600">
          <Shield className="h-4 w-4 text-white" aria-hidden="true" />
        </div>
        {!isCollapsed && (
          <span className="ml-2.5 text-sm font-bold text-slate-900 tracking-tight truncate">
            PassDetection
          </span>
        )}
      </div>

      {/* Nav Items */}
      <nav className="flex-1 overflow-y-auto py-4">
        <ul className="flex flex-col gap-0.5 px-2" role="list">
          {visibleItems.map((item) => {
            const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
            const Icon = item.icon;

            return (
              <li key={item.href}>
                <Link
                  href={item.href as never}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2",
                    "text-sm font-medium transition-colors duration-100",
                    isActive
                      ? "bg-blue-50 text-blue-700"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  )}
                  aria-current={isActive ? "page" : undefined}
                  title={isCollapsed ? item.label : undefined}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4 shrink-0",
                      isActive ? "text-blue-600" : "text-slate-400"
                    )}
                    aria-hidden="true"
                  />
                  {!isCollapsed && <span className="truncate">{item.label}</span>}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Collapse Toggle */}
      <div className="border-t border-slate-200 p-2">
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleSidebar}
          className="w-full text-slate-400 hover:text-slate-700"
          aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {isCollapsed
            ? <ChevronRight className="h-4 w-4" aria-hidden="true" />
            : <ChevronLeft  className="h-4 w-4" aria-hidden="true" />}
        </Button>
      </div>
    </aside>
  );
}
