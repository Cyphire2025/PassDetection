import { type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import { uploadLinksApi, type CreateUploadLinkRequest, type UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { passportsApi } from "@/features/passports/api/passports.api";
import { clientDetailsApi } from "@/features/passports/api/client-details.api";
import { useCreateUploadLink, useRestoreUploadLink, useRevokeUploadLink } from "@/features/passports/hooks/use-upload-links";
import { useImportPassportGroup, useSavePassportDocuments, useStaffApprovePassportSubmission } from "@/features/passports/hooks/use-passports";
import { useUpdateClientDetails } from "@/features/passports/hooks/use-client-details";
import { dashboardRealtimeQueryPrefixes } from "@/features/operations/services/dashboard-realtime";
import { whatsappSourceGroupsApi, type WhatsAppSourceGroup, type WhatsAppSourceGroupPreview } from "../api/whatsapp-source-groups.api";
import { WHATSAPP_SOURCE_QUERY_KEYS } from "../utils/source-group-cache";
import { useWhatsAppBroadcastSourceContacts, useWhatsAppSourceGroupPreview, useWhatsAppSourceGroups } from "./use-whatsapp-source-groups";

vi.mock("../api/whatsapp-source-groups.api", () => ({ whatsappSourceGroupsApi: { list: vi.fn(), preview: vi.fn(), groupContacts: vi.fn() } }));
vi.mock("@/features/passports/api/upload-links.api", () => ({ uploadLinksApi: { create: vi.fn(), revoke: vi.fn(), restore: vi.fn() } }));
vi.mock("@/features/passports/api/passports.api", () => ({ passportsApi: { importGroup: vi.fn(), staffApprove: vi.fn(), savePassportDocumentsInChunks: vi.fn() } }));
vi.mock("@/features/passports/api/client-details.api", () => ({ clientDetailsApi: { update: vi.fn() } }));

const groupId = "trip-a";
const submission = { id: "submission-a", group_id: groupId } as PassportSubmission;
let serverGroups: WhatsAppSourceGroup[];
let serverPreview: WhatsAppSourceGroupPreview;

function contactPreview(count = 1, name = "Original Traveller", revision = "revision-a"): WhatsAppSourceGroupPreview {
  return {
    source_group_id: groupId, source_group_name: "September trip", total_submissions: count,
    recipient_count: count, recipients: [{ name, phone_number: "+919999999991", imported_fields: {} }],
    excluded_count: 0, excluded_counts: { missing_phone: 0, invalid_phone: 0, unverified_phone: 0, missing_name: 0, name_too_long: 0, duplicate_phone: 0 },
    preview_revision: revision,
  };
}

function setup() {
  // Match the application's default: a warm cache stays fresh for five minutes.
  const client = new QueryClient({ defaultOptions: {
    queries: { staleTime: 5 * 60_000, retry: false }, mutations: { retry: false },
  } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, wrapper };
}

beforeEach(() => {
  vi.clearAllMocks();
  serverGroups = [{ id: groupId, name: "September trip", submission_count: 1 }];
  serverPreview = contactPreview();
  vi.mocked(whatsappSourceGroupsApi.list).mockImplementation(async () => serverGroups);
  vi.mocked(whatsappSourceGroupsApi.preview).mockImplementation(async (id) => ({ ...serverPreview, source_group_id: id }));
  vi.mocked(whatsappSourceGroupsApi.groupContacts).mockImplementation(async () => ({
    sources: [{ id: groupId, name: "September trip", import_only: true }],
    total_contacts: serverPreview.total_submissions, unique_phone_count: serverPreview.recipient_count,
    needs_attention_count: 0, shared_phone_count: 0,
    contacts: serverPreview.recipients.map((recipient, index) => ({ source_submission_id: `person-${index}`, name: recipient.name ?? "", phone_number: recipient.phone_number, normalized_phone_number: recipient.phone_number, issue: null, imported_fields: {}, source_group_id: groupId, source_group_name: "September trip", source_import_only: true, recipient_id: `recipient-${index}` })),
  }));
});

describe("WhatsApp source-group cache freshness", () => {
  it("fetches new groups on opening despite a fresh cached empty result", async () => {
    const { client, wrapper } = setup();
    client.setQueryData(WHATSAPP_SOURCE_QUERY_KEYS.groups, []);
    const { result } = renderHook(() => useWhatsAppSourceGroups(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(serverGroups));
    expect(whatsappSourceGroupsApi.list).toHaveBeenCalledTimes(1);
  });

  it("refreshes an existing preview when selecting a recently viewed group again", async () => {
    const { wrapper } = setup();
    const { result, rerender } = renderHook(({ id }) => useWhatsAppSourceGroupPreview(id), { wrapper, initialProps: { id: groupId } });
    await waitFor(() => expect(result.current.data?.preview_revision).toBe("revision-a"));
    rerender({ id: "trip-b" });
    await waitFor(() => expect(result.current.data?.source_group_id).toBe("trip-b"));
    serverPreview = contactPreview(2, "Updated Traveller", "revision-new");
    rerender({ id: groupId });
    await waitFor(() => expect(result.current.data?.preview_revision).toBe("revision-new"));
    expect(result.current.data?.recipients[0].name).toBe("Updated Traveller");
  });

  it("updates an already-open picker immediately after creating a passport group", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => ({ groups: useWhatsAppSourceGroups(), create: useCreateUploadLink() }), { wrapper });
    await waitFor(() => expect(result.current.groups.data).toHaveLength(1));
    vi.mocked(uploadLinksApi.create).mockImplementation(async () => {
      serverGroups = [...serverGroups, { id: "new-trip", name: "New import group", submission_count: 0 }];
      return { id: "new-trip" } as UploadLinkResponse;
    });
    await act(() => result.current.create.mutateAsync({ name: "New import group" } as CreateUploadLinkRequest));
    await waitFor(() => expect(result.current.groups.data).toHaveLength(2));
    expect(result.current.groups.data?.[1].name).toBe("New import group");
  });

  it("refreshes counts and contacts after Excel import while leaving unrelated previews fresh", async () => {
    const { client, wrapper } = setup();
    client.setQueryData(WHATSAPP_SOURCE_QUERY_KEYS.preview("unrelated-trip"), contactPreview());
    const { result } = renderHook(() => ({ groups: useWhatsAppSourceGroups(), preview: useWhatsAppSourceGroupPreview(groupId), broadcast: useWhatsAppBroadcastSourceContacts("broadcast-a", true), importFile: useImportPassportGroup(groupId) }), { wrapper });
    await waitFor(() => expect(result.current.preview.data?.recipient_count).toBe(1));
    vi.mocked(passportsApi.importGroup).mockImplementation(async () => {
      serverGroups = [{ ...serverGroups[0], submission_count: 377 }];
      serverPreview = contactPreview(377, "Imported Traveller", "revision-imported");
      return { imported_count: 376, updated_count: 0, skipped_count: 0 };
    });
    await act(() => result.current.importFile.mutateAsync(new File(["contacts"], "group.xlsx")));
    await waitFor(() => expect(result.current.groups.data?.[0].submission_count).toBe(377));
    expect(result.current.preview.data?.recipient_count).toBe(377);
    expect(result.current.preview.data?.recipients[0].name).toBe("Imported Traveller");
    expect(result.current.broadcast.data?.total_contacts).toBe(377);
    expect(result.current.broadcast.data?.contacts[0].name).toBe("Imported Traveller");
    expect(client.getQueryState(WHATSAPP_SOURCE_QUERY_KEYS.preview("unrelated-trip"))?.isInvalidated).toBe(false);
  });

  it("refreshes the copied name after staff approval saves corrected passport fields", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => ({ preview: useWhatsAppSourceGroupPreview(groupId), approve: useStaffApprovePassportSubmission(submission.id) }), { wrapper });
    await waitFor(() => expect(result.current.preview.data?.preview_revision).toBe("revision-a"));
    vi.mocked(passportsApi.staffApprove).mockImplementation(async () => {
      serverPreview = contactPreview(1, "Corrected Fullname", "revision-approved");
      return { submission, outcome: "approved", extractionRevision: 2 };
    });
    await act(() => result.current.approve.mutateAsync({ confirmedFields: { given_name: "Corrected", surname: "Fullname" }, expectedExtractionRevision: 1 }));
    await waitFor(() => expect(result.current.preview.data?.recipients[0].name).toBe("Corrected Fullname"));
  });

  it("keeps contact edits wired to the source preview cache", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => ({ preview: useWhatsAppSourceGroupPreview(groupId), edit: useUpdateClientDetails(submission.id, groupId) }), { wrapper });
    await waitFor(() => expect(result.current.preview.data?.preview_revision).toBe("revision-a"));
    vi.mocked(clientDetailsApi.update).mockImplementation(async () => {
      serverPreview = { ...contactPreview(1, "Original Traveller", "revision-contact"), recipients: [{ name: "Original Traveller", phone_number: "+919999999992" }] };
      return submission;
    });
    await act(() => result.current.edit.mutateAsync({ client_phone: "+919999999992", expected_updated_at: "2026-09-21T00:00:00Z" }));
    await waitFor(() => expect(result.current.preview.data?.recipients[0].phone_number).toBe("+919999999992"));
  });

  it("refreshes contacts if a later document-import chunk fails after earlier saves", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => ({ preview: useWhatsAppSourceGroupPreview(groupId), save: useSavePassportDocuments(groupId) }), { wrapper });
    await waitFor(() => expect(result.current.preview.data?.preview_revision).toBe("revision-a"));
    vi.mocked(passportsApi.savePassportDocumentsInChunks).mockImplementation(async () => {
      serverPreview = contactPreview(2, "Partially imported traveller", "revision-partial");
      throw new Error("Later chunk failed");
    });
    await act(async () => { await expect(result.current.save.mutateAsync({ files: [] })).rejects.toThrow("Later chunk failed"); });
    await waitFor(() => expect(result.current.preview.data?.preview_revision).toBe("revision-partial"));
  });

  it("removes closed groups and restores reopened groups without waiting for cached results to expire", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => ({ groups: useWhatsAppSourceGroups(), revoke: useRevokeUploadLink(), restore: useRestoreUploadLink() }), { wrapper });
    await waitFor(() => expect(result.current.groups.data).toHaveLength(1));
    vi.mocked(uploadLinksApi.revoke).mockImplementation(async () => {
      serverGroups = [];
      return { id: groupId } as UploadLinkResponse;
    });
    vi.mocked(uploadLinksApi.restore).mockImplementation(async () => {
      serverGroups = [{ id: groupId, name: "Reopened trip", submission_count: 1 }];
      return { id: groupId } as UploadLinkResponse;
    });
    await act(() => result.current.revoke.mutateAsync(groupId));
    await waitFor(() => expect(result.current.groups.data).toHaveLength(0));
    await act(() => result.current.restore.mutateAsync(groupId));
    await waitFor(() => expect(result.current.groups.data?.[0].name).toBe("Reopened trip"));
  });

  it.each(["roster", "all"] as const)("refreshes the selected roster on a %s realtime hint", async (invalidation) => {
    const { client, wrapper } = setup();
    const { result } = renderHook(() => ({ groups: useWhatsAppSourceGroups(), preview: useWhatsAppSourceGroupPreview(groupId), broadcast: useWhatsAppBroadcastSourceContacts("broadcast-a", true) }), { wrapper });
    await waitFor(() => expect(result.current.preview.data?.preview_revision).toBe("revision-a"));
    serverGroups = [{ ...serverGroups[0], submission_count: 2 }];
    serverPreview = contactPreview(2, "Updated elsewhere", "revision-realtime");
    await act(async () => {
      await Promise.all(dashboardRealtimeQueryPrefixes({ type: "sync_hint", trip_id: groupId, cursor: 42, invalidation }).map((queryKey) => client.invalidateQueries({ queryKey })));
    });
    await waitFor(() => expect(result.current.groups.data?.[0].submission_count).toBe(2));
    expect(result.current.preview.data?.preview_revision).toBe("revision-realtime");
    expect(result.current.broadcast.data?.contacts[0].name).toBe("Updated elsewhere");
  });
});
