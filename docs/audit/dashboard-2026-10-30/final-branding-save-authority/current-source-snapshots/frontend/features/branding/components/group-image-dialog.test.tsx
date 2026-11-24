import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GroupImageDialog } from "./group-image-dialog";
import { GroupBanner } from "./group-banner";
import { GroupBannerAction } from "./group-banner-action";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";

const transport = vi.hoisted(() => ({ save: vi.fn(), invalidate: vi.fn(), crop: vi.fn() }));
vi.mock("../api/branding-images.api", () => ({
  saveBrandingImage: transport.save, invalidateBrandingImages: transport.invalidate,
}));
vi.mock("../image-crop", async original => ({
  ...await original<typeof import("../image-crop")>(), cropBrandingImage: transport.crop,
}));

class ResizeObserverFixture {
  targets: Element[] = [];
  disconnect = vi.fn();
  constructor(readonly callback: ResizeObserverCallback) { observers.push(this); }
  observe(target: Element) { this.targets.push(target); }
  unobserve() { /* no individual target release is needed by this fixture */ }
}
const observers: ResizeObserverFixture[] = [];

beforeEach(() => {
  useAuthStore.setState({ user: { id: "branding-test-actor", role: "agency_admin", agency_id: "branding-test-agency" } as User });
  observers.length = 0;
  vi.stubGlobal("ResizeObserver", ResizeObserverFixture);
  const NativeURL = globalThis.URL;
  vi.stubGlobal("URL", class extends NativeURL {
    static createObjectURL = vi.fn(() => "blob:synthetic-banner");
    static revokeObjectURL = vi.fn();
  });
  transport.save.mockReset().mockResolvedValue({ url: "/api/group-banner?v=next" });
  transport.invalidate.mockReset().mockResolvedValue(undefined);
  transport.crop.mockReset().mockResolvedValue(new File(["cropped"], "cropped.jpg", { type: "image/jpeg" }));
});
afterEach(() => { vi.unstubAllGlobals(); useAuthStore.setState({ user: null }); });

function workspace(width: number, height: number, existing = true) {
  const client = new QueryClient();
  const view = render(<QueryClientProvider client={client}>
    <GroupBanner src={existing ? "/api/group-banner?v=original" : null}>
      <div data-testid="banner-content">Group heading and readiness</div>
      <GroupBannerAction group={{ group_id: "group-1", banner_url: existing ? "/api/group-banner?v=original" : null }} disabled={false} />
    </GroupBanner>
  </QueryClientProvider>);
  const frame = screen.getByTestId("banner-content").parentElement!;
  Object.assign(frame.style, { borderStyle: "solid", borderWidth: "0px" });
  let bounds = { width, height };
  vi.spyOn(frame, "getBoundingClientRect").mockImplementation(() => ({
    ...bounds, height: frame.classList.contains("group-banner") ? bounds.height : bounds.height - 32,
  }) as DOMRect);
  return { frame, view, resize: (next: typeof bounds) => { bounds = next; } };
}

const preview = () => screen.getByRole("img", { name: /Image crop preview/ });

