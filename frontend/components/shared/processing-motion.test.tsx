import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProcessingMotion } from "./processing-motion";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("processing motion resource lifecycle", () => {
  it("pauses outside the viewport and in hidden tabs, and releases its observer on unmount", () => {
    let visibility: IntersectionObserverCallback | undefined;
    const observe = vi.fn();
    const disconnect = vi.fn();
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: IntersectionObserverCallback) { visibility = callback; }
      observe = observe;
      disconnect = disconnect;
    });
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const { container, unmount } = render(<ProcessingMotion variant="passport" />);
    const scene = container.firstElementChild!;
    expect(observe).toHaveBeenCalledWith(scene);
    expect(scene).toHaveAttribute("data-playing", "true");
    const intersect = (isIntersecting: boolean) => act(() => visibility?.(
      [{ isIntersecting } as IntersectionObserverEntry], {} as IntersectionObserver,
    ));
    intersect(false);
    expect(scene).toHaveAttribute("data-playing", "false");
    hidden.mockReturnValue(true);
    intersect(true);
    expect(scene).toHaveAttribute("data-playing", "false");
    hidden.mockReturnValue(false);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(scene).toHaveAttribute("data-playing", "true");
    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  });

  it("remains decorative and usable without IntersectionObserver", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const { container, queryByRole } = render(<ProcessingMotion variant="analysis" compact />);
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
    expect(container.firstElementChild).toHaveAttribute("data-playing", "true");
    expect(queryByRole("status")).toBeNull();
    expect(queryByRole("progressbar")).toBeNull();
  });
});
