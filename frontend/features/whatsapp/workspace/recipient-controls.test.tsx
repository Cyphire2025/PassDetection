import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RecipientRowMenu } from "./recipient-controls";

function fixture() {
  const selected = vi.fn();
  render(<main data-testid="recipient-scroll">
    <RecipientRowMenu name="Fixture traveller">{close => <button role="menuitem" onClick={() => { selected(); close(); }}>View details</button>}</RecipientRowMenu>
    <button>Outside</button>
  </main>);
  const trigger = screen.getByRole("button", { name: "Actions for Fixture traveller" });
  let top = 376;
  vi.spyOn(trigger, "getBoundingClientRect").mockImplementation(() => ({ x: 100, y: top, top, bottom: top + 32, left: 100, right: 132, width: 32, height: 32, toJSON() {} }));
  return { trigger, selected, scroll: screen.getByTestId("recipient-scroll"), moveAnchor: () => { top -= 20; } };
}

describe("recipient action menu scroll ordering", () => {
  it("remains actionable when a queued scroll event arrives after opening at its final position", () => {
    const { trigger, selected, scroll } = fixture();
    // Browsers may deliver the notification after the click although the
    // scroll offset and trigger position have already settled.
    scroll.scrollTop = 558;
    fireEvent.click(trigger);
    expect(screen.getByRole("menuitem", { name: "View details" })).toHaveFocus();
    fireEvent.scroll(scroll);
    fireEvent.click(screen.getByRole("menuitem", { name: "View details" }));
    expect(selected).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("dismisses when scrolling actually moves the trigger and keeps normal outside dismissal", () => {
    const { trigger, scroll, moveAnchor } = fixture();
    fireEvent.click(trigger);
    moveAnchor();
    fireEvent.scroll(scroll);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Outside" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    fireEvent.resize(window);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("returns focus to the trigger on Escape after an ignored queued scroll", () => {
    const { trigger, scroll } = fixture();
    fireEvent.click(trigger);
    fireEvent.scroll(scroll);
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(trigger).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
