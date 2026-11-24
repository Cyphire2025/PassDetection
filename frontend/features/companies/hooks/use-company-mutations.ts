"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { companiesApi } from "../api/companies.api";
import type { Company, CompanyInput, CompanyUpdate } from "../types";
import { companyKeys } from "./company-query-state";

export function useCompanyMutations(agencyId: string) {
  const client = useQueryClient();
  const invalidate = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: companyKeys.scope(agencyId) }),
      client.invalidateQueries({ queryKey: ["gc-app", agencyId] }),
      client.invalidateQueries({ queryKey: ["upload-links"] }),
      client.invalidateQueries({ queryKey: ["passports", "groups"] }),
      client.invalidateQueries({ queryKey: ["document-distribution", "groups"] }),
    ]);
  };
  return {
    create: usePrivateMutation({
      mutationFn: (body: CompanyInput, _context, owner) => companiesApi.create(agencyId, body, owner.requestConfig),
      onSuccess: invalidate
    }),
    update: usePrivateMutation({
      mutationFn: ({ id, ...body }: CompanyUpdate & { id: string }, _context, owner) => companiesApi.update(agencyId, id, body, owner.requestConfig),
      onSuccess: invalidate
    }),
    remove: usePrivateMutation({
      mutationFn: (company: Company, _context, owner) => companiesApi.remove(agencyId, company, owner.requestConfig),
      onSuccess: invalidate
    }),
  };
}
