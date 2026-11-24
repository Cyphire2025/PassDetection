import { PerspectiveCamera, Vector3 } from "three";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TestHologramEngine } from "./test-hologram-engine";
import { LANDSCAPE_FOV, LANDSCAPE_POSITION, LANDSCAPE_TARGET, WORLD_SCULPTURE_POSITION } from "./test-landscape-layout";

const viewport = { width: 1681, height: 936 };
const portrait = { left: 25, top: 72, width: 1631, height: 650 };

function resizeHarness() {
  const camera = new PerspectiveCamera(LANDSCAPE_FOV, viewport.width / viewport.height, .1, 2000);
  camera.position.set(...LANDSCAPE_POSITION); camera.lookAt(...LANDSCAPE_TARGET); camera.updateMatrixWorld();
  let ratio = 1, width = 1, height = 1;
  const canvasWrites = vi.fn();
  // Mirror Three's public contract: setPixelRatio itself resizes the canvas.
  const renderer = {
    setSize: vi.fn((w: number, h: number) => { width = w; height = h; canvasWrites(Math.floor(w * ratio), Math.floor(h * ratio)); }),
    setPixelRatio: vi.fn((value: number) => { ratio = value; renderer.setSize(width, height); }),
  };
  const composer = { setPixelRatio: vi.fn(), setSize: vi.fn() };
  const stage = { camera, resize: vi.fn((w: number, h: number) => { camera.aspect = w / h; camera.updateProjectionMatrix(); }) };
  // Exercise the production resize method without requiring a GPU/context or assets.
  const engine = Object.assign(Object.create(TestHologramEngine.prototype),
    { renderer, composer, stage, width: 0, height: 0, dpr: 1, quality: 1, lowPower: false }) as TestHologramEngine;
  return { engine, camera, canvasWrites, composer, renderer };
}

afterEach(() => vi.unstubAllGlobals());

describe("hologram drawing-buffer allocation", () => {
  it("reframes every drawer layout change without resetting an unchanged full-screen canvas", () => {
    vi.stubGlobal("devicePixelRatio", 1);
    const { engine, camera, canvasWrites, composer } = resizeHarness();
    engine.resize(viewport.width, viewport.height, portrait);
    canvasWrites.mockClear(); composer.setSize.mockClear(); composer.setPixelRatio.mockClear();
    const initialProjection = camera.projectionMatrix.clone(), position = camera.position.clone();
    for (let step = 1; step <= 20; step++) {
      const frame = { ...portrait, width: portrait.width - step * 25 };
      engine.resize(viewport.width, viewport.height, frame);
      const center = new Vector3(...WORLD_SCULPTURE_POSITION).project(camera);
      expect((center.x + 1) * viewport.width / 2).toBeCloseTo(frame.left + frame.width / 2, 8);
    }
    expect(canvasWrites).not.toHaveBeenCalled();
    expect(composer.setSize).not.toHaveBeenCalled(); expect(composer.setPixelRatio).not.toHaveBeenCalled();
    expect(camera.projectionMatrix.equals(initialProjection)).toBe(false);
    expect(camera.position.equals(position)).toBe(true);
  });

  it("resizes real viewport and effective DPR changes, including adaptive resolution", () => {
    vi.stubGlobal("devicePixelRatio", 1);
    const { engine, camera, canvasWrites, composer } = resizeHarness();
    engine.resize(viewport.width, viewport.height, portrait);
    canvasWrites.mockClear(); composer.setSize.mockClear();
    engine.resize(390, 844, { left: 5, top: 202, width: 380, height: 287 });
    expect(canvasWrites).toHaveBeenLastCalledWith(390, 844);
    expect(composer.setSize).toHaveBeenLastCalledWith(390, 844);
    expect(camera.aspect).toBeCloseTo(390 / 844);
    vi.stubGlobal("devicePixelRatio", 1.25);
    engine.resize(390, 844);
    expect(canvasWrites).toHaveBeenLastCalledWith(487, 1055);
    expect(composer.setPixelRatio).toHaveBeenLastCalledWith(1.25);
    Object.assign(engine, { quality: .8 });
    engine.resize(390, 844);
    expect(canvasWrites).toHaveBeenLastCalledWith(390, 844);
    expect(composer.setPixelRatio).toHaveBeenLastCalledWith(1);
  });
});
