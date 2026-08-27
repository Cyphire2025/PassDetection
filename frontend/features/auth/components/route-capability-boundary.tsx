
"use client";

import { useEffect, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ArrowLeft, ShieldAlert } from "lucide-react";
import {
  canAccessApplicationPath,
  firstAuthorizedPath,
  resolveRouteCapability,
} from "@/features/auth/config/route-capabilities";
import { selectUser, useAuthStore } from "@/stores/auth.store";

export function RouteCapabilityBoundary({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const user = useAuthStore(selectUser);
  const capability = resolveRouteCapability(pathname);
  const canAccess = canAccessApplicationPath(user, pathname);
  const returnPath = user ? firstAuthorizedPath(user) : "/login";

  useEffect(() => {
    // Preserve the established deep-link journey for a known workspace: deny
    // before mounting privileged children, then return the signed-in operator
    // to their first authorized route. Unknown routes keep the explicit
    // fail-closed screen so an undeclared capability cannot be hidden.
    if (!user || !capability || canAccess) return;
    router.replace(returnPath as never);
  }, [canAccess, capability, returnPath, router, user]);

  if (canAccess) return children;

  return (
    <main className="flex min-h-dvh items-center justify-center bg-slate-50 p-5" aria-labelledby="unauthorized-route-heading">
      <section className="w-full max-w-xl rounded-2xl border border-amber-200 bg-white p-6 text-center shadow-sm sm:p-8">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-amber-100 text-amber-800">
          <ShieldAlert className="h-6 w-6" aria-hidden="true" />
        </span>
        <p className="mt-5 text-xs font-semibold uppercase tracking-[0.16em] text-amber-800">Permission boundary</p>
        <h1 id="unauthorized-route-heading" className="mt-2 text-xl font-semibold text-slate-950">This workspace is not available to your current role</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          No privileged data request was started. Your active session may have changed, or this direct link requires a capability that is not assigned to this account.
        </p>
        {!capability && (
          <p className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
            This dashboard route is not registered in the typed capability map and therefore fails closed.
          </p>
        )}
        <Link href={returnPath as never} className="mt-6 inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-700">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Return to an authorized workspace
        </Link>
      </section>
    </main>
  );
}
