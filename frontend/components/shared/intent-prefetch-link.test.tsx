import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { AnchorHTMLAttributes } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { IntentPrefetchLink } from "./intent-prefetch-link";

const prefetch = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ prefetch }) }));
vi.mock("next/link", () => ({ default: ({ prefetch: automatic, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { prefetch: boolean }) => <a {...props} data-automatic-prefetch={automatic} /> }));
beforeEach(() => prefetch.mockReset());
afterEach(cleanup);

it("warms the current destination once across pointer, focus and touch intent without automatic prefetch", () => {
  const enter = vi.fn(), focus = vi.fn(), touch = vi.fn();
  render(<IntentPrefetchLink href="/passports" onMouseEnter={enter} onFocus={focus} onTouchStart={touch}>Open passengers</IntentPrefetchLink>);
  const link = screen.getByRole("link", { name: "Open passengers" });
  expect(link).toHaveAttribute("data-automatic-prefetch", "false");
  expect(prefetch).not.toHaveBeenCalled();
  fireEvent.mouseEnter(link);
  fireEvent.focus(link);
  fireEvent.touchStart(link);
  expect(prefetch).toHaveBeenCalledExactlyOnceWith("/passports");
  expect(enter).toHaveBeenCalledOnce();
  expect(focus).toHaveBeenCalledOnce();
  expect(touch).toHaveBeenCalledOnce();
});

it("warms a changed destination when the same list link stays mounted", () => {
  const { rerender } = render(<IntentPrefetchLink href="/passports">Open workspace</IntentPrefetchLink>);
  const link = screen.getByRole("link", { name: "Open workspace" });
  fireEvent.focus(link);
  rerender(<IntentPrefetchLink href="/documents">Open workspace</IntentPrefetchLink>);
  fireEvent.focus(link);
  fireEvent.mouseEnter(link);
  expect(prefetch.mock.calls).toEqual([["/passports"], ["/documents"]]);
});