describe("group image crop frame", () => {
  it.each([[390, 844], [1192, 1000]])("matches the background viewport at %i by %i", (width, height) => {
    render(<div data-testid="workspace-pane"><header /><main><div className="group-workspace" /></main></div>);
    const pane = screen.getByTestId("workspace-pane");
    pane.getBoundingClientRect = vi.fn(() => ({ width, height }) as DOMRect);
    const client = new QueryClient();
    render(<QueryClientProvider client={client}>
      <GroupImageDialog kind="background" groupId="group-1" currentUrl="/api/group-background" onClose={vi.fn()} />
    </QueryClientProvider>);
    expect(screen.getByRole("img", { name: /Image crop preview/ }).style.aspectRatio).toBe(`${width / height} / 1`);
  });

  it("retains the wide banner frame independently of the workspace viewport", () => {
    const client = new QueryClient();
    render(<QueryClientProvider client={client}>
      <GroupImageDialog kind="banner" groupId="group-1" currentUrl="/api/group-banner" onClose={vi.fn()} />
    </QueryClientProvider>);
    expect(screen.getByRole("img", { name: /Image crop preview/ }).style.aspectRatio).toBe("4 / 1");
  });

  it.each([[1108, 302], [358, 500]])("matches the existing banner's committed %i by %i frame", (width, height) => {
    workspace(width, height);
    fireEvent.click(screen.getByRole("button", { name: "Edit banner" }));
    expect(preview().style.aspectRatio).toBe(`${width / height} / 1`);
  });

  it.each([[1108, 302], [358, 500]])("previews the future %i by %i frame when adding the first banner and restores layout on cancel", (width, height) => {
    const { frame } = workspace(width, height, false);
    expect(frame).not.toHaveClass("group-banner");
    fireEvent.click(screen.getByRole("button", { name: "Add banner" }));
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: { files: [new File(["image"], "banner.png", { type: "image/png" })] },
    });
    expect(preview().style.aspectRatio).toBe(`${width / height} / 1`);
    expect(frame).toHaveClass("group-banner");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(frame).not.toHaveClass("group-banner");
    expect(transport.save).not.toHaveBeenCalled();
  });

  it("observes the actual banner frame across resizing and releases its observer on close", () => {
    const { frame, resize } = workspace(1108, 302);
    fireEvent.click(screen.getByRole("button", { name: "Edit banner" }));
    const observer = observers.find(entry => entry.targets.includes(frame));
    expect(observer).toBeDefined();
    resize({ width: 358, height: 500 });
    act(() => observer!.callback([], observer as unknown as ResizeObserver));
    expect(preview().style.aspectRatio).toBe(`${358 / 500} / 1`);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(observer!.disconnect).toHaveBeenCalledTimes(1);
  });

  it("uses the measured target aspect for the saved crop and keeps the original image version", async () => {
    workspace(358, 500);
    fireEvent.click(screen.getByRole("button", { name: "Edit banner" }));
    fireEvent.change(screen.getByRole("slider", { name: "Horizontal position" }), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save banner" }));
    await waitFor(() => expect(transport.save).toHaveBeenCalled());
    expect(transport.crop).toHaveBeenCalledWith("/api/group-banner?v=original", 358 / 500, { x: 30, y: 50, zoom: 1 });
    expect(transport.save).toHaveBeenCalledWith("group-banner", "group-1", undefined, expect.any(File), "/api/group-banner?v=original", "branding-test-actor", {
      expectedAuthorityKey: JSON.stringify(["branding-test-actor", "agency_admin", "branding-test-agency"]), signal: expect.any(AbortSignal),
    });
  });

  it("matches the image padding box rather than the frame's fractional borders", async () => {
    const { frame } = workspace(358, 500);
    Object.assign(frame.style, { borderStyle: "solid", borderLeftWidth: "0.25px", borderRightWidth: "2.5px", borderTopWidth: "1.5px", borderBottomWidth: "0.5px" });
    fireEvent.click(screen.getByRole("button", { name: "Edit banner" }));
    const aspect = (358 - .25 - 2.5) / (500 - 1.5 - .5);
    expect(preview().style.aspectRatio).toBe(`${aspect} / 1`);
    fireEvent.change(screen.getByRole("slider", { name: "Horizontal position" }), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save banner" }));
    await waitFor(() => expect(transport.crop).toHaveBeenCalledWith("/api/group-banner?v=original", aspect, expect.objectContaining({ x: 30 })));
  });

  it("keeps the banner measurement local to its own frame", () => {
    render(<GroupBanner src="/api/another-banner"><div data-testid="decoy">Another group</div></GroupBanner>);
    screen.getByTestId("decoy").parentElement!.getBoundingClientRect = vi.fn(() => ({ width: 100, height: 10 }) as DOMRect);
    workspace(358, 500);
    fireEvent.click(screen.getByRole("button", { name: "Edit banner" }));
    expect(preview().style.aspectRatio).toBe(`${358 / 500} / 1`);
  });

  it("observes background pane changes and releases that exact observer", () => {
    render(<div data-testid="workspace-pane"><main><div className="group-workspace" /></main></div>);
    const pane = screen.getByTestId("workspace-pane");
    let bounds = { width: 1192, height: 1000 };
    pane.getBoundingClientRect = vi.fn(() => bounds as DOMRect);
    const client = new QueryClient();
    const view = render(<QueryClientProvider client={client}>
      <GroupImageDialog kind="background" groupId="group-1" currentUrl="/api/group-background" onClose={vi.fn()} />
    </QueryClientProvider>);
    const observer = observers.find(entry => entry.targets.includes(pane));
    expect(observer).toBeDefined();
    bounds = { width: 390, height: 844 };
    act(() => observer!.callback([], observer as unknown as ResizeObserver));
    expect(preview().style.aspectRatio).toBe(`${390 / 844} / 1`);
    view.unmount();
    expect(observer!.disconnect).toHaveBeenCalledTimes(1);
  });
});
