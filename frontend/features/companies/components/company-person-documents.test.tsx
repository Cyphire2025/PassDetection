import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { companyPeopleApi } from "../api/company-people.api";
import { CompanyPersonDocuments } from "./company-person-documents";
import type { CompanyPersonRecord } from "../types/company-people";

vi.mock("../api/company-people.api", () => ({ companyPeopleApi: { documents: vi.fn(), asset: vi.fn(), sources: vi.fn(), sourceAsset: vi.fn() } }));
const user: User = { id: "owner", role: "agency_admin", agency_id: "agency", full_name: "Owner", email: "owner@example.test", is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01" };
const version = { id: "version", passport_id: "passport", revision_number: 1, status: "accepted", created_at: "2026-01-01T00:00:00Z", change_kind: "initial", is_current: true, fields: {}, assets: [{ id: "asset", side: "front", availability: "available", content_type: "image/jpeg", byte_size: 5 }] };
const record: CompanyPersonRecord = { id: "person", status: "active", revision: 2, display_name: "Person", contact_revision: 1, phone_number: null, phone_verified: false, current_document: null };
function mount(value = record) {
  return render(<QueryClientProvider client={new QueryClient()}><CompanyPersonDocuments agencyId="agency" companyId="company" record={value} onBusy={vi.fn()} onSaved={vi.fn()} /></QueryClientProvider>);
}
beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({ user, sessionVersion: 1, isChangingAccessLevel: false });
  vi.mocked(companyPeopleApi.documents).mockResolvedValue({ items: [version], next_cursor: null, has_more: false });
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:private-company-document"), revokeObjectURL: vi.fn() }));
});

describe("company document preview", () => {
  it("opens original trip documents only on request without treating them as accepted versions", async () => {
    vi.mocked(companyPeopleApi.sources).mockResolvedValue({ items: [{ id: "legacy-source", group_id: "old-group", group_name: "Earlier trip", created_at: "2025-01-01", revision_number: 2, available_sides: ["front"] }], has_more: false, next_cursor: null });
    vi.mocked(companyPeopleApi.sourceAsset).mockResolvedValue(new Blob(["old image"], { type: "image/jpeg" }));
    mount();
    await screen.findByRole("button", { name: "Original trip documents" });
    expect(companyPeopleApi.sources).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Original trip documents" }));
    const open = await screen.findByRole("button", { name: "View original front from Earlier trip" });
    expect(companyPeopleApi.sourceAsset).not.toHaveBeenCalled();
    fireEvent.click(open);
    await screen.findByRole("img", { name: "front document" });
    expect(companyPeopleApi.sourceAsset).toHaveBeenCalledExactlyOnceWith("agency", "company", "person", "legacy-source", "front", expect.any(AbortSignal));
    expect(companyPeopleApi.asset).not.toHaveBeenCalled();
  });
  it("fetches one authorized blob only after opening and revokes it on close", async () => {
    vi.mocked(companyPeopleApi.asset).mockResolvedValue(new Blob(["image"], { type: "image/jpeg" }));
    mount();
    const open = await screen.findByRole("button", { name: "View front from version 1" });
    expect(companyPeopleApi.asset).not.toHaveBeenCalled();
    fireEvent.click(open);
    await screen.findByRole("img", { name: "front document" });
    expect(companyPeopleApi.asset).toHaveBeenCalledExactlyOnceWith("agency", "company", "person", "asset", expect.any(AbortSignal));
    fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private-company-document");
  });

  it("aborts an in-flight blob and does not display its late response after access changes", async () => {
    let signal: AbortSignal | undefined;
    let finish!: (value: Blob) => void;
    vi.mocked(companyPeopleApi.asset).mockImplementation((_agency, _company, _person, _asset, nextSignal) => { signal = nextSignal; return new Promise((resolve) => { finish = resolve; }); });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "View front from version 1" }));
    await waitFor(() => expect(signal).toBeDefined());
    act(() => useAuthStore.setState({ isChangingAccessLevel: true }));
    expect(signal?.aborted).toBe(true);
    await act(async () => finish(new Blob(["late"], { type: "image/jpeg" })));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

it.each(["review_required", "blocked"])("keeps %s identities locked for document uploads", async (status) => {
  mount({ ...record, status });
  await screen.findByRole("button", { name: "Original trip documents" });
  expect(screen.getByRole("button", { name: "Add document version" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("This identity needs review");
  expect(screen.queryByLabelText("New image")).not.toBeInTheDocument();
});
it("starts the first reviewed passport as a new version with no historical fields prefilled", async () => {
  mount(record);
  fireEvent.click(await screen.findByRole("button", { name: "Add document version" }));
  expect(screen.getByLabelText("Update type")).toHaveValue("renewal");
  expect(screen.getByRole("option", { name: "New passport" })).toBeInTheDocument();
  expect(screen.getByLabelText("Document image")).toHaveValue("front");
  expect(screen.getByLabelText("Document image")).toBeDisabled();
  expect(screen.getByLabelText(/Passport number/i)).toHaveValue("");
});
