import { beforeEach, expect, it, vi } from "vitest";
import { operationsApi } from "./operations.api";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn() } }));

beforeEach(() => vi.mocked(apiClient.get).mockReset().mockResolvedValue({ data: [] }));

it("requests dated current trips for coordinator assignment", async () => {
  await operationsApi.tourGroups(true);
  expect(apiClient.get).toHaveBeenCalledWith(API_ENDPOINTS.tourOperations.groups, {
    params: { assignment_eligible_only: true },
  });
});

it("keeps the broader default group list for rooming and historical office tools", async () => {
  await operationsApi.tourGroups();
  expect(apiClient.get).toHaveBeenCalledWith(API_ENDPOINTS.tourOperations.groups, {
    params: undefined,
  });
});
