"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AuthHydrator } from "./auth-hydrator";
import { AuthenticatedContent } from "./authenticated-content";

function RestoredNavigation({ destination }: { destination: import("next").Route }) {
  const router = useRouter();
  useEffect(() => { router.replace(destination); }, [destination, router]);
  return <p role="status" className="p-8 text-sm text-slate-600">Opening your workspace…</p>;
}

export function SessionRestorationPage({ destination }: { destination: import("next").Route }) {
  return <><AuthHydrator /><AuthenticatedContent>
    <RestoredNavigation destination={destination} />
  </AuthenticatedContent></>;
}
