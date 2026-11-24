import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import * as passports from "./use-passports";
import * as links from "./use-upload-links";
import { useUpdateClientDetails } from "./use-client-details";
import { useDisplayNameEditor } from "./use-display-name";

const api = vi.hoisted(() => ({
  passport: Object.fromEntries([
    "exportGroup", "exportGroupImages", "exportWhatsAppTracking", "importGroup",
    "previewPassportDocuments", "savePassportDocumentsInChunks", "exportSelectedPassports",
    "exportSelectedGroupImages", "bulkDocumentFollowUp", "bulkDelete", "bulkStaffApprove",
    "exportSelectedGroups", "confirm", "staffApprove", "retryAiVerification", "reextract", "getById",
  ].map((name) => [name, vi.fn()])),
  link: Object.fromEntries([
    "create", "revoke", "delete", "update", "updateWhatsAppLinks",
    "resolveUnidentifiedReplacement", "rejectUnidentifiedUpload", "restoreRosterResolution",
    "permanentDelete", "restore",
  ].map((name) => [name, vi.fn()])),
  clientDetails: vi.fn(), displayName: vi.fn(),
}));
vi.mock("../api/passports.api", () => ({ passportsApi: api.passport }));
vi.mock("../api/upload-links.api", () => ({ uploadLinksApi: api.link }));
vi.mock("../api/client-details.api", () => ({ clientDetailsApi: { update: api.clientDetails } }));
vi.mock("../api/display-name.api", () => ({ updateDisplayName: api.displayName }));

type Subject = { mutateAsync: (variables: unknown) => Promise<unknown> };
const subject = (value: unknown) => value as Subject;
const file = new File(["synthetic"], "passport.jpg");
const groupRequest = { groupId: "group", mode: "all" };
const cases = [
  ["group Excel", () => subject(passports.useExportPassportGroup()), api.passport.exportGroup, groupRequest],
  ["group images", () => subject(passports.useExportPassportGroupImages()), api.passport.exportGroupImages, groupRequest],
  ["tracking export", () => subject(passports.useExportWhatsAppTracking()), api.passport.exportWhatsAppTracking, { groupId: "group", status: "all" }],
  ["Excel import", () => subject(passports.useImportPassportGroup("group")), api.passport.importGroup, file],
  ["document preview", () => subject(passports.usePreviewPassportDocuments("group")), api.passport.previewPassportDocuments, { files: [file] }],
  ["document save", () => subject(passports.useSavePassportDocuments("group")), api.passport.savePassportDocumentsInChunks, { files: [file] }],
  ["selected Excel", () => subject(passports.useExportSelectedPassports()), api.passport.exportSelectedPassports, ["record"]],
  ["selected images", () => subject(passports.useExportSelectedPassportImages()), api.passport.exportSelectedGroupImages, { groupId: "group", submissionIds: ["record"] }],
  ["follow-up", () => subject(passports.useBulkDocumentFollowUp("group")), api.passport.bulkDocumentFollowUp, { submission_ids: ["record"], flagged: true }],
  ["bulk delete", () => subject(passports.useBulkDeletePassportSubmissions("group")), api.passport.bulkDelete, ["record"]],
  ["bulk approval", () => subject(passports.useBulkStaffApprovePassportSubmissions("group")), api.passport.bulkStaffApprove, [{ submission_id: "record", expected_extraction_revision: 7 }]],
  ["selected groups", () => subject(passports.useExportSelectedGroups()), api.passport.exportSelectedGroups, { groupIds: ["group"] }],
  ["confirmation", () => subject(passports.useConfirmPassportSubmission("record")), api.passport.confirm, { surname: "SYNTHETIC" }],
  ["staff approval", () => subject(passports.useStaffApprovePassportSubmission("record")), api.passport.staffApprove, { confirmedFields: { surname: "SYNTHETIC" }, expectedExtractionRevision: 7 }],
  ["AI retry", () => subject(passports.useRetryPassportAiVerification("record")), api.passport.retryAiVerification, undefined],
  ["re-extraction", () => subject(passports.useReextractPassportSubmission()), api.passport.reextract, "record"],
  ["link creation", () => subject(links.useCreateUploadLink()), api.link.create, { name: "Synthetic group" }],
  ["link closure", () => subject(links.useRevokeUploadLink()), api.link.revoke, "group"],
  ["link archive", () => subject(links.useDeleteUploadLink()), api.link.delete, "group"],
  ["link update", () => subject(links.useUpdateUploadLink()), api.link.update, { id: "group", name: "Synthetic group" }],
  ["linked broadcasts", () => subject(links.useUpdateGroupWhatsAppLinks("group")), api.link.updateWhatsAppLinks, { whatsappBroadcastGroupIds: ["broadcast"], matchingFieldsByBroadcast: { broadcast: ["phone"] } }],
  ["replacement", () => subject(links.useResolveUnidentifiedReplacement("group")), api.link.resolveUnidentifiedReplacement, { submissionId: "record", recipientId: "recipient", requestId: "request" }],
  ["reject upload", () => subject(links.useRejectUnidentifiedUpload("group")), api.link.rejectUnidentifiedUpload, { submissionId: "record", requestId: "request" }],
  ["restore resolution", () => subject(links.useRestoreRosterResolution("group")), api.link.restoreRosterResolution, "resolution"],
  ["permanent delete", () => subject(links.usePermanentlyDeleteUploadLink()), api.link.permanentDelete, { id: "group", retainRecords: true }],
  ["restore group", () => subject(links.useRestoreUploadLink()), api.link.restore, "group"],
  ["client details", () => subject(useUpdateClientDetails("record", "group")), api.clientDetails, { client_email: "synthetic@example.test", expected_updated_at: "revision" }],
  ["display name", () => subject(useDisplayNameEditor("record", "group").mutation), api.displayName, { display_name: "Synthetic", expected_updated_at: "revision" }],
] as const;

