import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { CompanyAgencySelector } from "./company-agency-scope";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn() } }));
describe("company agency lookup", () => {
  it("loads one bounded page at a time and debounces server search without choosing a tenant automatically", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [{ id: "agency", name: "Example agency" }], total: 1000, offset: 0, limit: 25 } });
    const onChange = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><CompanyAgencySelector value={null} onChange={onChange} /></QueryClientProvider>);
    await screen.findByRole("option", { name: "Example agency" });
    expect(apiClient.get).toHaveBeenCalledTimes(1);
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "More agencies" }));
    await waitFor(() => expect(apiClient.get).toHaveBeenLastCalledWith("/api/v1/gc-app/admin/agencies", expect.objectContaining({ params: { q: "", offset: 25, limit: 25 }, signal: expect.any(AbortSignal) })));
    fireEvent.change(screen.getByLabelText("Search agency workspaces"), { target: { value: "Target" } });
    await waitFor(() => expect(apiClient.get).toHaveBeenLastCalledWith("/api/v1/gc-app/admin/agencies", expect.objectContaining({ params: { q: "Target", offset: 0, limit: 25 }, signal: expect.any(AbortSignal) })));
  });
});
