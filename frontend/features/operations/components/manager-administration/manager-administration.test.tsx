import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ManagerAccount } from "../../api/operations.api";
import { DeleteManagerDialog } from "./delete-manager-dialog";
import { CreateManagerDialog } from "./create-manager-dialog";
import { ManagerInvitationDialog } from "./manager-invitation-dialog";
import { ManagerAdministrationPage } from "./manager-administration-page";

const mocks = vi.hoisted(() => ({ copy: vi.fn(), create: vi.fn(), remove: vi.fn() }));
vi.mock("@/lib/utils/clipboard", () => ({ copyTextToClipboard: mocks.copy }));
vi.mock("../../hooks/use-operations", () => ({
  useManagers: () => ({ data: [], isLoading: false }),
  useCreateManager: () => ({ mutateAsync: mocks.create, isPending: false }),
  useDeleteManager: () => ({ mutate: mocks.remove, isPending: false }),
}));
const manager: ManagerAccount = {
  id: "manager-1", full_name: "Synthetic Manager", email: "manager@example.test",
  role: "agency_manager", agency_id: "agency-1", is_active: true,
  created_at: "2026-10-30", last_login_at: null, created_groups: [], assigned_groups: [],
  credential_state: "invited", activation_token: "synthetic+token/test",
};
beforeEach(() => { vi.clearAllMocks(); });

it("contains focus in deletion confirmation and prevents closing or changing scope while pending", async () => {
  const close = vi.fn();
  const props = { manager, deleteOwnedData: false, isLoading: false,
    onDeleteOwnedDataChange: vi.fn(), onClose: close, onConfirm: vi.fn() };
  const { rerender } = render(<DeleteManagerDialog {...props} />);
  const dialog = screen.getByRole("dialog", { name: "Delete Manager Account" });
  const cancel = within(dialog).getByRole("button", { name: "Cancel" });
  await waitFor(() => expect(cancel).toHaveFocus());
  const checkbox = within(dialog).getByRole("checkbox");
  act(() => checkbox.focus());
  fireEvent.keyDown(checkbox, { key: "Tab", shiftKey: true });
  expect(within(dialog).getByRole("button", { name: "Delete Manager" })).toHaveFocus();
  rerender(<DeleteManagerDialog {...props} isLoading />);
  expect(within(dialog).getByRole("checkbox")).toBeDisabled();
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(close).not.toHaveBeenCalled();
  rerender(<DeleteManagerDialog {...props} />);
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(close).toHaveBeenCalledTimes(1);
});

it("disables the create dialog close button throughout account creation", () => {
  const close = vi.fn();
  render(<CreateManagerDialog form={{ full_name: "", email: "" }} formError={null}
    isLoading onClose={close} onFormChange={vi.fn()} onSubmit={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(close).not.toHaveBeenCalled();
});

it("reports denied clipboard access and permits a successful explicit retry", async () => {
  mocks.copy.mockRejectedValueOnce(new Error("clipboard denied")).mockResolvedValueOnce(undefined);
  render(<ManagerInvitationDialog manager={manager} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("copy it manually");
  const copiedUrl = new URL(mocks.copy.mock.calls[0][0]);
  expect(copiedUrl.origin).toBe(window.location.origin);
  expect(copiedUrl.pathname).toBe("/activate");
  expect(copiedUrl.searchParams.get("token")).toBe(manager.activation_token);
  fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
  expect(await screen.findByRole("button", { name: "Copied" })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("admits one creation before pending state renders and retains the one-time invitation", async () => {
  let resolveCreation: (value: ManagerAccount) => void = () => {};
  mocks.create.mockImplementation(() => new Promise<ManagerAccount>((resolve) => { resolveCreation = resolve; }));
  render(<ManagerAdministrationPage />);
  fireEvent.click(screen.getByRole("button", { name: "Create Manager" }));
  fireEvent.change(screen.getByLabelText(/Full name/), { target: { value: manager.full_name } });
  const email = screen.getByLabelText(/Email/);
  fireEvent.change(email, { target: { value: manager.email } });
  const form = email.closest("form")!;
  act(() => { fireEvent.submit(form); fireEvent.submit(form); });
  expect(mocks.create).toHaveBeenCalledExactlyOnceWith({ full_name: manager.full_name, email: manager.email });
  await act(async () => { resolveCreation(manager); });
  expect(screen.getByRole("dialog", { name: "Manager invitation created" })).toBeVisible();
});
