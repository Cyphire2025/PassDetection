"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { ROUTES } from "@/constants/routes";
import { canAccessEmailIntegrations } from "@/lib/utils/role-access";
import {
  selectHasHydrated,
  selectUserRole,
  useAuthStore,
} from "@/stores/auth.store";

const SECTION_LINKS = [
  {
    label: "Operations inbox",
    href: ROUTES.dashboard.emailIntegrationsInbox,
  },
  {
    label: "Review queue",
    href: ROUTES.dashboard.emailIntegrationsReview,
  },
  {
    label: "Activity",
    href: ROUTES.dashboard.emailIntegrationsActivity,
  },
  {
    label: "Connections",
    href: ROUTES.dashboard.emailIntegrations,
  },
] as const;

export function EmailIntegrationsShell({
  children,
}: {
  children: ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const hasHydrated = useAuthStore(selectHasHydrated);
  const role = useAuthStore(selectUserRole);
  const canAccess = canAccessEmailIntegrations(role);

  useEffect(() => {
    if (!hasHydrated || role === null || canAccess) return;
    router.replace(
      (role === "agency_coordinator"
        ? ROUTES.coordinator
        : ROUTES.dashboard.passports) as never,
    );
  }, [canAccess, hasHydrated, role, router]);

  if (!hasHydrated || !canAccess) return null;

  return (
    <div className="space-y-6">
      <nav
        aria-label="Email integrations"
        className="sm:border-b sm:border-slate-200"
      >
        <ul className="grid grid-cols-2 gap-1 sm:flex sm:flex-wrap sm:gap-6" role="list">
          {SECTION_LINKS.map((link) => {
            const isActive =
              link.href === ROUTES.dashboard.emailIntegrations
                ? pathname === link.href
                : pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <li key={link.href} className="min-w-0">
                <Link
                  href={link.href as never}
                  aria-current={isActive ? "page" : undefined}
                  className={`flex min-h-11 items-center border-b-2 px-2 py-2 text-sm font-medium transition-colors sm:px-1 sm:pb-3 ${
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
      {children}
    </div>
  );
}
