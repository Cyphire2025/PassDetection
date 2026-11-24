"use client";

import { useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { reuseSetupApi } from "../api/reuse-setup.api";
import { companyKeys, companyQueryOptions, useCompanyQueryContext } from "./company-query-state";

export function useCompanyReusePolicy(agencyId: string, companyId: string) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const key = [...scope, companyId, "reuse-policy"];
  const client = useQueryClient();
  const inFlight = useRef(false);
  const policy = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => reuseSetupApi.policy(agencyId, companyId, signal),
    enabled: ready,
    ...companyQueryOptions
  });
  const update = usePrivateMutation({
    mutationFn: (enabled: boolean, _context, owner) => {
      if (!ready || !policy.data) throw new Error("Company settings are unavailable.");
      return reuseSetupApi.savePolicy(agencyId, companyId, { expected_revision: policy.data.revision, enabled }, owner.requestConfig);
    },
    onSuccess: async (saved, _variables, _result, _context, owner) => {
      await client.invalidateQueries({ queryKey: companyKeys.scope(agencyId), refetchType: "none" });
      owner.assertCurrent();
      client.setQueryData(key, saved);
      await client.invalidateQueries({ queryKey: [...scope, companyId], exact: true });
    },
  });
  async function toggle(enabled: boolean) {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      await update.mutateAsync(enabled);
    } catch { /* Keep the saved value and show the error below. */ }
    finally {
      inFlight.current = false;
    }
  }
  return { ready, policy, update, toggle };
}
