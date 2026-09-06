import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WhatsAppBroadcastMotion } from "./whatsapp-broadcast-motion";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("broadcast artwork lifecycle", () => {
  it("keeps the same decorative scene through submitting, dispatch, reconnect and terminal outcomes", () => {
    const { container, rerender } = render(<WhatsAppBroadcastMotion messageType="welcome" state="submitting" startedAt={1_000} />);
    const scene = container.querySelector('[data-whatsapp-broadcast-motion="true"]')!;
    expect(scene).toHaveAttribute("aria-hidden", "true");
    expect(scene).toHaveAttribute("data-message-type", "welcome");
    for (const state of ["sending", "reconnecting", "sending", "attention", "complete"] as const) {
      rerender(<WhatsAppBroadcastMotion messageType="welcome" state={state} startedAt={1_000} />);
      expect(container.querySelector('[data-whatsapp-broadcast-motion="true"]')).toBe(scene);
      expect(scene).toHaveAttribute("data-state", state);
      expect(scene).toHaveAttribute("data-playing", String(state === "sending"));
    }
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(container).not.toHaveTextContent(/delivered|read|sent/i);
  });

  it("pauses offscreen and in hidden tabs without losing the active broadcast", () => {
    let observeVisibility!: (entries: Partial<IntersectionObserverEntry>[]) => void;
    const disconnect = vi.fn();
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: typeof observeVisibility) { observeVisibility = callback; }
      observe = vi.fn();
      disconnect = disconnect;
    });
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const { container, unmount } = render(<WhatsAppBroadcastMotion state="sending" />);
    const scene = container.querySelector('[data-whatsapp-broadcast-motion="true"]')!;
    act(() => observeVisibility([{ isIntersecting: false }]));
    expect(scene).toHaveAttribute("data-playing", "false");
    act(() => observeVisibility([{ isIntersecting: true }]));
    expect(scene).toHaveAttribute("data-playing", "true");
    hidden.mockReturnValue(true);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(scene).toHaveAttribute("data-playing", "false");
    hidden.mockReturnValue(false);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(scene).toHaveAttribute("data-playing", "true");
    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  });

  it("rejoins the original cadence after remount instead of restarting at zero", () => {
    const now = vi.spyOn(Date, "now").mockReturnValue(4_000);
    const first = render(<WhatsAppBroadcastMotion startedAt={1_000} />);
    const firstScene = first.container.querySelector<HTMLDivElement>('[data-whatsapp-broadcast-motion="true"]')!;
    expect(firstScene.style.getPropertyValue("--broadcast-phase")).toBe("-3s");
    first.unmount();
    now.mockReturnValue(5_000);
    const next = render(<WhatsAppBroadcastMotion startedAt={1_000} compact />);
    const nextScene = next.container.querySelector<HTMLDivElement>('[data-whatsapp-broadcast-motion="true"]')!;
    expect(nextScene.style.getPropertyValue("--broadcast-phase")).toBe("-4s");
    now.mockReturnValue(6_000);
    next.rerender(<WhatsAppBroadcastMotion startedAt={1_000} compact state="sending" />);
    expect(nextScene.style.getPropertyValue("--broadcast-phase")).toBe("-4s");
  });
});
