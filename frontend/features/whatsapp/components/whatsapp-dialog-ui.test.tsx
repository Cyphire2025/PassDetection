import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { renderToString } from "react-dom/server";
import { expect, it, vi } from "vitest";
import { DialogFrame } from "./whatsapp-dialog-ui";

it("places the unchanged overlay in document.body outside transformed and scrolling ancestors", () => {
  const { container } = render(<div style={{ transform: "translateY(0)", overflow: "auto" }}><DialogFrame title="Review" onClose={vi.fn()}><button>Send</button></DialogFrame></div>);
  const dialog = screen.getByRole("dialog", { name: "Review" });
  expect(container.contains(dialog)).toBe(false);
  expect(dialog.parentElement?.parentElement).toBe(document.body);
  expect(dialog.parentElement).toHaveClass("fixed", "inset-0");
  expect(dialog).toHaveAttribute("aria-modal", "true");
});

it("renders no browser portal in server HTML, allowing the client mount to hydrate safely", () => {
  expect(renderToString(<DialogFrame title="Server review" onClose={vi.fn()}><button>Send</button></DialogFrame>)).toBe("");
});

it("keeps initial focus, Tab wrapping, Escape and return to the initiating trigger", async () => {
  function Review() { const [open, setOpen] = useState(false); return <><button onClick={() => setOpen(true)}>Review message</button>{open && <DialogFrame title="Review" onClose={() => setOpen(false)}><button>Back to editing</button><button>Send</button></DialogFrame>}</>; }
  render(<Review />);
  const trigger = screen.getByRole("button", { name: "Review message" });
  await userEvent.click(trigger);
  const close = screen.getByRole("button", { name: "Close dialog" }), send = screen.getByRole("button", { name: "Send" });
  expect(close).toHaveFocus();
  send.focus(); await userEvent.tab(); expect(close).toHaveFocus();
  await userEvent.tab({ shift: true }); expect(send).toHaveFocus();
  await userEvent.keyboard("{Escape}"); expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(trigger).toHaveFocus();
});

it("preserves busy denial, composer layout and explicit close after the operation settles", async () => {
  const onClose = vi.fn();
  const content = <button>Send</button>;
  const view = render(<DialogFrame title="Busy review" description="Synthetic trip" eyebrow="WhatsApp" layout="composer" widthClass="max-w-6xl" isBusy onClose={onClose}>{content}</DialogFrame>);
  const dialog = screen.getByRole("dialog", { name: "Busy review" });
  expect(dialog).toHaveClass("max-w-6xl", "max-h-[94dvh]"); expect(dialog).toHaveAttribute("aria-busy", "true");
  await userEvent.keyboard("{Escape}"); fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
  expect(onClose).not.toHaveBeenCalled(); expect(screen.getByRole("button", { name: "Close dialog" })).toBeDisabled();
  view.rerender(<DialogFrame title="Busy review" onClose={onClose}>{content}</DialogFrame>);
  await userEvent.click(screen.getByRole("button", { name: "Close dialog" })); expect(onClose).toHaveBeenCalledOnce();
});

it("isolates background controls and restores nested focus without dismissing the outer review", async () => {
  function Nested() { const [outer, setOuter] = useState(false), [inner, setInner] = useState(false); return <><button onClick={() => setOuter(true)}>Open review</button>{outer && <DialogFrame title="Outer review" onClose={() => setOuter(false)}><button onClick={() => setInner(true)}>Open details</button>{inner && <DialogFrame title="Inner details" onClose={() => setInner(false)}><button>Done</button></DialogFrame>}</DialogFrame>}</>; }
  render(<Nested />); const trigger = screen.getByRole("button", { name: "Open review" }); await userEvent.click(trigger);
  expect(trigger.closest("[inert]")).not.toBeNull(); const details = screen.getByRole("button", { name: "Open details" }); await userEvent.click(details);
  expect(within(screen.getByRole("dialog", { name: "Inner details" })).getByRole("button", { name: "Close dialog" })).toHaveFocus();
  await userEvent.keyboard("{Escape}"); expect(screen.queryByRole("dialog", { name: "Inner details" })).not.toBeInTheDocument(); expect(details).toHaveFocus();
  await userEvent.keyboard("{Escape}"); expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(trigger.closest("[inert]")).toBeNull(); expect(trigger).toHaveFocus();
});