function actor(id = "initial-actor", role = "agency_admin", agencyId = "agency") {
  useAuthStore.setState({ user: { id, role, agency_id: agencyId } as User });
}
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}
const clients: QueryClient[] = [];
function context(cache?: MutationCache) {
  const client = new QueryClient({ mutationCache: cache, defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  return { client, wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> };
}
beforeEach(() => {
  vi.resetAllMocks(); actor();
  for (const fn of [...Object.values(api.passport), ...Object.values(api.link), api.clientDetails, api.displayName]) {
    fn.mockResolvedValue({ id: "record", group_id: "group", name: "Synthetic", status: "active", submission: { id: "record", group_id: "group" } });
  }
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

describe("private passport mutation invocation ownership", () => {
  it.each(cases)("does not dispatch queued %s intent under a replacement actor", async (_name, useSubject, transport, variables) => {
    const start = deferred(), entered = vi.fn();
    const ctx = context(new MutationCache({ onMutate: async () => { entered(); await start.promise; } }));
    const { result } = renderHook(useSubject, ctx);
    let pending!: Promise<unknown>;
    act(() => { pending = result.current.mutateAsync(variables); });
    // Attach rejection handling before releasing the scheduler to avoid an unhandled rejection.
    const outcome = pending.then(() => ({ error: null }), (error: unknown) => ({ error }));
    await waitFor(() => expect(entered).toHaveBeenCalledOnce());
    actor("replacement-actor");
    let settled!: { error: unknown };
    await act(async () => { start.resolve(); settled = await outcome; });
    expect(transport).not.toHaveBeenCalled();
    expect(settled.error).toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  });

  it.each(cases)("forwards the original authority separately from %s values", async (_name, useSubject, transport, variables) => {
    const { result } = renderHook(useSubject, context());
    await act(async () => { await result.current.mutateAsync(variables); });
    expect(transport).toHaveBeenCalledOnce();
    expect(transport.mock.calls[0].at(-1)).toEqual({
      expectedOwnerUserId: "initial-actor",
      expectedAuthorityKey: '["initial-actor","agency_admin","agency"]',
    });
  });

  it.each([
    ["passport role", () => subject(passports.useConfirmPassportSubmission("record")), api.passport.confirm, () => actor("initial-actor", "agency_staff")],
    ["passport agency", () => subject(passports.useConfirmPassportSubmission("record")), api.passport.confirm, () => actor("initial-actor", "agency_admin", "other-agency")],
    ["link role", () => subject(links.useCreateUploadLink()), api.link.create, () => actor("initial-actor", "agency_staff")],
    ["link agency", () => subject(links.useCreateUploadLink()), api.link.create, () => actor("initial-actor", "agency_admin", "other-agency")],
  ] as const)("rejects queued %s changes for the same user", async (_name, useSubject, transport, replaceAuthority) => {
    const start = deferred(), entered = vi.fn();
    const { result } = renderHook(useSubject, context(new MutationCache({ onMutate: async () => { entered(); await start.promise; } })));
    let pending!: Promise<unknown>;
    act(() => { pending = result.current.mutateAsync({ surname: "SYNTHETIC", name: "Synthetic" }); });
    const rejected = expect(pending).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    await waitFor(() => expect(entered).toHaveBeenCalledOnce());
    replaceAuthority();
    await act(async () => { start.resolve(); await rejected; });
    expect(transport).not.toHaveBeenCalled();
  });

  it("allows a queued operation after profile and session renewal under unchanged authority", async () => {
    const start = deferred(), entered = vi.fn();
    const { result } = renderHook(() => passports.useConfirmPassportSubmission("record"), context(new MutationCache({ onMutate: async () => { entered(); await start.promise; } })));
    let pending!: Promise<unknown>;
    act(() => { pending = result.current.mutateAsync({ surname: "SYNTHETIC" }); });
    await waitFor(() => expect(entered).toHaveBeenCalledOnce());
    useAuthStore.setState((state) => ({ user: { ...state.user!, full_name: "Renewed profile" }, sessionVersion: state.sessionVersion + 1 }));
    await act(async () => { start.resolve(); await pending; });
    expect(api.passport.confirm).toHaveBeenCalledOnce();
  });

  it("does not replace the new actor's detail cache with a late confirmation", async () => {
    let finish!: (value: unknown) => void;
    api.passport.confirm.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const ctx = context();
    const { result } = renderHook(() => passports.useConfirmPassportSubmission("record"), ctx);
    let pending!: Promise<unknown>;
    act(() => { pending = result.current.mutateAsync({ surname: "OLD" }); });
    const rejected = expect(pending).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    await waitFor(() => expect(api.passport.confirm).toHaveBeenCalledOnce());
    actor("replacement-actor");
    const replacement = { id: "record", client_name: "New actor cache" };
    const { QUERY_KEYS } = await import("@/constants");
    ctx.client.setQueryData(QUERY_KEYS.passports.detail("record"), replacement);
    await act(async () => { finish({ id: "record", group_id: "group", client_name: "Old private result" }); await rejected; });
    expect(ctx.client.getQueryData(QUERY_KEYS.passports.detail("record"))).toBe(replacement);
  });
});
