import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  canManagePassportRetention,
  PassportRetentionControl,
} from "./passport-retention-control";

const mutate = vi.fn();
const reset = vi.fn();
const usePassportRetention = vi.fn();
const useUpdatePassportRetention = vi.fn();

vi.mock("../hooks/use-passport-retention", () => ({
  usePassportRetention: (...args: unknown[]) => usePassportRetention(...args),
  useUpdatePassportRetention: (...args: unknown[]) => useUpdatePassportRetention(...args),
}));

describe("passport retention control", () => {
  beforeEach(() => {
    mutate.mockReset();
    reset.mockReset();
    usePassportRetention.mockReturnValue({
      data: {
        group_id: "group-1",
        passport_purge_at: "2027-01-15T10:00:00Z",
        passport_retention_days_applied: 365,
        legal_hold: true,
        legal_hold_reason: "Active legal review",
        legal_hold_set_at: "2026-08-22T10:00:00Z",
        legal_hold_set_by_user_id: "admin-1",
      },
      isLoading: false,
      error: null,
    });
    useUpdatePassportRetention.mockReturnValue({
      mutate,
      reset,
      isPending: false,
      error: null,
    });
  });

  it("limits management to the backend-supported administrator roles", () => {
    expect(canManagePassportRetention("super_admin")).toBe(true);
    expect(canManagePassportRetention("agency_admin")).toBe(true);
    expect(canManagePassportRetention("agency_manager")).toBe(false);
    expect(canManagePassportRetention("agency_staff")).toBe(false);
    expect(canManagePassportRetention(null)).toBe(false);
  });

  it("shows the explicit schedule and requires an audited reason before release", async () => {
    const user = userEvent.setup();
    render(<PassportRetentionControl groupId="group-1" groupName="Singapore 2027" />);

    expect(screen.getByText("Legal hold active")).toBeInTheDocument();
    expect(screen.getByText("Active legal review")).toBeInTheDocument();
    expect(screen.getByText("365 days")).toBeInTheDocument();

    const trigger = screen.getByRole("button", { name: "Release legal hold" });
    trigger.focus();
    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "Release passport legal hold" });
    expect(dialog).toBeInTheDocument();
    const reason = screen.getByRole("textbox", { name: "Audit reason" });
    expect(reason).toHaveFocus();
    const confirm = within(dialog).getByRole("button", { name: "Release legal hold" });
    expect(confirm).toBeDisabled();

    await user.type(reason, "  Legal review completed   and approved  ");
    await user.click(confirm);

    expect(mutate).toHaveBeenCalledWith(
      { legalHold: false, reason: "Legal review completed and approved" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("closes with Escape and restores focus when no update is running", async () => {
    const user = userEvent.setup();
    render(<PassportRetentionControl groupId="group-1" groupName="Singapore 2027" />);
    const trigger = screen.getByRole("button", { name: "Release legal hold" });
    await user.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
