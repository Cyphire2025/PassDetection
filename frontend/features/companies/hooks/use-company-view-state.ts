"use client";

import { useCallback } from "react";
import { usePathname, useSearchParams } from "next/navigation";

/** Native history updates keep navigation state without a server-route refresh. */
export function useCompanyViewState() {
  const pathname = usePathname();
  const params = useSearchParams();
  const query = params.toString();
  const update = useCallback((changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    const search = next.toString();
    window.history.replaceState(null, "", `${pathname}${search ? `?${search}` : ""}`);
  }, [pathname]);
  return { params, query, update };
}
