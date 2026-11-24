import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const boundary = vi.hoisted(() => ({ copy: vi.fn(), create: vi.fn(), creating: false, reset: vi.fn() }));
vi.mock("@/lib/utils/clipboard", () => ({ copyTextToClipboard: boundary.copy }));
vi.mock("../hooks/use-operations", () => ({
  useStaffAccessAccounts: () => ({ data: [], isLoading: false }), useAdminGroups: () => ({ data: [] }),
  useCreateStaff: () => ({ mutateAsync: boundary.create, isPending: boundary.creating }),
  useAssignStaffGroups: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useManagedAccountActions: () => ({
    resetPassword: { mutateAsync: boundary.reset, isPending: false },
    resetMfa: { isPending: false }, revokeSessions: { isPending: false }, setStatus: { isPending: false }, deleteAccount: { isPending: false },
  }),
}));
import { ManagedAccountControls } from "./managed-account-controls";
import { ManagedAccountsPanel } from "./managed-accounts-panel";

describe("managed credential link copy recovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    boundary.creating = false;
    boundary.copy.mockRejectedValue(new Error("Synthetic clipboard rejection"));
    boundary.create.mockResolvedValue({ full_name: "Synthetic Staff", activation_token: "synthetic-token" });
    boundary.reset.mockResolvedValue({ activation_token: "synthetic-reset-token" });
  });

  it("shows a manual-copy recovery when copying a staff invitation fails", async () => {
    render(<ManagedAccountsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Create Staff" }));
    const dialog = screen.getByRole("dialog", { name: "Create Staff" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Full name" }), { target: { value: "Synthetic Staff" } });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Email" }), { target: { value: "staff@example.test" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create Staff" }));
    fireEvent.click(await screen.findByRole("button", { name: "Copy activation link" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("copy it manually");
    expect(boundary.copy).toHaveBeenCalledWith(expect.stringContaining("token=synthetic-token"));
    expect(screen.queryByRole("button", { name: "Copied" })).not.toBeInTheDocument();
  });

  it("handles credential reset clipboard rejection without losing the issued link", async () => {
    render(<ManagedAccountControls accountId="account-a" accountName="Synthetic Staff" isActive />);
    fireEvent.click(screen.getByRole("button", { name: "Open actions for Synthetic Staff" }));
    fireEvent.click(await screen.findByRole("button", { name: "Issue reset link" }));
    fireEvent.click(screen.getByRole("button", { name: "Issue reset link" }));
    fireEvent.click(await screen.findByRole("button", { name: "Copy link" }));
    expect(await screen.findByText(/copy it manually/)).toBeInTheDocument();
    expect(screen.getByText(/token=synthetic-reset-token/)).toBeInTheDocument();
  });

  it("disables every dismissal button while staff creation is pending", () => {
    boundary.creating = true;
    render(<ManagedAccountsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Create Staff" }));
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });
});
