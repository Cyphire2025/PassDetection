import Link from "next/link";
import { ArrowRight, UserRound } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import type { CompanyPerson } from "../types/company-people";
import { companyPersonHref } from "../utils/company-navigation";

export function CompanyPersonRow({ person, companyId, query }: { person: CompanyPerson; companyId: string; query: string }) {
  const submissions = person.submission_count;
  return <li className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
    <span className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-50 text-slate-500 sm:flex"><UserRound className="h-4 w-4" aria-hidden="true" /></span>
    <div className="min-w-0 flex-1"><p className="break-words text-sm font-semibold text-slate-950">{person.display_name}</p><p className="mt-1 text-xs leading-5 text-slate-500">{submissions.toLocaleString()} {submissions === 1 ? "submission" : "submissions"} · {person.trip_count.toLocaleString()} {person.trip_count === 1 ? "trip" : "trips"}{person.current_passport_last4 ? ` · ••••${person.current_passport_last4}` : ""}</p></div>
    <Link prefetch={false} href={companyPersonHref(companyId, person.id, query)} aria-label={`Open ${person.display_name}`} className={buttonVariants({ variant: "secondary", size: "sm", className: "min-h-11 shrink-0 gap-1.5 text-blue-800" })}>Open<ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
  </li>;
}
