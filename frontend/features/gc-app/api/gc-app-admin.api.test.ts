import { beforeEach, describe, expect, it, vi } from "vitest";
import { gcAppAdminApi } from "./gc-app-admin.api";

const client = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() }));
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

beforeEach(() => Object.values(client).forEach((mock) => mock.mockReset()));

describe("GC App administrative API workflow", () => {
  it("removes only GC App access using the selected revision, including archived or deleted groups", async () => {
    client.get.mockResolvedValue({ data: { ...access, lifecycle_status: "deleted", client_organization_id: null } });
    const current = await gcAppAdminApi.getGroupControl("agency", "trip");
    await gcAppAdminApi.removeGroup("agency", current);
    expect(client.delete).toHaveBeenCalledExactlyOnceWith("/api/v1/gc-app/admin/groups/trip", {
      params: { agency_id: "agency", expected_revision: 8 },
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
