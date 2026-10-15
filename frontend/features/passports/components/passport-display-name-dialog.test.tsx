import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PassportDisplayNameDialog } from "./passport-display-name-dialog";

const state = vi.hoisted(() => ({
  query: {
    isPending: false,
    data: { id: "passenger-1", group_id: "group-1", client_name: "SHIVANAND", display_name: null as string | null, updated_at: "2026-10-15T09:00:00Z" },
    refetch: vi.fn(),
  },
  mutation: { isPending: false, mutateAsync: vi.fn() },
}));
vi.mock("../hooks/use-display-name", () => ({ useDisplayNameEditor: () => state }));
const original = { ...state.query.data };

beforeEach(() => {
  state.query.data = { ...original };
  state.query.isPending = false;
  state.query.refetch.mockReset();
  state.mutation.isPending = false;
  state.mutation.mutateAsync.mockReset().mockResolvedValue({});
});

describe("passenger display name", () => {
  it("saves only the alias and original revision, then closes", async () => {
    const close = vi.fn();
    render(<PassportDisplayNameDialog id="passenger-1" groupId="group-1" onClose={close} />);
    expect(screen.getByRole("dialog")).toHaveTextContent("Passport details and assigned documents stay unchanged");
    expect(screen.getByRole("button", { name: "Save display name" })).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: "Display name" }), { target: { value: "  SHIVANAND   A  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save display name" }));
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(state.mutation.mutateAsync).toHaveBeenCalledExactlyOnceWith({ display_name: "SHIVANAND A", expected_updated_at: original.updated_at });
  });

  it("loads an existing override and allows restoring the original name", async () => {
    state.query.data.display_name = "SHIVANAND A";
    render(<PassportDisplayNameDialog id="passenger-1" groupId="group-1" onClose={vi.fn()} />);
    expect(screen.getByRole("textbox", { name: "Display name" })).toHaveValue("SHIVANAND A");
    fireEvent.change(screen.getByRole("textbox", { name: "Display name" }), { target: { value: "SHIVANAND" } });
    fireEvent.click(screen.getByRole("button", { name: "Save display name" }));
    await waitFor(() => expect(state.mutation.mutateAsync).toHaveBeenCalledExactlyOnceWith({ display_name: "SHIVANAND", expected_updated_at: original.updated_at }));
  });

  it("keeps the draft on conflict and freezes the revision until explicit reload", async () => {
    state.mutation.mutateAsync.mockRejectedValue({ status: 409, message: "This passenger changed while you were editing." });
    const view = render(<PassportDisplayNameDialog id="passenger-1" groupId="group-1" onClose={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Display name" }), { target: { value: "My draft" } });
    state.query.data = { ...original, display_name: "Other staff edit", updated_at: "2026-10-16T09:00:00Z" };
    view.rerender(<PassportDisplayNameDialog id="passenger-1" groupId="group-1" onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Save display name" }));
    await screen.findByRole("alert");
    expect(state.mutation.mutateAsync).toHaveBeenCalledExactlyOnceWith({ display_name: "My draft", expected_updated_at: original.updated_at });
    expect(screen.getByRole("textbox", { name: "Display name" })).toHaveValue("My draft");
    expect(screen.getByRole("button", { name: "Save display name" })).toBeDisabled();
    state.query.refetch.mockResolvedValue({ data: state.query.data });
    fireEvent.click(screen.getByRole("button", { name: "Reload latest name" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Display name" })).toHaveValue("Other staff edit"));
  });

  it("does not send a duplicate save while the first is awaiting a response", async () => {
    let finish: (value: unknown) => void = () => {};
    state.mutation.mutateAsync.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const close = vi.fn();
    render(<PassportDisplayNameDialog id="passenger-1" groupId="group-1" onClose={close} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Display name" }), { target: { value: "Changed name" } });
    const save = screen.getByRole("button", { name: "Save display name" });
    fireEvent.click(save);
    fireEvent.click(save);
    expect(state.mutation.mutateAsync).toHaveBeenCalledOnce();
    finish({});
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
  });

  it("rejects an empty label and does not edit a passenger from another group", () => {
    const view = render(<PassportDisplayNameDialog id="passenger-1" groupId="group-1" onClose={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Display name" }), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Save display name" })).toBeDisabled();
    view.rerender(<PassportDisplayNameDialog id="passenger-1" groupId="other-group" onClose={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Save display name" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("could not be loaded in this group");
    expect(state.mutation.mutateAsync).not.toHaveBeenCalled();
  });
});
