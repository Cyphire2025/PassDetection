import type { ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import styles from "./traveller-landing.module.css";

export function TravellerEntryChoice({ icon, title, description, onClick }: { icon: ReactNode; title: string; description: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className={`${styles.choice} group flex w-full items-center rounded-2xl border border-slate-200 bg-white text-left transition-colors hover:border-blue-400 hover:bg-blue-50/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2`}>
    <span className={`${styles.icon} flex shrink-0 items-center justify-center rounded-2xl bg-blue-50 text-blue-600`}>{icon}</span>
    <span className="min-w-0 flex-1"><span className="block text-base font-semibold text-slate-900">{title}</span><span className="mt-1 block text-sm leading-5 text-slate-500">{description}</span></span>
    <ArrowRight className="h-5 w-5 shrink-0 text-slate-400 group-hover:text-blue-600" aria-hidden="true" />
  </button>;
}
