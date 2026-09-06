import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CompanyJourneyFilm } from "./company-journey-film";

const reducedMotion = new EventTarget();
const connection = Object.assign(new EventTarget(), { saveData: false });
const originalConnectionDescriptor = Object.getOwnPropertyDescriptor(navigator, "connection");
let prefersReducedMotion = false;
let hidden = false;
let paused = true;
const observers: TestIntersectionObserver[] = [];

class TestIntersectionObserver implements IntersectionObserver {
  readonly root = null;
  readonly rootMargin = "0px";
  readonly thresholds = [0.15];
  private target: Element | null = null;

  constructor(private readonly callback: IntersectionObserverCallback) {
    observers.push(this);
  }

  observe(target: Element) { this.target = target; }
  unobserve() { this.target = null; }
  disconnect() { this.target = null; }
  takeRecords(): IntersectionObserverEntry[] { return []; }

  deliver(inView: boolean) {
    if (!this.target) return;
    const rect = this.target.getBoundingClientRect();
    this.callback([{
      target: this.target,
      isIntersecting: inView,
      intersectionRatio: inView ? 1 : 0,
      boundingClientRect: rect,
      intersectionRect: rect,
      rootBounds: null,
      time: performance.now(),
    }], this);
  }
}

function setInView(inView: boolean) {
  act(() => { observers.forEach((observer) => observer.deliver(inView)); });
}

function setDocumentHidden(value: boolean) {
  act(() => {
    hidden = value;
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

function renderFilm() {
  const view = render(<CompanyJourneyFilm />);
  const video = view.container.querySelector("video");
  if (!video) throw new Error("The company film must provide a video player.");
  return { ...view, video };
}

beforeEach(() => {
  prefersReducedMotion = false;
  connection.saveData = false;
  hidden = false;
  paused = true;
  observers.length = 0;
  vi.stubGlobal("IntersectionObserver", TestIntersectionObserver);
  vi.stubGlobal("matchMedia", () => ({
    get matches() { return prefersReducedMotion; },
    addEventListener: reducedMotion.addEventListener.bind(reducedMotion),
    removeEventListener: reducedMotion.removeEventListener.bind(reducedMotion),
  }));
  Object.defineProperty(navigator, "connection", { configurable: true, get: () => connection });
  vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
  vi.spyOn(HTMLMediaElement.prototype, "paused", "get").mockImplementation(() => paused);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
    paused = false;
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (this: HTMLMediaElement) {
    if (paused) return;
    paused = true;
    this.dispatchEvent(new Event("pause"));
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (originalConnectionDescriptor) Object.defineProperty(navigator, "connection", originalConnectionDescriptor);
  else Reflect.deleteProperty(navigator, "connection");
});

describe("CompanyJourneyFilm playback preferences", () => {
  it.each(["reduced motion", "data saver"])("keeps a poster without requesting the film under %s", (preference) => {
    prefersReducedMotion = preference === "reduced motion";
    connection.saveData = preference === "data saver";
    const { video } = renderFilm();

    expect(video).not.toHaveAttribute("src");
    expect(video).toHaveAttribute("preload", "none");
    expect(video).toHaveAttribute("poster");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    setInView(true);
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });

  it("automatically plays an in-view film without exposing playback controls", () => {
    const { video } = renderFilm();
    expect(video.getAttribute("src")).toMatch(/\.mp4(?:\?|$)/);
    setInView(true);
    expect(video.paused).toBe(false);
    expect(video).not.toHaveAttribute("controls");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("suspends playback in a hidden document or outside the viewport, then resumes when visible", () => {
    const { video } = renderFilm();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    setInView(true);
    expect(video.paused).toBe(false);

    setDocumentHidden(true);
    expect(video.paused).toBe(true);
    setDocumentHidden(false);
    expect(video.paused).toBe(false);

    setInView(false);
    expect(video.paused).toBe(true);
    setDocumentHidden(true);
    setDocumentHidden(false);
    expect(video.paused).toBe(true);
    setInView(true);
    expect(video.paused).toBe(false);
  });

  it("keeps an interrupted play request resumable after returning to view", async () => {
    vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(new DOMException("Playback interrupted", "AbortError"));
    const { video } = renderFilm();
    setInView(true);
    await act(async () => { await Promise.resolve(); });
    expect(video).toHaveAttribute("src");
    setInView(false);
    setInView(true);
    expect(video.paused).toBe(false);
  });

  it("stops automatic motion when the system preference changes while playing", () => {
    const { video } = renderFilm();
    setInView(true);
    expect(video.paused).toBe(false);

    act(() => {
      prefersReducedMotion = true;
      reducedMotion.dispatchEvent(new Event("change"));
    });

    expect(video).not.toHaveAttribute("src");
    expect(video.paused).toBe(true);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("falls back to the poster when browser autoplay is rejected", async () => {
    vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(new DOMException("Autoplay denied", "NotAllowedError"));
    const { video } = renderFilm();
    setInView(true);

    await waitFor(() => expect(video).not.toHaveAttribute("src"));
    expect(video).toHaveAttribute("poster");
    expect(video.paused).toBe(true);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("restores the poster after a media failure", () => {
    const { video } = renderFilm();
    setInView(true);
    fireEvent.error(video);

    expect(video).toHaveAttribute("poster");
    expect(video).not.toHaveAttribute("src");
    expect(video.paused).toBe(true);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Our expertise" })).toBeVisible();
  });
});
