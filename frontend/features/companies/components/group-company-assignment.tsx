"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { canAccessApplicationPath } from "@/features/auth/config/route-capabilities";
import { ROUTES } from "@/constants/routes";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { companyKeys } from "../hooks/use-companies";
import type { CompanyReference } from "../types";
import { CompanyPicker } from "./company-picker";
import { CompanyError, companyErrorMessage } from "./company-feedback";
import { CompanyReassignmentDialog } from "./company-reassignment-dialog";

export function GroupCompanyAssignment({ group, disabled }: { group: UploadLinkResponse; disabled?: boolean }) {
  const client = useQueryClient();
  const [saved, setSaved] = useState(group);
  const [selected, setSelected] = useState<CompanyReference | null>(group.company ?? null);
  const [notice, setNotice] = useState<string>();
  const [review, setReview] = useState(false);
  const user = useAuthStore(selectUser);
  const inFlight = useRef(false);
  const applySaved = async (response: UploadLinkResponse) => {
    setSaved(response);
    setSelected(response.company ?? null);
    setNotice("Company assignment saved.");
    await Promise.all([
      client.invalidateQueries({ queryKey: ["upload-links"] }),
      client.invalidateQueries({ queryKey: companyKeys.scope(group.agency_id) }),
      client.invalidateQueries({ queryKey: ["gc-app", group.agency_id] }),
    ]);
  };
  const assignment = useMutation({
    mutationFn: async (companyId: string) => (await apiClient.patch<UploadLinkResponse>(API_ENDPOINTS.companies.assignment(group.id), {
      company_id: companyId, expected_revision: saved.company_revision ?? 0,
    }, { params: { agency_id: group.agency_id } })).data,
    onSuccess: applySaved,
  });
  return <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-4">
    <CompanyPicker agencyId={group.agency_id} value={selected} onChange={(company) => { setSelected(company); setNotice(undefined); }} disabled={disabled || assignment.isPending} />
    <p className="text-xs leading-5 text-slate-500">Company assignment is saved separately. Closed and archived groups retain their collection status. Populated groups need an authorised reassignment review.</p>
    {assignment.isError && <CompanyError message={companyErrorMessage(assignment.error, "Company assignment could not be saved. Refresh the group and try again.")} />}
    {notice && <p role="status" className="text-sm text-emerald-700">{notice}</p>}
    <Button type="button" variant="secondary" size="sm" disabled={disabled || !selected || selected.id === saved.company_id || selected.status !== "active"} isLoading={assignment.isPending}
      onClick={async () => {
        if (!selected || inFlight.current) return;
        if (saved.company_id && selected.id !== saved.company_id && canAccessApplicationPath(user, ROUTES.dashboard.companies)) { setReview(true); return; }
        inFlight.current = true;
        try { await assignment.mutateAsync(selected.id); } catch { /* The mutation error remains visible and the draft selection is preserved. */ }
        finally { inFlight.current = false; }
      }}>Save company assignment</Button>
    {review && selected && <CompanyReassignmentDialog group={saved} target={selected} onSuccess={applySaved} onClose={() => setReview(false)} />}
  </div>;
}
