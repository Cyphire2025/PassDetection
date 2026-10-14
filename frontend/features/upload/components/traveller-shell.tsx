import type { ReactNode } from "react";
import { LockKeyhole } from "lucide-react";

/** One small, cacheable background; private documents are fetched separately. */
export function TravellerShell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return <main className="traveller-portal min-h-dvh px-4 py-6 sm:px-6 sm:py-10">
    <div className={`mx-auto w-full ${wide ? "max-w-6xl" : "max-w-xl"}`}>{children}</div>
    <p className="mx-auto mt-8 flex items-center justify-center gap-2 text-center text-xs text-slate-500">
      <LockKeyhole className="h-3.5 w-3.5" aria-hidden="true" />Secure document collection by Global Connect Travels
    </p>
  </main>;
}
