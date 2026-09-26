import { describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { passportsApi } from "./passports.api";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn() } }));

describe("literal roster search transport", () => {
  it.each(["50% complete", "staff_123", "percent_%\\literal"])('preserves the literal search %s in both roster request contracts', async (search) => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: [] });
    await passportsApi.listByGroup("group", search);
    expect(apiClient.get).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ params: { search } }));
    const params = { search, submission_filter: "all" as const, sort_by: "name" as const, sort_order: "asc" as const, page: 1, page_size: 25 };
    await passportsApi.getGroupSubmissionsView("group", params);
    expect(apiClient.get).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ params: expect.objectContaining(params) }));
  });
});
