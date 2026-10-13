"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useCompanyWorkspace, type CompanyWorkspace } from "../hooks/use-company-workspace";
import { CompanyError, CompanyLoading } from "./company-feedback";

const AgencyContext = createContext<string | null>(null);

export function CompanyWorkspaceFeedback({ workspace }: { workspace: CompanyWorkspace }) {
  if (!workspace.isError) return <CompanyLoading />;
  return <CompanyError message="Your company workspace is unavailable. Retry or contact your administrator to check the workspace configuration." retry={() => void workspace.refetch()} />;
}

export function CompanyAgencyScope({ children }: { children: ReactNode }) {
  const workspace = useCompanyWorkspace();
  if (!workspace.agencyId) return <CompanyWorkspaceFeedback workspace={workspace} />;
  return <AgencyContext.Provider key={`${workspace.sessionKey}:${workspace.agencyId}`} value={workspace.agencyId}>{children}</AgencyContext.Provider>;
}

export function useCompanyAgency() {
  const agency = useContext(AgencyContext);
  if (!agency) throw new Error("A company agency scope is required.");
  return agency;
}
