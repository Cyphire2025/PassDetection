import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Page } from "@playwright/test";
import { CylinderGeometry, Matrix4, Vector3 } from "three";
import { decodeHumanHead } from "../../features/ai/components/human-head-geometry";
import { prepareTestHead } from "../../features/ai/components/test-hologram-adult-head";
import { containmentCylinderGeometry, pedestalDiscGeometry } from "../../features/ai/components/test-hologram-platform";
import { testHologramSignal } from "./test-hologram-probe";
import { PROJECTOR } from "../../features/ai/components/test-hologram-projector";

export type ProjectedBounds = { left: number; right: number; top: number; bottom: number };
export const boundsWidth = (box: ProjectedBounds) => box.right - box.left;
export const boundsHeight = (box: ProjectedBounds) => box.bottom - box.top;

function projection(uniforms: Record<string, number[]>, width: number, height: number) {
  expect(uniforms.modelViewMatrix).toHaveLength(16); expect(uniforms.projectionMatrix).toHaveLength(16);
  const matrix = new Matrix4().fromArray(uniforms.projectionMatrix).multiply(new Matrix4().fromArray(uniforms.modelViewMatrix));
  return (x: number, y: number, z: number) => {
    const point = new Vector3(x, y, z).applyMatrix4(matrix);
    return { x: (point.x + 1) * width / 2, y: (1 - point.y) * height / 2 };
  };
}

function projectBounds(positions: ArrayLike<number>, project: ReturnType<typeof projection>) {
  const box: ProjectedBounds = { left: Infinity, right: -Infinity, top: Infinity, bottom: -Infinity };
  for (let index = 0; index < positions.length; index += 3) {
    const point = project(positions[index], positions[index + 1], positions[index + 2]);
    box.left = Math.min(box.left, point.x); box.right = Math.max(box.right, point.x);
    box.top = Math.min(box.top, point.y); box.bottom = Math.max(box.bottom, point.y);
  }
  return box;
}

export function restingHeadProjection(uniforms: Record<string, number[]>, width: number, height: number, appearance: "male" | "female" = "female") {
  const source = Uint8Array.from(readFileSync(resolve("public/ai/human-head/head-v1.bin"))).buffer;
  const head = prepareTestHead(decodeHumanHead(source, appearance), appearance), project = projection(uniforms, width, height);
  return { box: projectBounds(head.positions, project), project };
}

