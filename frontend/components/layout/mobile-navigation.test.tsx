import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "@/components/ui/modal";
import { MobileNavigation } from "./mobile-navigation";

vi.mock("./sidebar", () => ({ Sidebar: ({ onNavigate }: { onNavigate: () => void }) => (
  <a href="#groups" onClick={(event) => { event.preventDefault(); onNavigate(); }}>Groups</a>
) }));

function NavigationHarness() {
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState(false);
  return <>
    <button data-mobile-navigation-trigger onClick={() => setOpen(true)}>Open navigation</button>
    <button onClick={() => setConfirmation(true)}>Open confirmation</button>
    <MobileNavigation open={open} onClose={() => setOpen(false)} />
    <ConfirmDialog isOpen={confirmation} title="Nested confirmation" description="Review the action" confirmLabel="Confirm" onClose={() => setConfirmation(false)} onConfirm={() => setConfirmation(false)} />
  </>;
}

function openNavigation() {
  const trigger = screen.getByRole("button", { name: "Open navigation" });
  trigger.focus();
  fireEvent.click(trigger);
  return trigger;
}

describe("mobile navigation keyboard boundary", () => {
  it("contains external focus, wraps Tab and restores the trigger after route navigation", () => {
    render(<NavigationHarness />);
    const trigger = openNavigation();
    const close = screen.getByRole("button", { name: "Close navigation" });
    expect(close).toHaveFocus();
    expect(trigger).toHaveAttribute("inert");
    trigger.focus();
    expect(close).toHaveFocus();
    const groups = screen.getByRole("link", { name: "Groups" });
    groups.focus();
    fireEvent.keyDown(groups, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.click(groups);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(trigger).not.toHaveAttribute("inert");
  });

  it("lets only the top dialog consume Escape and retains drawer scroll locking", () => {
    render(<NavigationHarness />);
    openNavigation();
    const close = screen.getByRole("button", { name: "Close navigation" });
    fireEvent.click(screen.getByText("Open confirmation"));
    const confirmation = screen.getByRole("dialog", { name: "Nested confirmation" });
    fireEvent.keyDown(confirmation, { key: "Escape" });
    expect(screen.getByRole("dialog", { name: "Dashboard navigation" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.body.style.overflow).not.toBe("hidden");
  });
});
