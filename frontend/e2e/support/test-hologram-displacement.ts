import { expect, type Page } from "@playwright/test";
import { CONTAINMENT } from "../../features/ai/components/test-hologram-platform";
import { PLATFORM_HORIZONTAL_SCALE } from "../../features/ai/components/test-landscape-layout";

type ParticleCoherence = { samples: number; nearPairs: number; farPairs: number; neighborCorrelation: number; nearDifferenceRms: number; farDifferenceRms: number };
export type TrackedParticle = { id: number; position: number[]; canonical: number[]; distance: number; screen: number[] };
/** `displacement` is the production uniform's historical name. Its XYZ now
 * stores absolute enclosure positions, never an offset from a particle's seed. */
export type ParticleDisplacement = {
  samples: number; changed: number; deltaRms: number; signature: number;
  enclosure: { radiusMaximum: number; minimumY: number; maximumY: number };
  regions: Record<"forehead" | "cheeks" | "nose", { samples: number; changed: number; deltaRms: number }>;
  coherence: ParticleCoherence;
  interior: { samples: number; deepSamples: number; maximumDepth: number; changed: number; deltaRms: number; coherence: ParticleCoherence };
  shape: { inside: number; nearSurface: number; extracted: number; outsideDomain: number; minimum: number; maximum: number; median: number; p95: number; bins: number[] };
  sdf: { dimensions: number[]; minimum: number[]; size: number[]; voxel: number; storage: number };
  stateStorage: number; time: number; at: number; elapsed: number; wakeMaximum: number;
  identities: TrackedParticle[];
};
type DisplacementWindow = Window & { __sampleParticleDisplacement: () => Promise<ParticleDisplacement> };

/** Observe actual state and field textures at the head's draw. This neither
 * replaces shaders/clocks nor infers volume depth from immutable seed labels. */