/** Project real submitted transforms, including mobile fitting and shared world camera. */
export async function hologramComposition(page: Page) {
  const state = await testHologramSignal(page);
  const ui = await page.evaluate(() => {
    const box = (element: Element | null) => {
      if (!element) throw new Error("Required workspace control is missing");
      const rect = element.getBoundingClientRect();
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
    };
    const root = document.querySelector('[data-testid="particle-face-test"]')!;
    return { width: innerWidth, height: innerHeight, appearance: root.getAttribute("data-appearance") as "male" | "female",
      header: box(document.querySelector("header")), portrait: box(root),
      microphone: box(document.querySelector('button[aria-label="Start microphone"], button[aria-label="End voice conversation"]')),
      composer: box(document.querySelector('textarea[aria-label="Message Global Connects"]')) };
  });
  const head = restingHeadProjection(state.headUniforms, ui.width, ui.height, ui.appearance).box;
  // Compare the exposed stone profile with controls. The lower tier's extra
  // flange is intentionally buried in the terrain and cannot overlap the UI;
  // applying that hidden extension to both submitted tiers overstates the base.
  const pedestal = pedestalDiscGeometry(), cylinder = containmentCylinderGeometry();
  const rays = new CylinderGeometry(PROJECTOR.upperRadius, PROJECTOR.lowerRadius, PROJECTOR.top - PROJECTOR.bottom, 64, 1, true);
  try {
    expect(state.parts.pedestal?.length).toBeGreaterThan(0);
    expect(state.parts.cage?.length).toBeGreaterThan(0);
    expect(state.parts.projector?.length).toBeGreaterThan(0);
    expect(state.parts.projectorRays?.length).toBeGreaterThan(0);
    const discs = state.parts.pedestal.map((part) => projectBounds(pedestal.attributes.position.array, projection(part.uniforms, ui.width, ui.height)));
    const disk = discs.reduce((result, box) => ({ left: Math.min(result.left, box.left), right: Math.max(result.right, box.right),
      top: Math.min(result.top, box.top), bottom: Math.max(result.bottom, box.bottom) }));
    const cage = projectBounds(cylinder.attributes.position.array, projection(state.parts.cage[0].uniforms, ui.width, ui.height));
    const projector = projection(state.parts.projector[0].uniforms, ui.width, ui.height)(0, 0, 0);
    const barrier = state.parts.cage[0].uniforms;
    const rayToCage = new Matrix4().fromArray(barrier.modelViewMatrix).invert()
      .multiply(new Matrix4().fromArray(state.parts.projectorRays[0].uniforms.modelViewMatrix));
    const point = new Vector3(), rayRange = { bottom: Infinity, top: -Infinity };
    for (let index = 0; index < rays.attributes.position.count; index++) {
      point.fromBufferAttribute(rays.attributes.position, index).applyMatrix4(rayToCage);
      rayRange.bottom = Math.min(rayRange.bottom, point.y); rayRange.top = Math.max(rayRange.top, point.y);
    }
    return { ui, head, disk, cage, projector, ripple: { strength: barrier.strength[0], time: barrier.time[0], heightBounds: barrier.heightBounds },
      projectorOpacity: state.parts.projector[0].uniforms.opacity[0], rayRange };
  } finally { pedestal.dispose(); cylinder.dispose(); rays.dispose(); }
}

export function expectCompositionFits(composition: Awaited<ReturnType<typeof hologramComposition>>) {
  const { head, disk, cage, projector, ui } = composition;
  expect(composition.rayRange.top, "projector rays stop in the lower neck zone").toBeLessThan(-.85);
  expect(composition.rayRange.bottom).toBeGreaterThan(-1.11);
  expect(composition.rayRange.top - composition.rayRange.bottom, "projector fan stays short").toBeLessThan(.25);
  for (const [name, box] of Object.entries({ head, disk, cage })) {
    expect(box.left, `${name} stays inside the left viewport gutter`).toBeGreaterThanOrEqual(4);
    expect(box.right, `${name} stays inside the right viewport gutter`).toBeLessThanOrEqual(ui.width - 4);
    // The faint cage may extend into the empty center of the header band. The
    // solid face remains below the controls, matching the approved composition.
    expect(box.top, `${name} stays inside the viewport`).toBeGreaterThanOrEqual(4);
    expect(box.bottom, `${name} stays above the microphone`).toBeLessThanOrEqual(ui.microphone.top - 4);
  }
  expect(head.top, "the face stays below the header controls").toBeGreaterThanOrEqual(ui.header.bottom + 8);
  expect(ui.microphone.bottom).toBeLessThan(ui.composer.top);
  expect(projector.x).toBeGreaterThan(disk.left + boundsWidth(disk) * .4);
  expect(projector.x).toBeLessThan(disk.left + boundsWidth(disk) * .6);
  expect(projector.y).toBeGreaterThanOrEqual(disk.top - 2);
  expect(projector.y).toBeLessThan(disk.bottom);
  // These are the available ripple amplitude and physical enclosure bounds;
  // only the moving shader envelope is visible, not a permanent full cage.
  expect(composition.ripple.strength).toBeGreaterThan(.01);
  expect(composition.ripple.strength).toBeLessThan(.3);
  expect(Number.isFinite(composition.ripple.time)).toBe(true);
  expect(composition.ripple.heightBounds).toHaveLength(2);
  expect(composition.ripple.heightBounds[1]).toBeGreaterThan(composition.ripple.heightBounds[0]);
  expect(composition.projectorOpacity).toBeGreaterThan(.01);
}
