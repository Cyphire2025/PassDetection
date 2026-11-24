import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { expect, it, vi } from "vitest";
import { groupUpdatesApi, type GroupUpdatePreview } from "../api/group-updates.api";
import { useGroupUpdateAudience } from "./use-group-update-audience";

vi.mock("../api/group-updates.api", () => ({ groupUpdatesApi: { preview: vi.fn() } }));

it("stops automatic private audience polling after denial and allows an explicit refresh", async () => {
  vi.useFakeTimers();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const response = { recipients: [{ latest_update_status: "queued" }] } as GroupUpdatePreview;
  vi.mocked(groupUpdatesApi.preview).mockReset().mockResolvedValueOnce(response).mockRejectedValue({ status: 403, code: "FORBIDDEN" });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const view = renderHook(() => useGroupUpdateAudience("synthetic-group"), { wrapper });
  try {
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(view.result.current.data).toBeDefined();
    await act(async () => { await vi.advanceTimersByTimeAsync(5_001); });
    expect(groupUpdatesApi.preview).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(groupUpdatesApi.preview).toHaveBeenCalledTimes(2);
    vi.mocked(groupUpdatesApi.preview).mockResolvedValue({ ...response, recipients: [] });
    await act(async () => { expect((await view.result.current.refetch()).isSuccess).toBe(true); });
    expect(groupUpdatesApi.preview).toHaveBeenCalledTimes(3);
  } finally {
    view.unmount();
    client.clear();
    vi.useRealTimers();
  }
});
