"use client";

import dynamic from "next/dynamic";
import { Button } from "@/components/ui/button";
import { useCompanyDirectoryState } from "../hooks/use-company-directory-state";
import { CompanyDataExports } from "./company-data-exports";
import { CompanyPeopleDirectory } from "./company-people-directory";

const CompanyMatchQueue = dynamic(() => import("./company-match-queue").then((module) => module.CompanyMatchQueue));

/** One indexed 100-person page; private fields and images load on explicit open. */
export function CompanyAllData({ agencyId, companyId }: {
  agencyId: string;
  companyId: string
}) {
  const state = useCompanyDirectoryState(agencyId, companyId);
  const { people, scope, ready, reviewMatches, setReviewMatches } = state;
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <CompanyDataExports agencyId={agencyId} companyId={companyId} />
      <Button
        type="button"
        variant="ghost"
        disabled={!ready || people.isError}
        onClick={() => setReviewMatches(true)}
      >Review matches</Button>
    </div>
    <CompanyPeopleDirectory companyId={companyId} state={state} />
    {ready && !people.isError && reviewMatches && <CompanyMatchQueue
      key={scope.join(":")}
      agencyId={agencyId}
      companyId={companyId}
      onClose={() => setReviewMatches(false)}
    />}
  </div>;
}
