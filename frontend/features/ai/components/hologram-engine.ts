import { FRAGMENT, portraitPoints, VERTEX } from "./hologram-shaders";

export class HologramEngine {
  private gl: WebGLRenderingContext;
  private program: WebGLProgram;
  private buffers: WebGLBuffer[] = [];
  private count = 0;
  private sampleHeight = 900;
  private source: HTMLImageElement | null = null;
  private locations = new Map<string, WebGLUniformLocation | null>();
  constructor(private canvas: HTMLCanvasElement) {
    const gl = canvas.getContext("webgl", { alpha: true, antialias: false, premultipliedAlpha: false, powerPreference: "low-power" });
    if (!gl) throw new Error("WebGL unavailable");
    this.gl = gl;
    const program = gl.createProgram(); if (!program) throw new Error("WebGL allocation failed");
    this.program = program;
    for (const [type, source] of [[gl.VERTEX_SHADER, VERTEX], [gl.FRAGMENT_SHADER, FRAGMENT]] as const) {
      const shader = gl.createShader(type); if (!shader) throw new Error("WebGL allocation failed");
      gl.shaderSource(shader, source); gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) { gl.deleteShader(shader); this.destroy(); throw new Error("Portrait shader unavailable"); }
      gl.attachShader(program, shader); gl.deleteShader(shader);
    }
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) { this.destroy(); throw new Error("Portrait renderer unavailable"); }
    gl.useProgram(program); gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    for (const name of ["viewport", "rotation", "time", "energy", "motion", "pointSize", "speaking", "dark"]) this.locations.set(name, gl.getUniformLocation(program, name));
  }
  setImage(image: HTMLImageElement) {
    this.source = image;
    const gl = this.gl;
    for (const buffer of this.buffers) gl.deleteBuffer(buffer);
    this.buffers = [];
    const points = portraitPoints(image, this.canvas.clientWidth < 640);
    this.sampleHeight = points.height; this.count = points.vertices.length / 3;
    for (const [name, data] of [["position", points.vertices], ["color", points.colors]] as const) {
      const buffer = gl.createBuffer(); if (!buffer) throw new Error("Portrait allocation failed");
      this.buffers.push(buffer); gl.bindBuffer(gl.ARRAY_BUFFER, buffer); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      const location = gl.getAttribLocation(this.program, name); gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 0, 0);
    }
  }
  draw(time: number, energy: number, speaking: boolean, dark: boolean, motion: boolean, pointer: { x: number; y: number }) {
    const gl = this.gl;
    const width = this.canvas.clientWidth, height = this.canvas.clientHeight, dpr = Math.min(devicePixelRatio || 1, 1.75);
    if (width < 1 || height < 1) return;
    if (this.source && this.sampleHeight !== (width < 640 ? 600 : 900)) this.setImage(this.source);
    const w = Math.round(width * dpr), h = Math.round(height * dpr);
    if (this.canvas.width !== w || this.canvas.height !== h) { this.canvas.width = w; this.canvas.height = h; }
    gl.viewport(0, 0, w, h); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); gl.useProgram(this.program);
    const at = (name: string) => this.locations.get(name) ?? null;
    gl.uniform2f(at("viewport"), width, height);
    gl.uniform2f(at("rotation"), pointer.x * .075 + Math.sin(time * .23) * .014, pointer.y * .04);
    gl.uniform1f(at("pointSize"), Math.max(1, Math.min(width / .8, height) * .94 / this.sampleHeight * 1.65 * dpr));
    for (const [name, value] of Object.entries({ time, energy: Math.max(0, Math.min(1, energy)), speaking: Number(speaking), dark: Number(dark), motion: Number(motion) })) gl.uniform1f(at(name), value);
    gl.drawArrays(gl.POINTS, 0, this.count);
  }
  destroy() { for (const buffer of this.buffers) this.gl.deleteBuffer(buffer); this.buffers = []; this.source = null; this.gl.deleteProgram(this.program); }
}
