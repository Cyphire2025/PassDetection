"use client";

import { useCompanyReusePolicy } from "../hooks/use-company-reuse-policy";
import { CompanyError, CompanyLoading } from "./company-feedback";
import { CompanyReusePolicyCard } from "./company-reuse-policy-card";

/** Mounted only on Settings; group rows do not fetch configuration individually. */
export function CompanySettings({ agencyId, companyId, active }: {
  agencyId: string;
  companyId: string;
  active: boolean;
}) {
  const state = useCompanyReusePolicy(agencyId, companyId);
  if (!state.ready || state.policy.isLoading) return <CompanyLoading />;
  if (state.policy.isError || !state.policy.data) {
    return <CompanyError message="Settings could not be loaded." retry={() => void state.policy.refetch()} />;
  }
  return <CompanyReusePolicyCard
    active={active}
    policy={state.policy.data}
    update={state.update}
    toggle={state.toggle}
    retry={() => {
      state.update.reset();
      void state.policy.refetch();
    }}
  />;
}
