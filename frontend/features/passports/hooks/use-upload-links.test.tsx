import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { QUERY_KEYS } from "@/constants";
import { uploadLinksApi, type UploadLinkResponse, type UpdateUploadLinkRequest } from "../api/upload-links.api";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../types/upload-configuration";
import { useUpdateUploadLink } from "./use-upload-links";

vi.mock("../api/upload-links.api", () => ({ uploadLinksApi: { update: vi.fn() } }));

describe("saved upload-link settings", () => {
  it("refreshes the trip editor's summary immediately, preserving roster counts", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    client.setQueryData(QUERY_KEYS.passports.groups(), [{ group_id: "trip", group_name: "Old name", group_status: "active", total_passports: 12 }]);
    const response = {
      id: "trip", name: "New name", status: "active",
      upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, agent_employee_code_label: "Producer Code", passport_live_scan: false },
      custom_questions: [{ id: "question", label: "Activity", options: ["A", "B"], enabled: true, required: false }],
    } as UploadLinkResponse;
    vi.mocked(uploadLinksApi.update).mockResolvedValue(response);
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => useUpdateUploadLink(), { wrapper });
    await act(() => result.current.mutateAsync({ id: "trip", name: "New name" } as UpdateUploadLinkRequest & { id: string }));
    expect(client.getQueryData(QUERY_KEYS.passports.groups())).toEqual([expect.objectContaining({
      group_id: "trip", group_name: "New name", total_passports: 12,
      upload_configuration: response.upload_configuration, custom_questions: response.custom_questions,
    })]);
  });
});
