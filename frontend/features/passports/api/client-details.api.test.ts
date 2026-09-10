import { describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { clientDetailsApi } from "./client-details.api";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), patch: vi.fn() } }));

describe("client details transport", () => {
  it("reads authenticated editor metadata and patches sparse corrections without a workflow command", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { updated_at: "version" } });
    vi.mocked(apiClient.patch).mockResolvedValue({ data: { id: "id", status: "staff_approved" } });
    expect(await clientDetailsApi.get("id")).toEqual({ updated_at: "version" });
    const patch = { expected_updated_at: "version", agent_employee_code: "12345" };
    expect(await clientDetailsApi.update("id", patch)).toEqual({ id: "id", status: "staff_approved" });
    expect(apiClient.get).toHaveBeenCalledWith("/api/v1/passports/id/client-details");
    expect(apiClient.patch).toHaveBeenCalledWith("/api/v1/passports/id/client-details", patch);
  });
});
