"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Settings2, Smartphone, Users } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { ROUTES } from "@/constants/routes";
import { OperationsPageHeader } from "@/features/operations/components/operations-workspace-ui";
import { canManageGcApp } from "@/lib/utils/role-access";
import { selectHasHydrated, selectUser, useAuthStore } from "@/stores/auth.store";
import { GcAppAgencyScopeProvider } from "./gc-app-agency-scope";

export const GC_APP_SECTION_LINKS = [
  {
    label: "Client Manager Accounts",
    href: ROUTES.dashboard.gcAppClientManagerAccounts,
    description: "Accounts and group assignments",
    icon: Users,
  },
  {
    label: "App Controls",
    href: ROUTES.dashboard.gcAppAppControls,
    description: "Access, content and publishing",
    icon: Settings2,
  },
] as const;

export function GcAppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const hasHydrated = useAuthStore(selectHasHydrated);
  const user = useAuthStore(selectUser);
  const canAccess = canManageGcApp(user);

  useEffect(() => {
    if (!hasHydrated || user === null || canAccess) return;
    router.replace(
      (user.role === "agency_coordinator"
        ? ROUTES.coordinator
        : ROUTES.dashboard.passports) as never,
    );
  }, [canAccess, hasHydrated, router, user]);

  if (!hasHydrated || !canAccess || !user) return null;

  return (
    <div className="space-y-5">
      <OperationsPageHeader
        title="GC App operations"
        description="Manage client access and publish content to GC App."
        icon={Smartphone}
      />

      <nav aria-label="GC App">
        <ul className="grid grid-cols-1 gap-2 rounded-2xl border border-slate-200 bg-slate-100/70 p-1.5 sm:flex sm:flex-wrap" role="list">
          {GC_APP_SECTION_LINKS.map((link) => {
            const isActive = pathname === link.href || pathname.startsWith(`${link.href}/`);
            const Icon = link.icon;
            return (
              <li key={link.href} className="min-w-0">
                <Link
                  href={link.href as never}
                  aria-current={isActive ? "page" : undefined}
                  className={`flex min-h-12 items-center gap-3 rounded-xl px-4 py-2 text-sm transition-all motion-reduce:transition-none ${
                    isActive
                      ? "bg-white text-slate-950 shadow-sm ring-1 ring-slate-200"
                      : "text-slate-600 hover:bg-white/70 hover:text-slate-900"
                  }`}
                >
                  <Icon className={`h-4 w-4 shrink-0 ${isActive ? "text-blue-600" : "text-slate-400"}`} aria-hidden="true" />
                  <span className="text-left">
                    <span className="block font-semibold">{link.label}</span>
                    <span className="hidden text-[11px] font-normal text-slate-500 sm:block">{link.description}</span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <GcAppAgencyScopeProvider user={user}>{children}</GcAppAgencyScopeProvider>
    </div>
  );
}
