import { beforeEach, describe, expect, it, vi } from "vitest";
import { gcAppAdminApi } from "./gc-app-admin.api";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";

const client = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: client }));

const access = {
  group_id: "trip", name: "Synthetic trip", lifecycle_status: "closed", enabled: false,
  client_organization_id: "company", client_organization_name: "Synthetic company",
  passenger_access_enabled: true, coordinator_access_enabled: false, client_manager_access_enabled: false,
  access_starts_at: "2026-12-01T00:00:00Z", access_expires_at: "2026-12-10T00:00:00Z",
  revoked_at: null, revision: 8, itinerary_version: 0, common_document_version: 0, announcement_version: 0,
  last_successful_sync_at: null, app_availability: "paused", app_availability_reason: "app_disabled",
  app_availability_evaluated_at: "2026-09-15T12:00:00Z",
};
const announcement = {
  id: "message", title: "Synthetic", message: "Test announcement", priority: "normal", status: "published",
  version: 1, available_from: null, available_until: null, updated_at: "2026-09-15T12:00:00Z",
};
const body = { title: "Synthetic", body: "Test announcement", priority: "normal" as const, available_from: null, available_until: null, publish: true };

const actor = (id: string) => useAuthStore.setState({ user: { id, role: "agency_admin", agency_id: "agency" } as User });
beforeEach(() => { Object.values(client).forEach((mock) => mock.mockReset()); actor("initial-actor"); });

