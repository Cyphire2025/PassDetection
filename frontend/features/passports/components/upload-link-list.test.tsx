import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User, UserRole } from "@/types";
import { uploadLinksApi, type UploadLinkResponse } from "../api/upload-links.api";
import { UploadLinkList } from "./upload-link-list";

vi.mock("../api/upload-links.api", () => ({
  uploadLinksApi: { list: vi.fn(), permanentDelete: vi.fn() },
}));

const archivedGroup: UploadLinkResponse = {
  id: "archived-group", name: "NIPUN", token: "group-token", status: "archived",
  created_at: "2026-09-24T00:00:00Z", departure_cities: [],
  agency_id: "agency", created_by_user_id: "admin", closed_at: "2026-09-24T01:00:00Z",
  destination: null, travel_date: null, return_date: null, timezone: "Asia/Kolkata",
  package_name: null, base_city_enabled: false, nearest_international_airport_enabled: false,
  staff_code_enabled: false, agent_employee_code_enabled: false, meal_preference_enabled: false,
  require_selfie: false, allow_files_from_device: true, ask_nearest_domestic_airport: false,
  relation_with_qualifier_enabled: false, designation_enabled: false, agency_dealership_name_enabled: false,
  custom_questions: [], custom_details: [], qualifier_relation_options: [], notes: null,
  deleted_at: null, deleted_passport_count: 0, deletion_retained_records: false,
};

function renderList(role: UserRole = "agency_admin") {
  useAuthStore.setState({
    user: { id: "admin", role, agency_id: "agency", is_active: true } as User,
    isAuthenticated: true, hasHydrated: true,
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<QueryClientProvider client={queryClient}><UploadLinkList /></QueryClientProvider>);
}

async function openDeleteDialog() {
  // Both responsive table layouts exist in jsdom; either invokes the same action.
  const triggers = await screen.findAllByRole("button", { name: "Delete" });
  fireEvent.click(triggers[0]);
  return screen.getByRole("dialog", { name: "Delete Archived Group" });
}

beforeEach(() => {
  vi.mocked(uploadLinksApi.list).mockReset().mockImplementation(async (status) => (
    status === "archived" ? [archivedGroup] : []
  ));
  vi.mocked(uploadLinksApi.permanentDelete).mockReset();
});

describe("archived group deletion feedback", () => {
  it.each([
    { status: 409, code: "HTTP_409", message: "Cancel pending document deliveries before permanently deleting this group." },
    { status: 403, code: "AUTHORIZATION_ERROR", message: "You cannot delete data for this group" },
    { code: "STEP_UP_CANCELLED", message: "Identity confirmation was cancelled." },
    { code: "NETWORK_ERROR", message: "Unable to reach the server. Check your connection and try again." },
  ])("shows $code inside the open dialog without retrying or changing retention", async (error) => {
    vi.mocked(uploadLinksApi.permanentDelete).mockRejectedValue(error);
    renderList();
    const dialog = await openDeleteDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: /^Delete passport records/ }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(error.message);
    expect(dialog).toBeInTheDocument();
    expect(uploadLinksApi.permanentDelete).toHaveBeenCalledExactlyOnceWith("archived-group", false);
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeEnabled();
  });

  it("shows a useful fallback when an unexpected error has no message", async () => {
    vi.mocked(uploadLinksApi.permanentDelete).mockRejectedValue({ code: "UNEXPECTED_ERROR" });
    renderList();
    const dialog = await openDeleteDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: /^Delete passport records/ }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The group could not be deleted. Please try again.");
  });

  it("shows retention errors and clears them when the dialog is reopened", async () => {
    vi.mocked(uploadLinksApi.permanentDelete).mockRejectedValue({ message: "This group was already deleted using a different retention choice." });
    renderList();
    const dialog = await openDeleteDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: /^Keep passport records/ }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("different retention choice");
    expect(uploadLinksApi.permanentDelete).toHaveBeenCalledExactlyOnceWith("archived-group", true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    const reopened = await openDeleteDialog();
    expect(within(reopened).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("clears the error for a manual retry, prevents duplicate actions or dismissal while pending, and closes on success", async () => {
    let complete!: () => void;
    vi.mocked(uploadLinksApi.permanentDelete)
      .mockRejectedValueOnce({ message: "A document delivery is still in progress." })
      .mockImplementationOnce(() => new Promise<void>((resolve) => { complete = resolve; }));
    renderList();
    const dialog = await openDeleteDialog();
    const deleteButton = within(dialog).getByRole("button", { name: /^Delete passport records/ });
    fireEvent.click(deleteButton);
    await within(dialog).findByRole("alert");
    fireEvent.click(deleteButton);
    await waitFor(() => expect(dialog).toHaveAttribute("aria-busy", "true"));
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
    for (const button of within(dialog).getAllByRole("button")) expect(button).toBeDisabled();
    expect(within(dialog).getByRole("status")).toHaveTextContent("Deleting group");
    fireEvent.keyDown(dialog, { key: "Escape" });
    fireEvent.click(deleteButton);
    expect(dialog).toBeInTheDocument();
    expect(uploadLinksApi.permanentDelete).toHaveBeenCalledTimes(2);
    await act(async () => { complete(); });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it.each(["agency_manager", "agency_staff"] as const)("keeps permanent deletion hidden for %s", async (role) => {
    renderList(role);
    await screen.findAllByText("NIPUN");
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(uploadLinksApi.permanentDelete).not.toHaveBeenCalled();
  });
});
