import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog, TextInputDialog } from "./modal";
import { ModalFocusTracker } from "./modal-focus-return";

describe("modal keyboard boundary", () => {
  it("returns to a pointer trigger that WebKit did not focus, including a nested icon target", async () => {
    function PointerDialog() {
      const [open, setOpen] = useState(false);
      return <><ModalFocusTracker /><button onClick={() => setOpen(true)}><span>Pointer opener</span></button>
        <ConfirmDialog isOpen={open} title="Pointer dialog" description="Confirm" confirmLabel="Proceed" onConfirm={vi.fn()} onClose={() => setOpen(false)} /></>;
    }
    render(<PointerDialog />);
    const trigger = screen.getByRole("button", { name: "Pointer opener" });
    fireEvent.pointerDown(screen.getByText("Pointer opener"));
    fireEvent.click(trigger);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(trigger).toHaveFocus();
  });
  it("does not reuse an earlier pointer target for a later keyboard activation", async () => {
    function KeyboardDialog() {
      const [open, setOpen] = useState(false);
      return <><ModalFocusTracker /><button>Earlier pointer</button><button onClick={() => setOpen(true)}>Keyboard opener</button>
        <ConfirmDialog isOpen={open} title="Keyboard dialog" description="Confirm" confirmLabel="Proceed" onConfirm={vi.fn()} onClose={() => setOpen(false)} /></>;
    }
    render(<KeyboardDialog />);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Earlier pointer" }));
    const trigger = screen.getByRole("button", { name: "Keyboard opener" }); trigger.focus();
    await userEvent.keyboard("{Enter}{Escape}");
    expect(trigger).toHaveFocus();
  });
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
    expect(screen.getByRole("button", { name: "Close dialog" })).toBeDisabled();
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

  it("edits a name and blocks empty or pending confirmation without dismissing", async () => {
    const confirm = vi.fn(); const close = vi.fn(); const changed = vi.fn();
    const props = { isOpen: true, title: "Rename", description: "Choose a name", label: "Name", confirmLabel: "Save", onConfirm: confirm, onClose: close, onValueChange: changed };
    const { rerender } = render(<TextInputDialog {...props} value="   " />);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "New name" } });
    expect(changed).toHaveBeenCalledWith("New name");
    rerender(<TextInputDialog {...props} value="New name" />);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    rerender(<TextInputDialog {...props} value="New name" isLoading />);
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Close dialog" })).toBeDisabled();
    expect(close).not.toHaveBeenCalled();
    rerender(<TextInputDialog {...props} value="New name" isOpen={false} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("makes background inert and contains programmatic focus without losing prior inert state", () => {
    const { rerender } = render(<><button>Background</button><aside inert>Already unavailable</aside></>);
    const background = screen.getByRole("button", { name: "Background" });
    background.focus();
    rerender(<><button>Background</button><aside inert>Already unavailable</aside><ConfirmDialog isOpen title="Confirm" description="Choose" confirmLabel="Proceed" onConfirm={vi.fn()} onClose={vi.fn()} /></>);
    expect(background).toHaveAttribute("inert");
    background.focus();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    rerender(<><button>Background</button><aside inert>Already unavailable</aside></>);
    expect(background).not.toHaveAttribute("inert");
    expect(screen.getByText("Already unavailable")).toHaveAttribute("inert");
    expect(background).toHaveFocus();
  });

  it("closes only the nested dialog and restores its trigger before the outer dialog", async () => {
    function Nested() {
      const [outer, setOuter] = useState(false);
      const [inner, setInner] = useState(false);
      return <><button onClick={() => setOuter(true)}>Open outer</button>
        <ConfirmDialog isOpen={outer} title="Outer" description="Outer choice" confirmLabel="Open inner" onConfirm={() => setInner(true)} onClose={() => setOuter(false)} />
        <ConfirmDialog isOpen={inner} title="Inner" description="Inner choice" confirmLabel="Accept" onConfirm={vi.fn()} onClose={() => setInner(false)} /></>;
    }
    render(<Nested />);
    await userEvent.click(screen.getByRole("button", { name: "Open outer" }));
    const outerTrigger = screen.getByRole("button", { name: "Open inner" });
    await userEvent.click(outerTrigger);
    const inner = screen.getByRole("dialog", { name: "Inner" });
    expect(within(inner).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Inner" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Outer" })).toBeInTheDocument();
    expect(outerTrigger).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Open outer" })).toHaveFocus();
    expect(document.body.style.overflow).not.toBe("hidden");
  });

  it("returns to the workspace if a successful mutation removed the trigger", () => {
    const { rerender } = render(<main><button>Remove item</button></main>);
    screen.getByRole("button", { name: "Remove item" }).focus();
    rerender(<main><button>Remove item</button><ConfirmDialog isOpen title="Remove?" description="Confirm" confirmLabel="Remove" onConfirm={vi.fn()} onClose={vi.fn()} /></main>);
    rerender(<main>Nothing left</main>);
    expect(screen.getByRole("main")).toHaveFocus();
    expect(screen.getByRole("main")).not.toHaveAttribute("tabindex");
  });

  it("contains Tab at the dialog when all actions are disabled", () => {
    render(<ConfirmDialog isOpen isLoading title="Working" description="Wait" confirmLabel="Accept" onConfirm={vi.fn()} onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(dialog).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(dialog).toHaveFocus();
  });
});
