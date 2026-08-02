"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { ROUTES } from "@/constants/routes";
import { canManageGcApp } from "@/lib/utils/role-access";
import { selectHasHydrated, selectUser, useAuthStore } from "@/stores/auth.store";
import { GcAppAgencyScopeProvider } from "./gc-app-agency-scope";

export const GC_APP_SECTION_LINKS = [
  {
    label: "Client Manager Accounts",
    href: ROUTES.dashboard.gcAppClientManagerAccounts,
  },
  {
    label: "App Controls",
    href: ROUTES.dashboard.gcAppAppControls,
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
    <div className="space-y-6">
      <nav aria-label="GC App" className="overflow-x-auto border-b border-slate-200">
        <ul className="flex min-w-max gap-6" role="list">
          {GC_APP_SECTION_LINKS.map((link) => {
            const isActive = pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <li key={link.href}>
                <Link
                  href={link.href as never}
                  aria-current={isActive ? "page" : undefined}
                  className={`block border-b-2 px-1 pb-3 text-sm font-medium transition-colors motion-reduce:transition-none ${
                    isActive
                      ? "border-blue-600 text-blue-700"
                      : "border-transparent text-slate-600 hover:border-slate-300 hover:text-slate-900"
                  }`}
                >
                  {link.label}
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