export async function observeParticleDisplacement(page: Page) {
  await page.addInitScript(() => {
    type Volume = { data: Float32Array; dimensions: number[]; storage: number };
    const active = new WeakMap<WebGL2RenderingContext, WebGLProgram | null>();
    const sizes = new WeakMap<WebGLTexture, { width: number; height: number; storage: number }>();
    const volumes = new WeakMap<WebGLTexture, Volume>();
    let previous: { field: Float32Array; time: number; volume: WebGLTexture } | undefined;
    let pending: { resolve: (value: ParticleDisplacement) => void; reject: (reason: Error) => void; timer: number } | undefined;
    Object.defineProperty(window, "__sampleParticleDisplacement", { value: () => new Promise<ParticleDisplacement>((resolve, reject) => {
      if (pending) { reject(new Error("A particle-state readback is already pending")); return; }
      const timer = window.setTimeout(() => { pending = undefined; reject(new Error("No volumetric head draw was rendered")); }, 10000);
      pending = { resolve, reject, timer };
    }) });
    const half = (value: number) => {
      const sign = value & 0x8000 ? -1 : 1, exponent = value >> 10 & 31, mantissa = value & 1023;
      return exponent === 31 ? Number.NaN : sign * (exponent ? 1 + mantissa / 1024 : mantissa / 1024) * 2 ** (exponent ? exponent - 15 : -14);
    };
    const transform = (m: ArrayLike<number>, p: ArrayLike<number>) => [0, 1, 2, 3].map((row) => m[row] * p[0] + m[4 + row] * p[1] + m[8 + row] * p[2] + m[12 + row]);
    const sample = (gl: WebGL2RenderingContext, mode: number, count: number) => {
      const program = active.get(gl);
      if (!pending || mode !== gl.POINTS || !program || gl.getUniformLocation(program, "articulation") === null) return;
      const request = pending; pending = undefined; clearTimeout(request.timer);
      const previousRead = gl.getParameter(gl.READ_FRAMEBUFFER_BINDING) as WebGLFramebuffer | null;
      const previousUnit = gl.getParameter(gl.ACTIVE_TEXTURE) as number;
      let framebuffer: WebGLFramebuffer | null = null;
      try {
        const uniform = (name: string) => {
          const location = gl.getUniformLocation(program, name);
          if (!location) throw new Error(`Missing actual volumetric head uniform ${name}`);
          return gl.getUniform(program, location);
        };
        const texture = (name: string, binding: number) => {
          gl.activeTexture(gl.TEXTURE0 + Number(uniform(name)));
          const result = gl.getParameter(binding) as WebGLTexture | null;
          if (!result) throw new Error(`No actual texture bound for ${name}`);
          return result;
        };
        const stateTexture = texture("displacement", gl.TEXTURE_BINDING_2D), size = sizes.get(stateTexture);
        const volumeTexture = texture("sdfVolume", gl.TEXTURE_BINDING_3D), volume = volumes.get(volumeTexture);
        gl.activeTexture(previousUnit);
        if (!size || size.width * size.height !== count) throw new Error(`Unexpected actual particle-state dimensions ${JSON.stringify(size)} for ${count} points`);
        if (size.storage !== gl.RGBA32F) throw new Error(`Absolute particle positions require actual RGBA32F storage, observed ${size.storage}`);
        if (!volume) throw new Error("No observed 3D signed-distance field upload");
        const minimum = Array.from(uniform("sdfMin") as Float32Array), extent = Array.from(uniform("sdfSize") as Float32Array);
        const inverse = uniform("enclosureToHead") as Float32Array;
        const projection = uniform("projectionMatrix") as Float32Array, modelView = uniform("modelViewMatrix") as Float32Array;
        const time = Number(uniform("time"));
        if (minimum.length !== 3 || extent.some((value) => !Number.isFinite(value) || value <= 0) || inverse.length !== 16) throw new Error("Invalid actual volume bounds/transform");
        const voxel = Math.max(...extent.map((value, axis) => value / volume.dimensions[axis]));
        // Match hardware linear filtering, including half-texel centers and
        // CLAMP_TO_EDGE. Only the uploaded signed-distance channel is consulted.
        const distanceAt = (point: number[]) => {
          const grid = point.map((value, axis) => Math.max(0, Math.min(volume.dimensions[axis] - 1,
            (value - minimum[axis]) / extent[axis] * volume.dimensions[axis] - .5)));
          const lo = grid.map(Math.floor), hi = lo.map((value, axis) => Math.min(value + 1, volume.dimensions[axis] - 1));
          let distance = 0;
          for (let corner = 0; corner < 8; corner++) {
            let weight = 1; const coordinate = [0, 0, 0];
            for (let axis = 0; axis < 3; axis++) {
              const upper = corner >> axis & 1;
              coordinate[axis] = upper ? hi[axis] : lo[axis];
              weight *= upper ? grid[axis] - lo[axis] : 1 - (grid[axis] - lo[axis]);
            }
            distance += weight * volume.data[((coordinate[2] * volume.dimensions[1] + coordinate[1]) * volume.dimensions[0] + coordinate[0]) * 4 + 3];
          }
          const outside = point.map((value, axis) => value - Math.max(minimum[axis], Math.min(minimum[axis] + extent[axis], value)));
          const beyond = Math.hypot(...outside);
          return beyond > .00001 ? Math.max(0, distance) + beyond : distance;
        };
        framebuffer = gl.createFramebuffer();
        if (!framebuffer) throw new Error("Unable to allocate readback framebuffer");
        gl.bindFramebuffer(gl.READ_FRAMEBUFFER, framebuffer);
        gl.framebufferTexture2D(gl.READ_FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, stateTexture, 0);
        if (gl.checkFramebufferStatus(gl.READ_FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) throw new Error("Actual particle-state texture is not readable");
        const rgba = new Float32Array(count * 4);
        gl.readPixels(0, 0, size.width, size.height, gl.RGBA, gl.FLOAT, rgba);
        const error = gl.getError(); if (error !== gl.NO_ERROR) throw new Error(`Particle-state readback failed: WebGL ${error}`);
        const field = new Float32Array(count * 3), canonical = new Float32Array(count * 3), distances = new Float32Array(count);
        const previousField = previous?.volume === volumeTexture && previous.field.length === field.length ? previous.field : undefined;
        const elapsed = previousField && previous ? time - previous.time : 0;
        const enclosure = { radiusMaximum: 0, minimumY: Infinity, maximumY: -Infinity };
        const empty = () => ({ samples: 0, changed: 0, deltaRms: 0 });
        const regions = { forehead: empty(), cheeks: empty(), nose: empty() };
        const emptyCoherence = () => ({ samples: 0, nearPairs: 0, farPairs: 0, neighborCorrelation: 0, nearDifferenceRms: 0, farDifferenceRms: 0 });
        const interior = { ...empty(), deepSamples: 0, maximumDepth: 0, coherence: emptyCoherence() };
        const shape = { inside: 0, nearSurface: 0, extracted: 0, outsideDomain: 0, minimum: Infinity, maximum: -Infinity, median: 0, p95: 0, bins: Array<number>(12 ** 3).fill(0) };
        let changed = 0, squaredChange = 0, signature = 2166136261, wakeMaximum = 0;
        for (let id = 0; id < count; id++) {
          const offset = id * 3, position = Array.from(rgba.subarray(id * 4, id * 4 + 3));
          if (!position.every(Number.isFinite) || !Number.isFinite(rgba[id * 4 + 3])) throw new Error("Non-finite GPU particle state");
          field.set(position, offset);
          const point = transform(inverse, position).slice(0, 3); canonical.set(point, offset);
          const distance = distanceAt(point); distances[id] = distance;
          if (!Number.isFinite(distance)) throw new Error("Non-finite actual SDF sample");
          let change = 0;
          for (let axis = 0; axis < 3; axis++) {
            if (previousField) change += (position[axis] - previousField[offset + axis]) ** 2;
            signature = Math.imul(signature ^ Math.round(position[axis] * 1e6), 16777619);
          }
          if (change > 1e-12) changed++;
          squaredChange += change; wakeMaximum = Math.max(wakeMaximum, rgba[id * 4 + 3]);
          enclosure.radiusMaximum = Math.max(enclosure.radiusMaximum, Math.hypot(position[0], position[2]));
          enclosure.minimumY = Math.min(enclosure.minimumY, position[1]); enclosure.maximumY = Math.max(enclosure.maximumY, position[1]);
          shape.minimum = Math.min(shape.minimum, distance); shape.maximum = Math.max(shape.maximum, distance);
          if (distance <= 0) shape.inside++;
          if (Math.abs(distance) <= voxel * 1.5) shape.nearSurface++;
          if (distance > voxel * 2) shape.extracted++;
          const outside = point.some((value, axis) => value < minimum[axis] || value > minimum[axis] + extent[axis]);
          if (outside) shape.outsideDomain++;
          else {
            const bin = point.map((value, axis) => Math.min(11, Math.floor((value - minimum[axis]) / extent[axis] * 12)));
            shape.bins[(bin[2] * 12 + bin[1]) * 12 + bin[0]]++;
          }
          // Current Eulerian depth, independent of which seed was originally
          // labelled interior. Two voxels exclude coarse boundary uncertainty.
          if (distance < -voxel) {
            interior.samples++; interior.maximumDepth = Math.max(interior.maximumDepth, -distance);
            if (distance < -voxel * 2) interior.deepSamples++;
            if (change > 1e-12) interior.changed++;
            interior.deltaRms += change;
          }
          const [x, y, z] = point;
          const region = Math.abs(x) < .34 && y > .35 && y < .66 && z > .2 ? regions.forehead
            : Math.abs(x) > .2 && Math.abs(x) < .42 && y > -.25 && y < .08 && z > .25 ? regions.cheeks
              : Math.abs(x) < .11 && y > -.12 && y < .18 && z > .48 ? regions.nose : null;
          if (region && distance <= voxel * 1.5) { region.samples++; region.deltaRms += change; if (change > 1e-12) region.changed++; }
        }
        const sorted = Float32Array.from(distances).sort(); shape.median = sorted[Math.floor(count / 2)]; shape.p95 = sorted[Math.floor(count * .95)];
        for (const region of [...Object.values(regions), interior]) region.deltaRms = Math.sqrt(region.deltaRms / Math.max(1, region.samples));
        const surfacePoints: number[] = [], deepPoints: number[] = [];
        const stride = Math.max(1, Math.floor(count / 4096));
        for (let id = 0; id < count; id += stride) {
          const x = canonical[id * 3], y = canonical[id * 3 + 1], z = canonical[id * 3 + 2];
          if (Math.abs(x) > .44 || y < -.35 || y > .66) continue;
          if (z > .2 && Math.abs(distances[id]) < voxel * 1.5 && surfacePoints.length < 512) surfacePoints.push(id);
          if (distances[id] < -voxel * 2 && deepPoints.length < 512) deepPoints.push(id);
        }
        const correlate = (points: number[]): ParticleCoherence => {
          let nearPairs = 0, farPairs = 0, nearSquared = 0, farSquared = 0, dot = 0, lengthA = 0, lengthB = 0;
          if (previousField) for (const id of points) {
            let nearest = -1, near = .12 ** 2, farthest = -1, far = .5 ** 2;
            for (const candidate of points) {
              if (candidate === id) continue;
              let distance = 0;
              for (let axis = 0; axis < 3; axis++) distance += (previousField[id * 3 + axis] - previousField[candidate * 3 + axis]) ** 2;
              if (distance > .015 ** 2 && distance < near) { nearest = candidate; near = distance; }
              if (distance > far) { farthest = candidate; far = distance; }
            }
            for (let axis = 0; axis < 3; axis++) {
              const change = field[id * 3 + axis] - previousField[id * 3 + axis];
              if (nearest >= 0) {
                const neighbor = field[nearest * 3 + axis] - previousField[nearest * 3 + axis];
                nearSquared += (change - neighbor) ** 2; dot += change * neighbor; lengthA += change ** 2; lengthB += neighbor ** 2;
              }
              if (farthest >= 0) farSquared += (change - (field[farthest * 3 + axis] - previousField[farthest * 3 + axis])) ** 2;
            }
            if (nearest >= 0) nearPairs++; if (farthest >= 0) farPairs++;
          }
          return { samples: points.length, nearPairs, farPairs, neighborCorrelation: dot / Math.max(1e-12, Math.sqrt(lengthA * lengthB)),
            nearDifferenceRms: Math.sqrt(nearSquared / Math.max(1, nearPairs)), farDifferenceRms: Math.sqrt(farSquared / Math.max(1, farPairs)) };
        };
        const coherence = correlate(surfacePoints); interior.coherence = correlate(deepPoints);
        const identities: TrackedParticle[] = [], identityStride = Math.max(1, Math.ceil(count / 2048));
        for (let id = 0; id < count; id += identityStride) {
          const q = Array.from(canonical.subarray(id * 3, id * 3 + 3));
          const camera = transform(modelView, q), clip = [0, 1, 2, 3].map((row) => projection[row] * camera[0] + projection[4 + row] * camera[1] + projection[8 + row] * camera[2] + projection[12 + row] * camera[3]);
          identities.push({ id, position: Array.from(field.subarray(id * 3, id * 3 + 3)), canonical: q, distance: distances[id],
            screen: [(clip[0] / clip[3] + 1) * innerWidth / 2, (1 - clip[1] / clip[3]) * innerHeight / 2] });
        }
        previous = { field, time, volume: volumeTexture };
        request.resolve({ samples: count, changed, deltaRms: Math.sqrt(squaredChange / count), signature: signature >>> 0, enclosure, regions, coherence, interior, shape,
          sdf: { dimensions: [...volume.dimensions], minimum, size: extent, voxel, storage: volume.storage }, stateStorage: size.storage,
          time, at: performance.now(), elapsed, wakeMaximum, identities });
      } catch (error) { request.reject(error instanceof Error ? error : new Error(String(error))); }
      finally {
        gl.activeTexture(previousUnit); gl.bindFramebuffer(gl.READ_FRAMEBUFFER, previousRead);
        if (framebuffer) gl.deleteFramebuffer(framebuffer);
      }
    };
    const prototype = WebGL2RenderingContext.prototype;
    const storage = prototype.texStorage2D, image = prototype.texImage2D;
    prototype.texStorage2D = function (target, levels, format, width, height) {
      storage.call(this, target, levels, format, width, height);
      if (target === this.TEXTURE_2D) { const texture = this.getParameter(this.TEXTURE_BINDING_2D) as WebGLTexture | null; if (texture) sizes.set(texture, { width, height, storage: format }); }
    };
    prototype.texImage2D = function (...args: unknown[]) {
      Reflect.apply(image, this, args);
      if (args[0] === this.TEXTURE_2D && args[1] === 0 && args.length >= 9) {
        const texture = this.getParameter(this.TEXTURE_BINDING_2D) as WebGLTexture | null;
        if (texture) sizes.set(texture, { width: Number(args[3]), height: Number(args[4]), storage: Number(args[2]) });
      }
    };
    const observeVolume = (gl: WebGL2RenderingContext, args: unknown[], sub: boolean) => {
      const data = args[sub ? 10 : 9], dimensions = (sub ? args.slice(5, 8) : args.slice(3, 6)).map(Number);
      if (args[0] !== gl.TEXTURE_3D || args[1] !== 0 || !(data instanceof Uint16Array || data instanceof Float32Array)) return;
      if (sub && args.slice(2, 5).some((value) => value !== 0)) throw new Error("Unexpected partial 3D field upload in QA probe");
      if (data.length !== dimensions.reduce((product, value) => product * value, 4)) throw new Error("Unexpected 3D field channel count");
      const texture = gl.getParameter(gl.TEXTURE_BINDING_3D) as WebGLTexture | null;
      if (texture) volumes.set(texture, { data: data instanceof Float32Array ? data.slice() : Float32Array.from(data, half), dimensions, storage: Number(args[sub ? 9 : 8]) });
    };
    const image3d = prototype.texImage3D, sub3d = prototype.texSubImage3D;
    prototype.texImage3D = function (...args: unknown[]) { Reflect.apply(image3d, this, args); observeVolume(this, args, false); };
    prototype.texSubImage3D = function (...args: unknown[]) { Reflect.apply(sub3d, this, args); observeVolume(this, args, true); };
    const use = prototype.useProgram;
    prototype.useProgram = function (program) { active.set(this, program); return use.call(this, program); };
    const arrays = prototype.drawArrays, elements = prototype.drawElements;
    prototype.drawArrays = function (mode, first, count) { arrays.call(this, mode, first, count); sample(this, mode, count); };
    prototype.drawElements = function (mode, count, type, offset) { elements.call(this, mode, count, type, offset); sample(this, mode, count); };
  });
}

export const particleDisplacement = (page: Page) => page.evaluate(() => (window as unknown as DisplacementWindow).__sampleParticleDisplacement());

export function expectParticlesInsideBoundary(sample: ParticleDisplacement) {
  expect(sample.samples).toBeGreaterThan(1000);
  expect(sample.stateStorage, "absolute position state uses RGBA32F").toBe(0x8814);
  expect(sample.enclosure.radiusMaximum).toBeLessThanOrEqual(CONTAINMENT.radius * PLATFORM_HORIZONTAL_SCALE - .016);
  expect(sample.enclosure.minimumY).toBeGreaterThanOrEqual(CONTAINMENT.bottom + .016);
  expect(sample.enclosure.maximumY).toBeLessThanOrEqual(CONTAINMENT.top - .016);
}

export function expectWholeFaceDeformation(sample: ParticleDisplacement) {
  for (const [name, region] of Object.entries(sample.regions)) {
    expect(region.samples, `${name} has meaningful current-location particle coverage`).toBeGreaterThan(20);
    expect(region.changed, `${name} particles keep moving in enclosure space`).toBeGreaterThan(region.samples * .5);
    expect(region.deltaRms, `${name} changes beyond floating-point noise`).toBeGreaterThan(.001);
  }
}

export function expectCoherentSurfaceMotion(sample: ParticleDisplacement) {
  const coherence = sample.coherence;
  expect(coherence.nearPairs, "nearby current face samples cover the real GPU field").toBeGreaterThan(100);
  expect(coherence.farPairs).toBeGreaterThan(100);
  expect(coherence.neighborCorrelation, "nearby current particles flow together").toBeGreaterThan(.5);
  expect(coherence.nearDifferenceRms).toBeLessThan(coherence.farDifferenceRms * .65);
}

export function expectInteriorPopulation(sample: ParticleDisplacement) {
  expect(sample.interior.samples, "current SDF finds substantial real interior material").toBeGreaterThan(sample.samples * .15);
  expect(sample.interior.deepSamples, "material occupies more than a thin boundary layer").toBeGreaterThan(sample.samples * .05);
  expect(sample.interior.maximumDepth).toBeGreaterThan(sample.sdf.voxel * 3);
}

export function expectAssembledVolume(sample: ParticleDisplacement) {
  expectInteriorPopulation(sample);
  expect(sample.shape.extracted / sample.samples, "almost all idle material stays within two SDF voxels of the shape").toBeLessThan(.05);
  expect(sample.shape.outsideDomain / sample.samples).toBeLessThan(.01);
}

export function expectCoherentInteriorMotion(sample: ParticleDisplacement) {
  expectInteriorPopulation(sample);
  const interior = sample.interior;
  expect(interior.changed, "current interior particles keep moving").toBeGreaterThan(interior.samples * .5);
  expect(interior.deltaRms, "interior moves in enclosure space beyond floating-point noise").toBeGreaterThan(.001);
  expect(interior.coherence.nearPairs).toBeGreaterThan(100); expect(interior.coherence.farPairs).toBeGreaterThan(100);
  expect(interior.coherence.neighborCorrelation).toBeGreaterThan(.5);
  expect(interior.coherence.nearDifferenceRms).toBeLessThan(interior.coherence.farDifferenceRms * .65);
}
