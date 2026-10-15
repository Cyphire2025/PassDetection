import type { ReactNode } from "react";
import { LockKeyhole } from "lucide-react";
import styles from "./traveller-landing.module.css";

/** One small, cacheable background; private documents are fetched separately. */
export function TravellerShell({ children, wide = false, landing = false }: { children: ReactNode; wide?: boolean; landing?: boolean }) {
  return <main data-landing={landing} className={`traveller-portal ${styles.shell} min-h-dvh px-4 py-6 sm:px-6 sm:py-10`}>
    <div className={`${styles.content} mx-auto w-full ${wide ? "max-w-6xl" : "max-w-xl"}`}>{children}</div>
    <p className={`${styles.footer} mx-auto mt-8 flex items-center justify-center gap-2 text-center text-xs text-slate-500`}>
      <LockKeyhole className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /><span>Secure document collection by Global Connect Travels</span>
    </p>
  </main>;
}