describe("GC App administrative API workflow", () => {
  it.each(["manager", "group"])("retains server paging and scope in %s audit history", async scope => {
    const event = { id: "audit", action: "gc_app.access_changed", actor_email: "operator@example.test", created_at: "2026-09-15T12:00:00Z", metadata: { secret: "not projected" } };
    client.get.mockResolvedValue({ data: { items: [event], total: 91, offset: 50, limit: 25 } });
    const signal = new AbortController().signal;
    const result = scope === "manager"
      ? await gcAppAdminApi.listClientManagerAudit("agency", "manager", { page: 3, page_size: 25 }, signal)
      : await gcAppAdminApi.listGroupAudit("agency", "trip", { page: 3, page_size: 25 }, signal);
    expect(result).toEqual({ items: [{ id: "audit", action: "gc_app.access_changed", summary: "gc app / access changed", actor_name: "operator@example.test", created_at: event.created_at }], total: 91, page: 3, page_size: 25, has_next: true });
    expect(client.get).toHaveBeenCalledExactlyOnceWith(expect.stringMatching(scope === "manager" ? /\/client-managers\/manager\/audit$/ : /\/groups\/trip\/audit$/), { params: { agency_id: "agency", q: undefined, offset: 50, limit: 25 }, signal });
    expect(result.items[0]).not.toHaveProperty("metadata");
  });

  it("rejects an oversized agency directory before starting any fan-out", async () => {
    client.get.mockResolvedValue({ data: { items: [], total: 5001, offset: 0, limit: 100 } });
    await expect(gcAppAdminApi.listAgencies()).rejects.toThrow("too large to load safely");
    expect(client.get).toHaveBeenCalledOnce();
  });

  it("keeps parallel directory reads bounded and output in server-page order", async () => {
    let active = 0;
    let maximum = 0;
    client.get.mockImplementation(async (_url, config) => {
      const offset = config.params.offset;
      active++;
      maximum = Math.max(maximum, active);
      await new Promise(resolve => setTimeout(resolve, offset === 100 ? 8 : 1));
      active--;
      return { data: { items: [{ id: `agency-${offset}`, name: "Synthetic", is_active: true }], total: 900, offset, limit: 100 } };
    });
    const result = await gcAppAdminApi.listAgencies();
    expect(maximum).toBe(4);
    expect(result.map(agency => agency.id)).toEqual(Array.from({ length: 9 }, (_, index) => `agency-${index * 100}`));
    expect(client.get).toHaveBeenCalledTimes(9);
    for (const [, config] of client.get.mock.calls) expect(config).toMatchObject({ expectedOwnerUserId: "initial-actor", expectedAuthorityKey: JSON.stringify(["initial-actor", "agency_admin", "agency"]) });
  });

  it("rejects a private document preview returned as a different content type", async () => {
    client.get.mockResolvedValue({ data: new Blob(["synthetic"], { type: "text/html" }) });
    const signal = new AbortController().signal;
    await expect(gcAppAdminApi.previewCommonDocument("agency", "trip", "document", signal)).rejects.toThrow("not a PDF");
    expect(client.get).toHaveBeenCalledExactlyOnceWith(expect.stringMatching(/\/groups\/trip\/common-documents\/document\/content$/), { params: { agency_id: "agency" }, responseType: "blob", signal, timeout: 120_000 });
  });

  it("stops directory fan-out after the initiating actor changes", async () => {
    client.get.mockImplementation(async () => {
      actor("replacement-actor");
      return { data: { items: [], total: 200, offset: 0, limit: 100 } };
    });
    await expect(gcAppAdminApi.listAgencies()).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    expect(client.get).toHaveBeenCalledOnce();
  });
  it("does not enrich another actor's group page after an account change", async () => {
    client.get.mockImplementation(async () => {
      actor("replacement-actor");
      return { data: { items: [{ id: "old-private-group" }], total: 1, offset: 0, limit: 20 } };
    });
    await expect(gcAppAdminApi.listGroups("agency", { page: 1, page_size: 20, availability: "all", lifecycle: "all" }))
      .rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    expect(client.get).toHaveBeenCalledOnce();
  });
  it("does not continue a profile update into group assignment under a replacement actor", async () => {
    client.patch.mockImplementation(async () => { actor("replacement-actor"); return { data: { revision: 5 } }; });
    const current = { id: "manager", revision: 4 } as Parameters<typeof gcAppAdminApi.updateClientManager>[2];
    await expect(gcAppAdminApi.updateClientManager("agency", "manager", current, {
      name: "Synthetic", email: "synthetic@example.test", phone_number: "000", company_id: "company", group_ids: [],
    })).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    expect(client.put).not.toHaveBeenCalled();
  });
  it("removes only GC App access using the selected revision, including archived or deleted groups", async () => {
    client.get.mockResolvedValue({ data: { ...access, lifecycle_status: "deleted", client_organization_id: null } });
    const current = await gcAppAdminApi.getGroupControl("agency", "trip");
    await gcAppAdminApi.removeGroup("agency", current);
    expect(client.delete).toHaveBeenCalledExactlyOnceWith("/api/v1/gc-app/admin/groups/trip/app-setup", {
      params: { agency_id: "agency", expected_revision: 8 },
    });
    expect(client.put).not.toHaveBeenCalled();
    expect(client.post).not.toHaveBeenCalled();
  });

  it("keeps emergency revocation distinct from removing the GC App setup", async () => {
    await gcAppAdminApi.revokeGroupAccess("agency", "trip");
    expect(client.delete).toHaveBeenCalledExactlyOnceWith("/api/v1/gc-app/admin/groups/trip", {
      params: { agency_id: "agency" },
    });
    expect(client.put).not.toHaveBeenCalled();
    expect(client.post).not.toHaveBeenCalled();
  });

  it("restores removed groups only through an explicit add using their preserved revision", async () => {
    client.get.mockResolvedValue({ data: { items: [{ id: "trip", name: "Synthetic trip", lifecycle_status: "closed",
      access: { ...access, removed_at: "2026-09-16T12:00:00Z", revision: 9 } }], total: 1, offset: 0, limit: 20 } });
    const candidates = await gcAppAdminApi.searchGroups("agency", { page: 1, page_size: 20, eligible_only: true });
    expect(candidates.items[0]).toMatchObject({ gc_removed_at: "2026-09-16T12:00:00Z", gc_revision: 9 });
    client.put.mockResolvedValue({ data: { ...access, revision: 10, enabled: true, removed_at: null } });
    await gcAppAdminApi.addGroup("agency", candidates.items[0]!, { id: "company", name: "Synthetic company" });
    expect(client.put.mock.calls[0][1]).toMatchObject({ expected_revision: 9, enabled: true, restore_removed: true });
  });

  it("loads documents without eagerly fetching announcement history", async () => {
    client.get.mockResolvedValue({ data: [] });
    expect(await gcAppAdminApi.getGroupContent("agency", "trip")).toEqual({ common_documents: [], announcements: [] });
    expect(client.get).toHaveBeenCalledTimes(1);
    expect(client.get.mock.calls[0][0]).toMatch(/\/common-documents$/);
  });

  it("keeps paused configured trips and exact server pagination without per-row requests", async () => {
    client.get.mockResolvedValue({ data: { items: [{ id: "trip", name: "Synthetic trip", lifecycle_status: "closed", gc_enabled: false, access }], total: 42, offset: 20, limit: 20 } });
    const result = await gcAppAdminApi.listGroups("agency", { page: 2, page_size: 20, availability: "paused" });
    expect(result.items).toHaveLength(1);
    expect(result).toMatchObject({ total: 42, page: 2, has_next: true });
    expect(result.items[0]).toMatchObject({ lifecycle: "closed", gc_app_enabled: false, app_availability: "paused" });
    expect(client.get).toHaveBeenCalledTimes(1);
    expect(client.get.mock.calls[0][1].params).toMatchObject({ configured_only: true, availability: "paused", offset: 20, limit: 20 });
    expect(client.get.mock.calls[0][1].params).not.toHaveProperty("gc_enabled");
  });

  it("restores app access while preserving role choices, collection state and access dates", async () => {
    client.get.mockResolvedValue({ data: access });
    const current = await gcAppAdminApi.getGroupControl("agency", "trip");
    client.put.mockResolvedValue({ data: { ...access, enabled: true, revision: 9 } });
    await gcAppAdminApi.updateGroupControl("agency", current, { enabled: true });
    expect(client.put.mock.calls[0][1]).toEqual({
      client_organization_id: "company", enabled: true, passenger_access_enabled: true,
      coordinator_access_enabled: false, client_manager_access_enabled: false,
      access_starts_at: access.access_starts_at, access_expires_at: access.access_expires_at, expected_revision: 8,
    });
  });

  it("saves and publishes a new announcement with one request", async () => {
    client.post.mockResolvedValue({ data: announcement });
    expect(await gcAppAdminApi.createAnnouncement("agency", "trip", body, 8)).toMatchObject({ id: "message", is_published: true });
    expect(client.post).toHaveBeenCalledTimes(1);
    expect(client.post.mock.calls[0][1]).toMatchObject({ publish: true, expected_access_revision: 8 });
  });

  it("edits and publishes once; an error never starts a second publish request", async () => {
    client.put.mockResolvedValue({ data: announcement });
    await gcAppAdminApi.updateAnnouncement("agency", "trip", "message", body, 8);
    expect(client.put).toHaveBeenCalledTimes(1);
    expect(client.post).not.toHaveBeenCalled();
    client.put.mockRejectedValue(new Error("connection lost"));
    await expect(gcAppAdminApi.updateAnnouncement("agency", "trip", "message", body, 9)).rejects.toThrow("connection lost");
    expect(client.post).not.toHaveBeenCalled();
  });

  it("loads announcement pages without silently truncating a large trip history", async () => {
    client.get.mockResolvedValue({ data: { items: [announcement], total: 201, offset: 200, limit: 25 } });
    const result = await gcAppAdminApi.listAnnouncements("agency", "trip", { page: 9, page_size: 25 });
    expect(result).toMatchObject({ total: 201, page: 9, has_next: false });
    expect(result.items[0]).toMatchObject({ id: "message", is_published: true });
    expect(client.get.mock.calls[0][1].params).toEqual({ agency_id: "agency", q: undefined, offset: 200, limit: 25 });
  });
});
