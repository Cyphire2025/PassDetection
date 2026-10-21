import type { Page } from "@playwright/test";

type PortraitProbe = {
  id: number; draws: number; frames: number; frameTime: number; vertices: number; points: number;
  uniforms: Record<string, number[]>; headUniforms: Record<string, number[]>; errors: string[];
  resources: Record<"buffers" | "programs" | "textures" | "framebuffers" | "renderbuffers", Set<object>>;
  lost: boolean;
  pressurePasses: number; simulationPasses: number; texturedPoints: number; maximumImpulse: number;
};
type ProbeCanvas = HTMLCanvasElement & { __portraitProbe?: PortraitProbe };
type ProbeWindow = Window & { __portraitProbes: PortraitProbe[] };

/** Observe real GPU work; do not replace rendering, clocks, or shader output. */
export async function observeTestHologram(page: Page) {
  await page.addInitScript(() => {
    const probes: PortraitProbe[] = [];
    Object.defineProperty(window, "__portraitProbes", { value: probes });
    let frameTime = 0;
    const requestFrame = window.requestAnimationFrame;
    window.requestAnimationFrame = (callback) => requestFrame.call(window, (time) => { frameTime = time; callback(time); });
    const locations = new WeakMap<WebGLUniformLocation, { name: string; program: WebGLProgram }>();
    const programUniforms = new WeakMap<WebGLProgram, Record<string, number[]>>();
    const activePrograms = new WeakMap<WebGLRenderingContext, WebGLProgram | null>();
    const activeUnits = new WeakMap<WebGLRenderingContext, number>();
    const textureBindings = new WeakMap<WebGLRenderingContext, Map<number, WebGLTexture | null>>();
    const boundTargets = new WeakMap<WebGLRenderingContext, WebGLFramebuffer | null>();
    const renderedTextures = new WeakSet<WebGLTexture>();
    const probe = (context: WebGLRenderingContext) => {
      const canvas = context.canvas as ProbeCanvas;
      if (!canvas.__portraitProbe) {
        const state: PortraitProbe = { id: probes.length, draws: 0, frames: 0, frameTime: -1, vertices: 0, points: 0,
          uniforms: {}, headUniforms: {}, errors: [], lost: false,
          pressurePasses: 0, simulationPasses: 0, texturedPoints: 0, maximumImpulse: 0,
          resources: { buffers: new Set(), programs: new Set(), textures: new Set(), framebuffers: new Set(), renderbuffers: new Set() } };
        canvas.__portraitProbe = state; probes.push(state);
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
      if (state.frameTime !== frameTime) { state.frameTime = frameTime; state.frames++; }
      const program = activePrograms.get(context), uniforms = program && programUniforms.get(program);
      const texture = (name: string) => {
        const unit = uniforms?.[name]?.[0], value = unit === undefined ? null : textureBindings.get(context)?.get(unit);
        return Boolean(value && renderedTextures.has(value));
      };
      if (boundTargets.get(context) && texture("uPressure") && texture("uDivergence")) state.pressurePasses++;
      if (boundTargets.get(context) && texture("uFluid") && texture("textureDisplacement")) state.simulationPasses++;
      if (mode !== context.POINTS) return;
      state.points = Math.max(state.points, count);
      if (uniforms?.articulation) state.headUniforms = { ...uniforms };
      if (texture("displacement") && texture("velocity")) state.texturedPoints++;
    };
    for (const prototype of [WebGLRenderingContext.prototype, WebGL2RenderingContext.prototype]) {
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
  const probeId = id ?? await page.getByTestId("particle-face-test").locator("canvas").evaluate((element) => {
    const probe = (element as ProbeCanvas).__portraitProbe;
    if (!probe) throw new Error("The Test portrait has not submitted WebGL work");
    return probe.id;
  });
  return page.evaluate((index) => {
    const probe = (window as unknown as ProbeWindow).__portraitProbes[index];
    return { id: probe.id, draws: probe.draws, frames: probe.frames, vertices: probe.vertices, points: probe.points,
      uniforms: probe.uniforms, headUniforms: probe.headUniforms, errors: probe.errors, lost: probe.lost,
      pressurePasses: probe.pressurePasses, simulationPasses: probe.simulationPasses, texturedPoints: probe.texturedPoints, maximumImpulse: probe.maximumImpulse,
      buffers: probe.resources.buffers.size, programs: probe.resources.programs.size, textures: probe.resources.textures.size,
      framebuffers: probe.resources.framebuffers.size, renderbuffers: probe.resources.renderbuffers.size };
  }, probeId);
}
