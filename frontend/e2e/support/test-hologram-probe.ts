import type { Page } from "@playwright/test";
import { observeHologramDiagnostics } from "./test-hologram-diagnostics";

export type HologramHeadFrame = {
  at: number; modelView: number[]; cameraView: number[]; speechEnergy: number; articulation: number[];
};

type PortraitProbe = {
  id: number; draws: number; frames: number; frameTime: number; firstFrameTime: number; vertices: number; points: number;
  uniforms: Record<string, number[]>; headUniforms: Record<string, number[]>; landscapeUniforms: Record<string, number[]>; landscapeCameras: number[][]; errors: string[];
  resources: Record<"buffers" | "programs" | "textures" | "framebuffers" | "renderbuffers", Set<object>>;
  lost: boolean;
  headFrames: HologramHeadFrame[];
  lastHomeAt: number;
  parts: Record<string, Array<{ uniforms: Record<string, number[]>; vertices: number }>>;
  pressurePasses: number; simulationPasses: number; texturedPoints: number; headNonPointDraws: number; landscapeDraws: number; mountainDraws: number; maximumImpulse: number;
};
type ProbeCanvas = HTMLCanvasElement & { __portraitProbe?: PortraitProbe };
type ProbeWindow = Window & { __portraitProbes: PortraitProbe[] };

