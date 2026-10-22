import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SculpturePresentation } from "@/components/ui/liquid-sculpture/types";
import { neutralSpeechFrame, type SpeechFrame } from "../speech-frame";
import type { HeadView } from "./test-hologram-engine";
import { TestHologram } from "./test-hologram";

const observed = vi.hoisted(() => ({
  callbacks: new Set<() => void>(),
  frames: [] as Array<{ view: HeadView; speech: SpeechFrame; opacity: number; level: number }>,
  suspend: vi.fn(), destroy: vi.fn(),
}));
vi.mock("gsap", () => ({ gsap: { ticker: {
  add: (callback: () => void) => observed.callbacks.add(callback),
  remove: (callback: () => void) => observed.callbacks.delete(callback),
} } }));
vi.mock("next/image", () => ({ default: () => null }));
vi.mock("./human-head-geometry", () => ({ loadHumanHead: async () => ({}) }));
vi.mock("./test-hologram-engine", () => ({ TestHologramEngine: class {
  async prepare() {}
  resize() {}
  suspend = observed.suspend;
  destroy = observed.destroy;
  resetRotation() { return .55; }
  draw(_time: number, view: HeadView, speech: SpeechFrame, _dark: boolean, _motion: boolean, opacity: number, level: number) {
    observed.frames.push({ view: { ...view }, speech: { ...speech }, opacity, level });
  }
} }));

let now = 0, hidden = false;
beforeEach(() => {
  now = 0; hidden = false; observed.callbacks.clear(); observed.frames.length = 0;
  observed.suspend.mockClear(); observed.destroy.mockClear();
  vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
  vi.stubGlobal("matchMedia", () => Object.assign(new EventTarget(), { matches: false }));
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const tick = (at: number) => act(() => { now = at; [...observed.callbacks].forEach((callback) => callback()); });
async function mount() {
  const levelRef = { current: 0 }, speechFrameRef = { current: neutralSpeechFrame() };
  const presentationRef = { current: { phase: "idle", reply: false, reveal: 0, revealWidth: 0, revealHeight: 0 } as SculpturePresentation };
  const result = render(<TestHologram appearance="female" dark motion levelRef={levelRef}
    presentationRef={presentationRef} speechFrameRef={speechFrameRef} />);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByTestId("particle-face-test")).toHaveAttribute("data-renderer", "webgl");
  return { ...result, levelRef, speechFrameRef };
}

describe("hologram transition integration", () => {
  it("uses actual slow frame time and excludes time spent in a hidden tab", async () => {
    const view = await mount();
    tick(0); tick(600);
    expect(observed.frames.at(-1)!.opacity).toBeCloseTo(.875);
    act(() => { hidden = true; document.dispatchEvent(new Event("visibilitychange")); });
    expect(observed.callbacks.size).toBe(0);
    now = 60600;
    act(() => { hidden = false; document.dispatchEvent(new Event("visibilitychange")); });
    tick(60600);
    expect(observed.frames.at(-1)!.opacity).toBeCloseTo(.875);
    tick(61200); expect(observed.frames.at(-1)!.opacity).toBe(1);
    view.unmount(); expect(observed.callbacks.size).toBe(0);
    expect(observed.destroy).toHaveBeenCalledOnce();
  });

  it("holds Home until the rendered pose converges and forwards live speech unchanged", async () => {
    const { levelRef, speechFrameRef } = await mount();
    tick(0); tick(1200);
    const canvas = screen.getByRole("img", { name: "Female interactive 3D particle face" });
    fireEvent.keyDown(canvas, { key: "ArrowRight" }); tick(1800);
    expect(observed.frames.at(-1)!.view.yaw).toBeGreaterThan(-.3);
    fireEvent.keyDown(canvas, { key: "Home" });
    for (const at of [2400, 3000, 3600, 4200, 4800, 5400]) tick(at);
    const homeFrames = observed.frames.filter((frame) => Math.abs(frame.view.yaw + .38) < .001);
    expect(homeFrames.length).toBeGreaterThan(1);
    expect(homeFrames.some((frame) => frame.view.manipulating)).toBe(true);
    expect(observed.frames.at(-1)!.view.manipulating).toBe(false);
    levelRef.current = .4; speechFrameRef.current = { ...neutralSpeechFrame(), active: true, energy: .6, jaw: .7 };
    tick(6000);
    expect(observed.frames.at(-1)!.speech).toEqual(speechFrameRef.current);
    expect(observed.frames.at(-1)!.level).toBe(.4);
  });
});
