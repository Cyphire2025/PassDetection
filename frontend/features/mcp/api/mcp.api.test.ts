import { expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { mcpApi } from "./mcp.api";

vi.mock("@/lib/api/client", () => ({ default: { patch: vi.fn(), post: vi.fn(), get: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
it("sends the isolated enable/disable update to the encoded connection endpoint", async () => {
  vi.mocked(apiClient.patch).mockResolvedValue({ data: { id: "a/b", enabled: false, status: "disabled" } });
  const result = await mcpApi.setConnectionAccess({ id: "a/b", enabled: false });
  expect(apiClient.patch).toHaveBeenCalledWith("/api/v1/admin/mcp/connections/a%2Fb/access", { enabled: false });
  expect(result).toEqual({ id: "a/b", enabled: false, status: "disabled" });
});
it("sends approval through dashboard MFA handling with only the reviewed device fields", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ data: { id: "request/a", status: "approved" } });
  const result = await mcpApi.approveRequest({ id: "request/a", name: "Office Windows", device_platform: "Windows", capabilities: ["mcp:read"] });
  expect(apiClient.post).toHaveBeenCalledWith("/api/v1/admin/mcp/connection-requests/request%2Fa/approve", { name: "Office Windows", device_platform: "Windows", capabilities: ["mcp:read"] });
  expect(result).toEqual({ id: "request/a", status: "approved" });
});
it("rejects a request without sending an OAuth callback or requester credential", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ data: { id: "request/a", status: "rejected" } });
  await mcpApi.rejectRequest("request/a");
  expect(apiClient.post).toHaveBeenCalledWith("/api/v1/admin/mcp/connection-requests/request%2Fa/reject", {});
});
it("deletes the encoded connection through dashboard MFA handling without a body or revoke call", async () => {
  vi.mocked(apiClient.delete).mockResolvedValue({ data: { deleted: true } });
  const result = await mcpApi.deleteConnection("grant/a");
  expect(apiClient.delete).toHaveBeenCalledWith("/api/v1/admin/mcp/connections/grant%2Fa");
  expect(result).toEqual({ deleted: true });
});
it("requires an explicit confirmed deletion before changing cached device state", async () => {
  vi.mocked(apiClient.delete).mockResolvedValue({ data: { deleted: false } });
  await expect(mcpApi.deleteConnection("grant/a")).rejects.toThrow("could not be deleted");
});

it("saves one versioned global read/write policy through the dashboard client", async () => {
  const update = { expected_revision: 8, read_enabled: true, write_enabled: false, allowed_read_sections: ["all_groups"],
    allowed_write_sections: ["exports"], allowed_write_tools: ["prepare_excel_export"] };
  vi.mocked(apiClient.put).mockResolvedValue({ data: { ...update, permission_revision: 9 } });
  await mcpApi.updatePermissions(update);
  expect(apiClient.put).toHaveBeenCalledWith("/api/v1/admin/mcp/permissions", update);
});

it("saves independent versioned device allowances without sending expanded OAuth scopes", async () => {
  const { id, ...update } = { id: "grant/a", expected_revision: 3, read_enabled: false, write_enabled: true,
    allowed_read_sections: null, allowed_write_sections: ["exports"] };
  vi.mocked(apiClient.put).mockResolvedValue({ data: { id, ...update, permission_revision: 4 } });
  await mcpApi.updateConnectionPermissions({ id, ...update });
  expect(apiClient.put).toHaveBeenCalledWith("/api/v1/admin/mcp/connections/grant%2Fa/permissions", update);
});
