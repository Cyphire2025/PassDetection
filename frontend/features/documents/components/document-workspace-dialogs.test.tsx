import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AbortIncompleteUploadDialog, RemoveAssignmentsDialog } from "./document-workspace-dialogs";

describe("document destructive dialog keyboard behavior", () => {
  it.each(["abort", "remove"])("%s enters the safe action, traps both directions, escapes and restores", async (kind) => {
    const onClose = vi.fn();
    const { rerender } = render(<button>Document action</button>);
    const trigger = screen.getByRole("button", { name: "Document action" });
    trigger.focus();
    rerender(<><button>Document action</button>{kind === "abort"
      ? <AbortIncompleteUploadDialog uploadCount={2} pending={false} error={null} onClose={onClose} onConfirm={vi.fn()} />
      : <RemoveAssignmentsDialog passengerCount={2} documentCount={2} pending={false} error={null} onClose={onClose} onKeepFiles={vi.fn()} onDeleteFiles={vi.fn()} />}</>);
    expect(screen.getByRole("button", { name: kind === "abort" ? "Keep upload" : "Cancel" })).toHaveFocus();
    const buttons = screen.getAllByRole("button").filter((button) => !button.hasAttribute("inert"));
    const first = buttons[0]; const last = buttons.at(-1)!;
    last.focus(); await userEvent.tab(); expect(first).toHaveFocus();
    first.focus(); await userEvent.tab({ shift: true }); expect(last).toHaveFocus();
    await userEvent.keyboard("{Escape}"); expect(onClose).toHaveBeenCalledOnce();
    rerender(<button>Document action</button>); expect(trigger).toHaveFocus();
  });
});
