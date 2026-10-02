import { expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { mcpApi } from "./mcp.api";

vi.mock("@/lib/api/client", () => ({ default: { patch: vi.fn() } }));
it("sends the isolated enable/disable update to the encoded connection endpoint", async () => {
  vi.mocked(apiClient.patch).mockResolvedValue({ data: { id: "a/b", enabled: false, status: "disabled" } });
  const result = await mcpApi.setConnectionAccess({ id: "a/b", enabled: false });
  expect(apiClient.patch).toHaveBeenCalledWith("/api/v1/admin/mcp/connections/a%2Fb/access", { enabled: false });
  expect(result).toEqual({ id: "a/b", enabled: false, status: "disabled" });
});
