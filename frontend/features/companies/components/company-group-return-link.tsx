"use client";

import { useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { ROUTES } from "@/constants/routes";
import { safeCompanyReturn } from "../utils/company-navigation";

export function CompanyGroupReturnLink() {
  const companyReturn = safeCompanyReturn(useSearchParams().get("returnTo"));
  return <IntentPrefetchLink href={companyReturn ?? ROUTES.dashboard.passports}
    className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15">
    <ArrowLeft className="h-4 w-4" aria-hidden="true" />{companyReturn ? "Back to company" : "All Groups"}
  </IntentPrefetchLink>;
}
