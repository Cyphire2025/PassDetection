import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog, TextInputDialog } from "./modal";

describe("modal keyboard boundary", () => {
  it("focuses the safe action, traps focus, closes with Escape, and restores the trigger", async () => {
    const onClose = vi.fn();
    const { rerender } = render(<button>Delete group</button>);
    const trigger = screen.getByRole("button", { name: "Delete group" });
    trigger.focus();
    rerender(
      <>
        <button>Delete group</button>
        <ConfirmDialog
          isOpen
          title="Delete group?"
          description="This action cannot be undone."
          confirmLabel="Delete"
          variant="danger"
          onConfirm={vi.fn()}
          onClose={onClose}
        />
      </>,
    );

    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = screen.getByRole("button", { name: "Delete" });
    const close = screen.getByRole("button", { name: "Close dialog" });
    expect(cancel).toHaveFocus();

    confirm.focus();
    await userEvent.tab();
    expect(close).toHaveFocus();
    close.focus();
    await userEvent.tab({ shift: true });
    expect(confirm).toHaveFocus();

    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    rerender(<button>Delete group</button>);
    await waitFor(() => expect(screen.getByRole("button", { name: "Delete group" })).toHaveFocus());
  });

  it("does not dismiss an in-flight action", async () => {
    const onClose = vi.fn();
    render(
      <ConfirmDialog
        isOpen
        isLoading
        title="Delete group?"
        description="Deletion is running."
        confirmLabel="Delete"
        onConfirm={vi.fn()}
        onClose={onClose}
      />,
    );

    await userEvent.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("puts initial focus in the text input", () => {
    render(
      <TextInputDialog
        isOpen
        title="Rename group"
        description="Choose a unique name."
        label="Group name"
        value=""
        confirmLabel="Save"
        onValueChange={vi.fn()}
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("textbox", { name: "Group name" })).toHaveFocus();
  });
});
