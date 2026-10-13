import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { EditGroupDialog } from "@/features/passports/components/edit-group-dialog";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), patch: vi.fn(), post: vi.fn() } }));
vi.mock("./company-picker", () => ({ CompanyPicker: ({ onChange, value }: { onChange: (value: unknown) => void; value: { name: string } | null }) => <><p>{value?.name ?? "Unassigned"}</p><button type="button" onClick={() => onChange({ id: "target", name: "Target Company", status: "active" })}>Select target company</button></> }));

const base = { id: "group-1", agency_id: "agency-1", name: "Historical Group", status: "archived", import_only: true, company_id: null, company: null, company_revision: 0 } as UploadLinkResponse;
const target = { id: "target", name: "Target Company", status: "active" as const };
function setup(group = base, onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  useAuthStore.setState({ user: { role: "agency_admin", is_active: true, agency_id: "agency-1" } as User });
  const view = render(<QueryClientProvider client={client}><EditGroupDialog group={group} onClose={onClose} /></QueryClientProvider>);
  return { ...view, client, onClose };
}
beforeEach(() => vi.clearAllMocks());

describe("company assignment", () => {
  it.each(["active", "closed", "archived"] as const)("main save persists legacy %s import assignment with revision zero", async (status) => {
    vi.mocked(apiClient.patch).mockResolvedValue({ data: { ...base, company_id: target.id, company: target, company_revision: 1 } });
    const { onClose } = setup({ ...base, status });
    fireEvent.click(screen.getByRole("button", { name: "Select target company" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(apiClient.patch).toHaveBeenCalledExactlyOnceWith("/api/v1/upload-links/group-1/company", { company_id: "target", expected_revision: 0 }, { params: { agency_id: "agency-1" } });
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(apiClient.patch).toHaveBeenCalledTimes(1);
  });

  it("requires an impact preview, reason and both expected revisions before reassignment", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { group_id: base.id, source_company_id: "previous", target_company_id: "target", expected_revision: 4, expected_roster_revision: 17, submission_records: 700, accepted_participations: 400, active_claims: 2, active_grants: 3, manager_conflict: false, can_reassign: true } });
    vi.mocked(apiClient.post).mockResolvedValue({ data: { ...base, company_id: target.id, company: target, company_revision: 5 } });
    setup({ ...base, company_id: "previous", company: { id: "previous", name: "Previous", status: "active" }, company_revision: 4 });
    fireEvent.click(screen.getByRole("button", { name: "Select target company" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const dialog = await screen.findByRole("dialog", { name: "Review company reassignment" });
    await within(dialog).findByText("700");
    expect(within(dialog).getByRole("button", { name: "Confirm reassignment" })).toBeDisabled();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Reason for reassignment" }), { target: { value: "Correcting client ownership" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm reassignment" }));
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/api/v1/companies/target/reassignments/group-1", { expected_revision: 4, expected_roster_revision: 17, reason: "Correcting client ownership" }, { params: { agency_id: "agency-1" } });
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("keeps manager-conflicted reassignment blocked", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { expected_revision: 4, expected_roster_revision: 17, submission_records: 700, accepted_participations: 400, active_claims: 0, active_grants: 0, manager_conflict: true, can_reassign: false } });
    setup({ ...base, company_id: "previous", company: { id: "previous", name: "Previous", status: "active" }, company_revision: 4 });
    fireEvent.click(screen.getByRole("button", { name: "Select target company" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByText(/client-manager assignment conflicts/);
    fireEvent.change(screen.getByRole("textbox", { name: "Reason for reassignment" }), { target: { value: "Correcting client ownership" } });
    expect(screen.getByRole("button", { name: "Confirm reassignment" })).toBeDisabled();
    expect(apiClient.patch).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("merges saved list state and invalidates both company and passport group views", async () => {
    const saved = { ...base, company_id: target.id, company: target, company_revision: 1 };
    vi.mocked(apiClient.patch).mockResolvedValue({ data: saved });
    const { client, onClose } = setup();
    const listKey = ["upload-links", "list", "archived"];
    client.setQueryData(listKey, [base, { ...base, agency_id: "different-agency" }]);
    client.setQueryData(["companies", base.agency_id, "summary"], {});
    client.setQueryData(["passports", "groups"], []);
    fireEvent.click(screen.getByRole("button", { name: "Select target company" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(client.getQueryData(listKey)).toEqual([saved, { ...base, agency_id: "different-agency" }]);
    expect(client.getQueryState(["companies", base.agency_id, "summary"])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["passports", "groups"])?.isInvalidated).toBe(true);
  });

  it("keeps a failed assignment draft and retries only through an explicit save", async () => {
    vi.mocked(apiClient.patch).mockRejectedValueOnce({ message: "Company assignment changed; refresh and retry" })
      .mockResolvedValueOnce({ data: { ...base, company_id: target.id, company: target, company_revision: 1 } });
    const { onClose } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Select target company" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Company assignment changed");
    expect(screen.getByText(target.name)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(apiClient.patch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(apiClient.patch).toHaveBeenCalledTimes(2);
  });

  it("prevents duplicate saves and dismissal while saving", async () => {
    let complete!: (result: unknown) => void;
    vi.mocked(apiClient.patch).mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
    const { onClose } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Select target company" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Group" });
    const save = within(dialog).getByRole("button", { name: "Save changes" });
    fireEvent.click(save);
    fireEvent.click(save);
    expect(dialog).toHaveAttribute("aria-busy", "true");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(apiClient.patch).toHaveBeenCalledTimes(1);
    await act(async () => complete({ data: { ...base, company_id: target.id, company: target, company_revision: 1 } }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });

  it("does not repeat a committed assignment if saving the renamed group fails", async () => {
    const saved = { ...base, company_id: target.id, company: target, company_revision: 1 };
    vi.mocked(apiClient.patch).mockResolvedValueOnce({ data: saved })
      .mockRejectedValueOnce({ message: "The group name could not be saved." })
      .mockResolvedValueOnce({ data: { ...saved, name: "Renamed import" } });
    const { onClose } = setup();
    fireEvent.change(screen.getByRole("textbox", { name: "Group name" }), { target: { value: "Renamed import" } });
    fireEvent.click(screen.getByRole("button", { name: "Select target company" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Company assignment was saved. The group name could not be saved.");
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(vi.mocked(apiClient.patch).mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/upload-links/group-1/company", "/api/v1/upload-links/group-1", "/api/v1/upload-links/group-1",
    ]);
  });

  it("discards delayed assignment results after the authentication session changes", async () => {
    let complete!: (result: unknown) => void;
    vi.mocked(apiClient.patch).mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
    const { client, onClose } = setup();
    const key = ["upload-links", "list", "archived"];
    client.setQueryData(key, [base]);
    fireEvent.click(screen.getByRole("button", { name: "Select target company" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    act(() => useAuthStore.setState((state) => ({ sessionVersion: state.sessionVersion + 1 })));
    await act(async () => complete({ data: { ...base, company_id: target.id, company: target, company_revision: 1 } }));
    expect(client.getQueryData(key)).toEqual([base]);
    expect(onClose).not.toHaveBeenCalled();
  });
});