/** Observe real GPU work; do not replace rendering, clocks, or shader output. */
export async function observeTestHologram(page: Page) {
  await observeHologramDiagnostics(page);
  await page.addInitScript(() => {
    const probes: PortraitProbe[] = [];
    Object.defineProperty(window, "__portraitProbes", { value: probes });
    let frameTime = 0;
    const requestFrame = window.requestAnimationFrame;
    window.requestAnimationFrame = (callback) => requestFrame.call(window, (time) => { frameTime = time; callback(time); });
    const locations = new WeakMap<WebGLUniformLocation, { name: string; program: WebGLProgram }>();
    const programUniforms = new WeakMap<WebGLProgram, Record<string, number[]>>();
    const namedShaders = new WeakMap<WebGLShader, string>(), namedPrograms = new WeakMap<WebGLProgram, string>();
    const activePrograms = new WeakMap<WebGLRenderingContext, WebGLProgram | null>();
    const activeUnits = new WeakMap<WebGLRenderingContext, number>();
    const textureBindings = new WeakMap<WebGLRenderingContext, Map<number, WebGLTexture | null>>();
    const boundTargets = new WeakMap<WebGLRenderingContext, WebGLFramebuffer | null>();
    const renderedTextures = new WeakSet<WebGLTexture>();
    const uploadedTextures = new WeakSet<WebGLTexture>();
    const uploaded = (context: WebGLRenderingContext, args: unknown[], subimage: boolean, compressed: boolean) => {
      const image = args[subimage ? 6 : 5] as { width?: number; height?: number } | null;
      const numericSize = compressed || args.length >= 9;
      const width = numericSize ? args[subimage ? 4 : 3] : image?.width;
      const height = numericSize ? args[subimage ? 5 : 4] : image?.height;
      const data = compressed ? args[subimage ? 7 : 6] : numericSize ? args[8] : image;
      const texture = textureBindings.get(context)?.get(activeUnits.get(context) ?? 0);
      if (texture && data && typeof width === "number" && typeof height === "number" && width > 4 && height > 4) uploadedTextures.add(texture);
    };
    const probe = (context: WebGLRenderingContext) => {
      const canvas = context.canvas as ProbeCanvas;
      if (!canvas.__portraitProbe) {
        const state: PortraitProbe = { id: probes.length, draws: 0, frames: 0, frameTime: -1, firstFrameTime: 0, vertices: 0, points: 0,
          uniforms: {}, headUniforms: {}, landscapeUniforms: {}, landscapeCameras: [], errors: [], lost: false, parts: {}, headFrames: [], lastHomeAt: -1,
          pressurePasses: 0, simulationPasses: 0, texturedPoints: 0, headNonPointDraws: 0, landscapeDraws: 0, mountainDraws: 0, maximumImpulse: 0,
          resources: { buffers: new Set(), programs: new Set(), textures: new Set(), framebuffers: new Set(), renderbuffers: new Set() } };
        canvas.__portraitProbe = state; probes.push(state);
        canvas.addEventListener("keydown", (event) => { if (event.key === "Home") state.lastHomeAt = performance.now(); }, { capture: true });
        canvas.addEventListener("webglcontextlost", () => { state.lost = true; Object.values(state.resources).forEach((resources) => resources.clear()); });
        canvas.addEventListener("webglcontextrestored", () => { state.lost = false; });
      }
      return canvas.__portraitProbe;
    };
    const record = (context: WebGLRenderingContext, location: WebGLUniformLocation | null, values: number[]) => {
      const info = location && locations.get(location);
      if (!info) return;
      probe(context).uniforms[info.name] = values;
      if (info.name === "uImpulse") probe(context).maximumImpulse = Math.max(probe(context).maximumImpulse, Math.hypot(...values));
      const uniforms = programUniforms.get(info.program) ?? {};
      uniforms[info.name] = values; programUniforms.set(info.program, uniforms);
    };
    const draw = (context: WebGLRenderingContext, mode: number, count: number) => {
      const state = probe(context); state.draws++; state.vertices = Math.max(state.vertices, count);
      if (state.frameTime !== frameTime) {
        if (!state.frames) state.firstFrameTime = frameTime;
        state.frameTime = frameTime; state.frames++;
        state.parts = {};
      }
      const program = activePrograms.get(context), uniforms = program && programUniforms.get(program);
      const part = program && namedPrograms.get(program);
      if (part && uniforms) (state.parts[part] ??= []).push({ uniforms: { ...uniforms }, vertices: count });
      // Identify articulated head passes by their actual uniforms, not only by
      // material names, so renaming a solid support mesh cannot hide it.
      if (mode !== context.POINTS && uniforms?.articulation && uniforms.headToEnclosure
        && uniforms.modelViewMatrix && uniforms.projectionMatrix) state.headNonPointDraws++;
      const texture = (name: string, textures = renderedTextures) => {
        const unit = uniforms?.[name]?.[0], value = unit === undefined ? null : textureBindings.get(context)?.get(unit);
        return Boolean(value && textures.has(value));
      };
      if (boundTargets.get(context) && texture("uPressure") && texture("uDivergence")) state.pressurePasses++;
      if (boundTargets.get(context) && texture("uFluid") && texture("textureDisplacement")) state.simulationPasses++;
      if (mode === context.TRIANGLES && texture("tMap", uploadedTextures) && texture("tWind", uploadedTextures)) {
        state.landscapeDraws++;
        if ((uniforms?.mountain?.[0] ?? 0) > .5) state.mountainDraws++;
        // Read the camera submitted to terrain, not later portrait/compositor matrices.
        state.landscapeUniforms = { ...uniforms };
        const camera = uniforms?.viewMatrix, previous = state.landscapeCameras.at(-1);
        if (camera && (!previous || camera.some((value, index) => value !== previous[index]))) {
          state.landscapeCameras.push([...camera]);
          if (state.landscapeCameras.length > 64) state.landscapeCameras.shift();
        }
      }
      if (mode !== context.POINTS) return;
      state.points = Math.max(state.points, count);
      if (uniforms?.articulation) {
        state.headUniforms = { ...uniforms };
        const camera = uniforms.viewMatrix ?? state.landscapeUniforms.viewMatrix;
        if (uniforms.modelViewMatrix && camera && state.headFrames.at(-1)?.at !== frameTime) {
          state.headFrames.push({ at: frameTime, modelView: [...uniforms.modelViewMatrix], cameraView: [...camera],
            speechEnergy: uniforms.speechEnergy?.[0] ?? 0, articulation: [...uniforms.articulation] });
          if (state.headFrames.length > 96) state.headFrames.shift();
        }
      }
      if (texture("displacement") && texture("velocity")) state.texturedPoints++;
    };
    for (const prototype of [WebGLRenderingContext.prototype, WebGL2RenderingContext.prototype]) {
      const shaderSource = prototype.shaderSource, attachShader = prototype.attachShader;
      prototype.shaderSource = function (shader, source) {
        const names: Record<string, string> = {
          "Frosted layered stone": "pedestal", "Cylindrical interaction enclosure": "cage", "Cylindrical interaction scan": "cage",
          "Projector aperture": "projector", "Projector upward rays": "projectorRays",
          "Human shadow core": "headSurface",
          "Human authored edge light": "headWire",
        };
        for (const [name, part] of Object.entries(names)) if (source.includes(`#define SHADER_NAME ${name}\n`)) namedShaders.set(shader, part);
        return shaderSource.call(this, shader, source);
      };
      prototype.attachShader = function (program, shader) {
        const name = namedShaders.get(shader); if (name) namedPrograms.set(program, name);
        return attachShader.call(this, program, shader);
      };
      const getUniformLocation = prototype.getUniformLocation;
      prototype.getUniformLocation = function (program, name) {
        const location = getUniformLocation.call(this, program, name);
        if (location) locations.set(location, { name, program }); return location;
      };
      const useProgram = prototype.useProgram;
      prototype.useProgram = function (program) { activePrograms.set(this, program); return useProgram.call(this, program); };
      const activeTexture = prototype.activeTexture, bindTexture = prototype.bindTexture;
      prototype.activeTexture = function (unit) { activeUnits.set(this, unit - this.TEXTURE0); return activeTexture.call(this, unit); };
      prototype.bindTexture = function (target, value) {
        const bindings = textureBindings.get(this) ?? new Map<number, WebGLTexture | null>();
        bindings.set(activeUnits.get(this) ?? 0, value); textureBindings.set(this, bindings);
        return bindTexture.call(this, target, value);
      };
      const texImage2D = prototype.texImage2D, texSubImage2D = prototype.texSubImage2D;
      prototype.texImage2D = function (...args: unknown[]) {
        Reflect.apply(texImage2D, this, args); uploaded(this, args, false, false);
      };
      prototype.texSubImage2D = function (...args: unknown[]) {
        Reflect.apply(texSubImage2D, this, args); uploaded(this, args, true, false);
      };
      const compressedTexImage2D = prototype.compressedTexImage2D, compressedTexSubImage2D = prototype.compressedTexSubImage2D;
      prototype.compressedTexImage2D = function (...args: Parameters<WebGL2RenderingContext["compressedTexImage2D"]>) {
        Reflect.apply(compressedTexImage2D, this, args); uploaded(this, args, false, true);
      };
      prototype.compressedTexSubImage2D = function (...args: Parameters<WebGL2RenderingContext["compressedTexSubImage2D"]>) {
        Reflect.apply(compressedTexSubImage2D, this, args); uploaded(this, args, true, true);
      };
      const bindFramebuffer = prototype.bindFramebuffer, framebufferTexture2D = prototype.framebufferTexture2D;
      prototype.bindFramebuffer = function (target, value) { boundTargets.set(this, value); return bindFramebuffer.call(this, target, value); };
      prototype.framebufferTexture2D = function (target, attachment, textureTarget, value, level) {
        if (value) renderedTextures.add(value); return framebufferTexture2D.call(this, target, attachment, textureTarget, value, level);
      };
      const uniform1i = prototype.uniform1i;
      prototype.uniform1i = function (location, value) { record(this, location, [value]); return uniform1i.call(this, location, value); };
      const uniform1f = prototype.uniform1f;
      prototype.uniform1f = function (location, x) { record(this, location, [x]); return uniform1f.call(this, location, x); };
      const uniform2f = prototype.uniform2f;
      prototype.uniform2f = function (location, x, y) { record(this, location, [x, y]); return uniform2f.call(this, location, x, y); };
      const uniform3f = prototype.uniform3f;
      prototype.uniform3f = function (location, x, y, z) { record(this, location, [x, y, z]); return uniform3f.call(this, location, x, y, z); };
      const uniform4f = prototype.uniform4f;
      prototype.uniform4f = function (location, x, y, z, w) { record(this, location, [x, y, z, w]); return uniform4f.call(this, location, x, y, z, w); };
      const uniform2fv = prototype.uniform2fv;
      prototype.uniform2fv = function (...args: Parameters<WebGL2RenderingContext["uniform2fv"]>) { record(this, args[0], Array.from(args[1])); return Reflect.apply(uniform2fv, this, args); };
      const uniform3fv = prototype.uniform3fv;
      prototype.uniform3fv = function (...args: Parameters<WebGL2RenderingContext["uniform3fv"]>) { record(this, args[0], Array.from(args[1])); return Reflect.apply(uniform3fv, this, args); };
      const uniform4fv = prototype.uniform4fv;
      prototype.uniform4fv = function (...args: Parameters<WebGL2RenderingContext["uniform4fv"]>) { record(this, args[0], Array.from(args[1])); return Reflect.apply(uniform4fv, this, args); };
      const uniformMatrix4fv = prototype.uniformMatrix4fv;
      prototype.uniformMatrix4fv = function (...args: Parameters<WebGL2RenderingContext["uniformMatrix4fv"]>) {
        record(this, args[0], Array.from(args[2])); return Reflect.apply(uniformMatrix4fv, this, args);
      };
      const drawArrays = prototype.drawArrays;
      prototype.drawArrays = function (mode, first, count) { draw(this, mode, count); return drawArrays.call(this, mode, first, count); };
      const drawElements = prototype.drawElements;
      prototype.drawElements = function (mode, count, type, offset) { draw(this, mode, count); return drawElements.call(this, mode, count, type, offset); };
      const createBuffer = prototype.createBuffer, deleteBuffer = prototype.deleteBuffer;
      prototype.createBuffer = function () { const value = createBuffer.call(this); if (value) probe(this).resources.buffers.add(value); return value; };
      prototype.deleteBuffer = function (value) { if (value) probe(this).resources.buffers.delete(value); return deleteBuffer.call(this, value); };
      const createProgram = prototype.createProgram, deleteProgram = prototype.deleteProgram;
      prototype.createProgram = function () { const value = createProgram.call(this); if (value) probe(this).resources.programs.add(value); return value; };
      prototype.deleteProgram = function (value) { if (value) probe(this).resources.programs.delete(value); return deleteProgram.call(this, value); };
      const createTexture = prototype.createTexture, deleteTexture = prototype.deleteTexture;
      prototype.createTexture = function () { const value = createTexture.call(this); if (value) probe(this).resources.textures.add(value); return value; };
      prototype.deleteTexture = function (value) { if (value) probe(this).resources.textures.delete(value); return deleteTexture.call(this, value); };
      const createFramebuffer = prototype.createFramebuffer, deleteFramebuffer = prototype.deleteFramebuffer;
      prototype.createFramebuffer = function () { const value = createFramebuffer.call(this); if (value) probe(this).resources.framebuffers.add(value); return value; };
      prototype.deleteFramebuffer = function (value) { if (value) probe(this).resources.framebuffers.delete(value); return deleteFramebuffer.call(this, value); };
      const createRenderbuffer = prototype.createRenderbuffer, deleteRenderbuffer = prototype.deleteRenderbuffer;
      prototype.createRenderbuffer = function () { const value = createRenderbuffer.call(this); if (value) probe(this).resources.renderbuffers.add(value); return value; };
      prototype.deleteRenderbuffer = function (value) { if (value) probe(this).resources.renderbuffers.delete(value); return deleteRenderbuffer.call(this, value); };
      const compileShader = prototype.compileShader;
      prototype.compileShader = function (shader) {
        compileShader.call(this, shader);
        if (!this.getShaderParameter(shader, this.COMPILE_STATUS)) probe(this).errors.push(this.getShaderInfoLog(shader) || "Shader compilation failed");
      };
      const linkProgram = prototype.linkProgram;
      prototype.linkProgram = function (program) {
        linkProgram.call(this, program);
        if (!this.getProgramParameter(program, this.LINK_STATUS)) probe(this).errors.push(this.getProgramInfoLog(program) || "Program linking failed");
      };
    }
  });
}

