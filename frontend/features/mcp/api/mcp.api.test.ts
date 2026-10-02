import { expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { mcpApi } from "./mcp.api";

vi.mock("@/lib/api/client", () => ({ default: { patch: vi.fn(), post: vi.fn(), get: vi.fn() } }));
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
