"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { AuthHydrator } from "./auth-hydrator";
import { AuthenticatedContent } from "./authenticated-content";

function RestoredNavigation({ destination }: { destination: string }) {
  const router = useRouter();
  useEffect(() => { router.replace(destination as Route); }, [destination, router]);
  return <p role="status" className="p-8 text-sm text-slate-600">Opening your workspace…</p>;
}

export function SessionRestorationPage({ destination }: { destination: string }) {
  return <><AuthHydrator /><AuthenticatedContent>
    <RestoredNavigation destination={destination} />
  </AuthenticatedContent></>;
}
