import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { companyPeopleApi } from "../api/company-people.api";
import { CompanyPersonPage } from "./company-person-page";

vi.mock("./company-agency-scope", () => ({ useCompanyAgency: () => "agency" }));
vi.mock("../hooks/use-company-view-state", () => import("../test-support/navigation"));
vi.mock("../api/company-people.api", () => ({ companyPeopleApi: { record: vi.fn(), documents: vi.fn(), sources: vi.fn() } }));
const user: User = { id: "owner", role: "agency_admin", agency_id: "agency", full_name: "Owner", email: "owner@example.test", is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01" };
beforeEach(() => {
  vi.resetAllMocks();
  window.history.replaceState(null, "", "/companies/company/people/person?tab=data&peopleSearch=Jane&peopleSort=name_desc&submissions=multiple");
  useAuthStore.setState({ user, sessionVersion: 1, isChangingAccessLevel: false });
  vi.mocked(companyPeopleApi.record).mockResolvedValue({ id: "person", status: "active", display_name: "Jane Sample",
    revision: 2, contact_revision: 1, phone_number: null, phone_verified: false, current_document: null });
  vi.mocked(companyPeopleApi.documents).mockResolvedValue({ items: [], has_more: false, next_cursor: null });
  vi.mocked(companyPeopleApi.sources).mockResolvedValue({ items: [], has_more: false, next_cursor: null });
});

it("renders a full page and returns to the exact filtered company view", async () => {
  render(<QueryClientProvider client={new QueryClient()}><CompanyPersonPage companyId="company" personId="person" /></QueryClientProvider>);
  await screen.findByRole("heading", { level: 1, name: "Jane Sample" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  const back = new URL(screen.getByRole("link", { name: "Back to company" }).getAttribute("href")!, "https://local.test");
  expect(back.pathname).toBe("/companies/company");
  expect(back.searchParams.get("peopleSearch")).toBe("Jane");
  expect(back.searchParams.get("submissions")).toBe("multiple");
  expect(screen.getByRole("tab", { name: "Documents & submissions" })).toHaveAttribute("aria-selected", "true");
  act(() => useAuthStore.setState({ isChangingAccessLevel: true }));
  await waitFor(() => expect(screen.queryByRole("heading", { level: 1, name: "Jane Sample" })).not.toBeInTheDocument());
});
