import { cleanup } from "@testing-library/react";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { vi } from "vitest";
import apiClient from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";

export const companyActor: User = {
  id: "company-owner", role: "agency_admin", agency_id: "agency",
  full_name: "Synthetic owner", email: "owner@example.test", is_active: true,
  last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01",
};
export const travellerId = "11111111-1111-4111-8111-111111111111";
export const match = {
  id: "case", source_kind: "passport_submission", source_row_key: travellerId,
  status: "provisional", reason_code: "exact_passport", traveller_id: travellerId, revision: 3,
};
const clients: QueryClient[] = [];

export function resetCompanyAuthority() {
  vi.resetAllMocks();
  useAuthStore.setState({ user: companyActor, sessionVersion: 1, isChangingAccessLevel: false });
  vi.mocked(apiClient.get).mockImplementation(async (url) => {
    if (url.endsWith("/matching-preview")) return { data: {
      items: [], counts: {}, next_cursor: null, latest_job_status: null,
      processed_count: 0, expected_group_revision: 9,
    } };
    if (url.endsWith("/passports")) return { data: {
      items: [{ id: "passport", passport_hint: "Synthetic passport", issuing_country: "IND",
        document_type: "P", status: "active", revision: 4, expiry_date: null }],
      profile_revision: 9, limit_reached: false,
    } };
    if (url.endsWith("/preview")) return { data: {
      can_reassign: true, expected_revision: 4, expected_roster_revision: 9,
      submission_records: 0, accepted_participations: 0, active_claims: 0, active_grants: 0,
    } };
    return { data: { enabled: false, revision: 4 } };
  });
  for (const method of [apiClient.post, apiClient.put, apiClient.patch, apiClient.delete]) {
    vi.mocked(method).mockResolvedValue({ data: { id: "saved", kind: "excel", status: "queued" } });
  }
}

export function cleanupCompanyAuthority() {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  useAuthStore.setState({ user: null });
}

export function queuedCompanyMutation() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => { release = resolve; });
  const entered = vi.fn();
  const client = new QueryClient({
    mutationCache: new MutationCache({ onMutate: async () => { entered(); await promise; } }),
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper, entered, release };
}

export const companyWrites = () => [apiClient.post, apiClient.put, apiClient.patch, apiClient.delete];
