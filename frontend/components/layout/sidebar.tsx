/**
 * Sidebar Navigation — Light Theme
 */

"use client";

import { BrandLogo } from "@/components/brand/brand-logo";
import { ROUTES } from "@/constants/routes";
import { canAccessApplicationPath } from "@/features/auth/config/route-capabilities";
import { useDashboardPreferences } from "@/features/settings/dashboard-preferences";
import { cn } from "@/lib/utils/cn";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import {
  BarChart3,
  BedDouble,
  CalendarCheck,
  ClipboardList,
  Database,
  FileText,
  LayoutDashboard,
  Link2,
  Mail,
  MessageCircle,
  Plug,
  SendToBack,
  Settings,
  Shield,
  Smartphone,
  UserCheck,
  UserCog,
  UtensilsCrossed,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type React from "react";

interface NavItem {
  label: string;
  href: import("next").Route;
  icon: React.ComponentType<{ className?: string }>;
  section: "Workspace" | "Communication" | "Operations" | "Administration";
  activePrefixes?: string[];
}

interface SidebarProps {
  mobile?: boolean;
  onNavigate?: () => void;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: ROUTES.dashboard.root, icon: LayoutDashboard, section: "Workspace" },
  { label: "My Tour", href: ROUTES.coordinator, icon: CalendarCheck, section: "Workspace" },
  { label: "All Groups", href: ROUTES.dashboard.passports, icon: FileText, section: "Workspace" },
  { label: "Group Links", href: ROUTES.dashboard.uploadLinks, icon: Link2, section: "Workspace" },
  { label: "WhatsApp", href: ROUTES.dashboard.whatsapp, icon: MessageCircle, section: "Communication" },
  {
    label: "Operations Inbox",
    href: ROUTES.dashboard.emailIntegrationsInbox,
    icon: Mail,
    section: "Communication",
  },
  { label: "Documents", href: ROUTES.dashboard.documents, icon: SendToBack, section: "Operations" },
  { label: "Rooming Lists", href: ROUTES.dashboard.rooming, icon: BedDouble, section: "Operations" },
  { label: "Menu", href: ROUTES.dashboard.menu, icon: UtensilsCrossed, section: "Operations" },
  {
    label: "Tour Ops",
    href: ROUTES.dashboard.tourOperationsGroupAssignments,
    icon: CalendarCheck,
    section: "Operations",
    activePrefixes: [
      ROUTES.dashboard.tourOperationsGroupAssignments,
      "/tour-operations/groups",
    ],
  },
  { label: "Manager", href: ROUTES.dashboard.admin, icon: Shield, section: "Administration" },
  { label: "MCP", href: ROUTES.dashboard.mcp, icon: Plug, section: "Administration" },
  {
    label: "Coordinators",
    href: ROUTES.dashboard.tourOperationsCoordinators,
    icon: UserCheck,
    section: "Administration",
  },
  {
    label: "GC App",
    href: ROUTES.dashboard.gcAppAppControls,
    icon: Smartphone,
    section: "Administration",
    activePrefixes: [ROUTES.dashboard.gcAppRoot],
  },
  { label: "Staff", href: ROUTES.dashboard.staff, icon: UserCog, section: "Administration" },
  { label: "Analytics", href: ROUTES.dashboard.analytics, icon: BarChart3, section: "Administration" },
  {
    label: "Audit Logs",
    href: ROUTES.dashboard.auditLogs,
    icon: ClipboardList,
    section: "Administration",
  },
  { label: "Old Data", href: ROUTES.dashboard.oldData, icon: Database, section: "Administration" },
  { label: "Settings", href: ROUTES.dashboard.settings, icon: Settings, section: "Administration" },
];

export function Sidebar({ mobile = false, onNavigate }: SidebarProps) {
  const pathname = usePathname();
  const storedCollapsed = useDashboardPreferences(
    (state) => state.sidebarCollapsed,
  );
  const isCollapsed = mobile ? false : storedCollapsed;
  const toggleSidebar = () =>
    useDashboardPreferences
      .getState()
      .update({ sidebarCollapsed: !storedCollapsed });
  const user = useAuthStore(selectUser);
  const visibleItems = NAV_ITEMS.filter((item) =>
    canAccessApplicationPath(user, item.href),
  );

  return (
    <aside
      className={cn(
        "dashboard-sidebar relative flex h-full flex-col bg-[#f4f5f7]",
        "transition-[width] duration-200 ease-out",
        mobile ? "w-full" : isCollapsed ? "w-[76px]" : "w-[248px]",
      )}
      aria-label="Main navigation"
    >
      {/* Brand */}
      <div className="flex h-[76px] shrink-0 items-center justify-center overflow-hidden px-3">
        {mobile ? (
          <BrandLogo priority />
        ) : (
          <button
            type="button"
            onClick={toggleSidebar}
            aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!isCollapsed}
            className="flex h-full w-full cursor-pointer items-center justify-center rounded-lg transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-600"
          >
            <BrandLogo compact={isCollapsed} priority />
          </button>
        )}
      </div>

      {/* Nav Items */}
      <nav className="dashboard-sidebar-scroll min-h-0 flex-1 overflow-y-auto px-1 py-3">
        <ul className="flex flex-col gap-1 px-2" role="list">
          {visibleItems.map((item, index) => {
            const activePrefixes = item.activePrefixes ?? [item.href];
            const isActive = item.href === ROUTES.dashboard.admin ? pathname === item.href : activePrefixes.some(
              (prefix) =>
                pathname === prefix || pathname.startsWith(prefix + "/"),
            );
            const Icon = item.icon;

            return (
              <li key={item.href}>
                {!isCollapsed && visibleItems[index - 1]?.section !== item.section && (
                    <p className="mb-2 mt-5 px-3 text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                      {item.section}
                    </p>
                  )}
                <Link
                  href={item.href}
                  onClick={onNavigate}
                  className={cn(
                    "relative flex min-h-10 items-center gap-3 rounded-lg px-3 py-2.5",
                    "text-[13px] font-medium transition-colors duration-150",
                    isActive
                      ? "bg-white text-slate-950 shadow-[0_1px_3px_0_rgb(15_23_42/0.09)] ring-1 ring-slate-200/70"
                      : "text-slate-500 hover:bg-white/70 hover:text-slate-900",
                  )}
                  aria-current={isActive ? "page" : undefined}
                  aria-label={isCollapsed ? item.label : undefined}
                  title={isCollapsed ? item.label : undefined}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4 shrink-0",
                      isActive ? "text-blue-700" : "text-slate-400",
                    )}
                    aria-hidden="true"
                  />
                  {!isCollapsed && (
                    <span className="truncate">{item.label}</span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

    </aside>
  );
}
