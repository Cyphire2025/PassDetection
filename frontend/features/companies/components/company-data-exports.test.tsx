import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { User } from "@/types";
import { useAuthStore } from "@/stores/auth.store";
import { companyDataExportsApi, type CompanyDataExport } from "../api/company-data-exports.api";
import { CompanyDataExports } from "./company-data-exports";

vi.mock("../api/company-data-exports.api", async (original) => {
  const actual = await original<typeof import("../api/company-data-exports.api")>();
  return { ...actual, companyDataExportsApi: { ...actual.companyDataExportsApi, create: vi.fn(), list: vi.fn(), parts: vi.fn() } };
});
const user: User = { id: "owner", role: "agency_admin", agency_id: "agency", full_name: "Owner", email: "owner@example.test", is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01" };
const job: CompanyDataExport = { id: "export", kind: "images", status: "succeeded", processed_count: 700, part_count: 2, created_at: "2026-10-14T00:00:00Z", expires_at: null, error_code: null };
beforeEach(() => { vi.clearAllMocks(); useAuthStore.setState({ user, sessionVersion: 1, isChangingAccessLevel: false }); });
function mount() { return render(<QueryClientProvider client={new QueryClient()}><CompanyDataExports agencyId="agency" companyId="company" /></QueryClientProvider>); }

describe("durable company exports", () => {
  it("loads persisted jobs and parts only on demand, with native protected downloads", async () => {
    vi.mocked(companyDataExportsApi.list).mockResolvedValue({ items: [job], next_cursor: null, has_more: false });
    vi.mocked(companyDataExportsApi.parts).mockResolvedValue({ items: [{ id: "part", part_number: 1, filename: "images-001.zip", content_type: "application/zip", byte_size: 1024, record_count: 400 }], next_cursor: null, has_more: false });
    mount();
    expect(companyDataExportsApi.list).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Recent exports" }));
    await screen.findByText("All document images · ZIP");
    expect(companyDataExportsApi.create).not.toHaveBeenCalled();
    expect(companyDataExportsApi.parts).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "View files" }));
    expect(await screen.findByRole("link", { name: /images-001.zip/ })).toHaveAttribute("href", "/api/v1/companies/company/data-exports/export/parts/part/download?agency_id=agency");
    expect(screen.getByRole("link", { name: /images-001.zip/ })).toHaveAttribute("download", "images-001.zip");
  });

  it("retries an uncertain create with the same idempotency key", async () => {
    vi.mocked(companyDataExportsApi.create).mockRejectedValueOnce(new Error("Connection interrupted")).mockResolvedValueOnce({ ...job, kind: "excel", status: "queued" });
    vi.mocked(companyDataExportsApi.list).mockResolvedValue({ items: [], next_cursor: null, has_more: false });
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Export Excel" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Export Excel" }));
    await waitFor(() => expect(companyDataExportsApi.create).toHaveBeenCalledTimes(2));
    expect(vi.mocked(companyDataExportsApi.create).mock.calls[0]).toEqual(vi.mocked(companyDataExportsApi.create).mock.calls[1]);
  });
});