export async function testHologramSignal(page: Page, id?: number) {
  return page.evaluate((index) => {
    const probe = index === undefined
      ? (document.querySelector('[data-testid="particle-face-test"] canvas') as ProbeCanvas | null)?.__portraitProbe
      : (window as unknown as ProbeWindow).__portraitProbes[index];
    if (!probe) throw new Error("The Test portrait has not submitted WebGL work");
    return { id: probe.id, draws: probe.draws, frames: probe.frames, vertices: probe.vertices, points: probe.points,
      uniforms: probe.uniforms, headUniforms: probe.headUniforms, landscapeUniforms: probe.landscapeUniforms, errors: probe.errors, lost: probe.lost, parts: probe.parts,
      pressurePasses: probe.pressurePasses, simulationPasses: probe.simulationPasses, texturedPoints: probe.texturedPoints, headNonPointDraws: probe.headNonPointDraws,
      landscapeDraws: probe.landscapeDraws, mountainDraws: probe.mountainDraws, landscapeCameras: probe.landscapeCameras, maximumImpulse: probe.maximumImpulse,
      buffers: probe.resources.buffers.size, programs: probe.resources.programs.size, textures: probe.resources.textures.size,
      framebuffers: probe.resources.framebuffers.size, renderbuffers: probe.resources.renderbuffers.size };
  }, id);
}

/** Bounded history of submitted head poses, independent of React or synthetic clocks. */
export async function testHologramHeadFrames(page: Page) {
  return page.evaluate(() => {
    const probe = (document.querySelector('[data-testid="particle-face-test"] canvas') as ProbeCanvas | null)?.__portraitProbe;
    if (!probe) throw new Error("The Test portrait has not submitted WebGL work");
    return probe.headFrames;
  });
}

export async function testHologramLastHomeAt(page: Page) {
  return page.evaluate(() => (document.querySelector('[data-testid="particle-face-test"] canvas') as ProbeCanvas | null)?.__portraitProbe?.lastHomeAt ?? -1);
}
