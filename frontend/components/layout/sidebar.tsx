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
  ClipboardList,
  Database,
  CalendarCheck,
  UserCheck,
  UserCog,
  BedDouble,
  SendToBack,
  MessageCircle,
  Mail,
  UtensilsCrossed,
  Smartphone,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { useUIStore, selectSidebarCollapsed } from "@/stores/ui.store";
import { ROUTES } from "@/constants/routes";
import { Button } from "@/components/ui";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { BrandLogo } from "@/components/brand/brand-logo";
import { canAccessApplicationPath } from "@/features/auth/config/route-capabilities";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  activePrefixes?: string[];
}

interface SidebarProps {
  mobile?: boolean;
  onNavigate?: () => void;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard",    href: ROUTES.dashboard.root,       icon: LayoutDashboard },
  { label: "My Tour",      href: ROUTES.coordinator,          icon: CalendarCheck },
  { label: "All Groups",   href: ROUTES.dashboard.passports,  icon: FileText },
  { label: "Group Links",  href: ROUTES.dashboard.uploadLinks, icon: Link2 },
  { label: "WhatsApp",     href: ROUTES.dashboard.whatsapp,    icon: MessageCircle },
  { label: "Operations Inbox", href: ROUTES.dashboard.emailIntegrationsInbox, icon: Mail },
  { label: "Documents",    href: ROUTES.dashboard.documents,   icon: SendToBack },
  { label: "Coordinators", href: ROUTES.dashboard.tourOperationsCoordinators, icon: UserCheck },
  { label: "Rooming Lists", href: ROUTES.dashboard.rooming, icon: BedDouble },
  { label: "Menu",          href: ROUTES.dashboard.menu, icon: UtensilsCrossed },
  {
    label: "Tour Ops",
    href: ROUTES.dashboard.tourOperationsGroupAssignments,
    icon: CalendarCheck,
    activePrefixes: [ROUTES.dashboard.tourOperationsGroupAssignments, "/tour-operations/groups"],
  },
  {
    label: "GC App",
    href: ROUTES.dashboard.gcAppClientManagerAccounts,
    icon: Smartphone,
    activePrefixes: [ROUTES.dashboard.gcAppRoot],
  },
  { label: "Manager",      href: ROUTES.dashboard.admin,       icon: Shield },
  { label: "Staff",        href: ROUTES.dashboard.staff,       icon: UserCog },
  { label: "Analytics",    href: ROUTES.dashboard.analytics,   icon: BarChart3 },
  { label: "Audit Logs",   href: ROUTES.dashboard.auditLogs,   icon: ClipboardList },
  { label: "Old Data",     href: ROUTES.dashboard.oldData,     icon: Database },
  { label: "Settings",     href: ROUTES.dashboard.settings,   icon: Settings },
];

export function Sidebar({ mobile = false, onNavigate }: SidebarProps) {
  const pathname        = usePathname();
  const storedCollapsed = useUIStore(selectSidebarCollapsed);
  const isCollapsed     = mobile ? false : storedCollapsed;
  const toggleSidebar   = useUIStore((s) => s.toggleSidebar);
  const user            = useAuthStore(selectUser);
  const visibleItems    = NAV_ITEMS.filter((item) => canAccessApplicationPath(user, item.href));

  return (
    <aside
      className={cn(
        "relative flex h-full flex-col border-r border-slate-200 bg-white",
        "transition-all duration-300 ease-in-out",
        mobile ? "w-full" : isCollapsed ? "w-16" : "w-60"
      )}
      aria-label="Main navigation"
    >
      {/* Brand */}
      <div className="flex h-[60px] shrink-0 items-center justify-center overflow-hidden border-b border-slate-200 px-2">
        <BrandLogo compact={isCollapsed} priority />
      </div>

      {/* Nav Items */}
      <nav className="flex-1 overflow-y-auto py-4">
        <ul className="flex flex-col gap-0.5 px-2" role="list">
          {visibleItems.map((item) => {
            const activePrefixes = item.activePrefixes ?? [item.href];
            const isActive = activePrefixes.some((prefix) => pathname === prefix || pathname.startsWith(prefix + "/"));
            const Icon = item.icon;

            return (
              <li key={item.href}>
                <Link
                  href={item.href as never}
                  onClick={onNavigate}
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
      {!mobile && <div className="border-t border-slate-200 p-2">
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
      </div>}
    </aside>
  );
}
