import { morphTargets } from "./morph-targets";
import { DEFAULT_APPEARANCE, type SculptureAppearance } from "./types";
/** Targets change; particle IDs, source colours and instance count stay intact. */
export class MorphField {
    amount = 0;
    blend = 1;
    selection: SculptureAppearance = DEFAULT_APPEARANCE;
    private key = "";
    private progress = 1;
    private count = 0;
    private height = 1;
    private before: Float32Array = new Float32Array(0);
    private after: Float32Array = new Float32Array(0);
    private textures: WebGLTexture[] = [];
    private logo: HTMLImageElement | null = null;
    private disposed = false;
    constructor(private gl: WebGL2RenderingContext, private width: number, private wake: () => void) {
        const image = new Image();
        image.onload = () => { if (this.disposed)
            return; this.logo = image; if (this.selection.mode === "logo") {
            this.key = "";
            this.select(this.selection);
            this.wake();
        } };
        image.src = "/globalconnect-logo-transparent.png";
    }
    rebuild(count: number, height: number) {
        this.count = count;
        this.height = height;
        this.before = new Float32Array(this.width * height * 4);
        this.after = this.before.slice();
        this.key = "";
        this.upload();
        this.select(this.selection);
    }
    select(value: SculptureAppearance) {
        this.selection = value;
        const key = JSON.stringify([value.mode, value.text, value.emoji]);
        if (key === this.key || !this.count)
            return;
        this.key = key;
        if (value.mode === "sculpture")
            return;
        const next = morphTargets(value, this.count, this.width * this.height, this.logo);
        this.before = this.amount < .001 ? next.slice() : this.before.map((point, index) => point + (this.after[index] - point) * this.blend);
        this.after = next;
        this.progress = 0;
        this.blend = 0;
        this.upload();
    }
    step(dt: number, reduced: boolean) {
        this.progress = reduced ? 1 : Math.min(1, this.progress + dt / 84);
        const p = this.progress;
        this.blend = p * p * (3 - 2 * p);
        const target = this.selection.mode === "sculpture" ? 0 : 1;
        this.amount = reduced ? target : this.amount + (target - this.amount) * (1 - Math.pow(.94, dt));
        if (Math.abs(this.amount - target) < .001)
            this.amount = target;
    }
    get active() { return this.amount > 0 || this.selection.mode !== "sculpture"; }
    get transitioning() { return this.progress < 1 || Math.abs(this.amount - (this.selection.mode === "sculpture" ? 0 : 1)) > .001; }
    bind(uniforms: Record<string, WebGLUniformLocation | null>, w: number, h: number) {
        const gl = this.gl;
        for (let i = 0; i < 2; i++) {
            gl.activeTexture(gl.TEXTURE4 + i);
            gl.bindTexture(gl.TEXTURE_2D, this.textures[i]);
            gl.uniform1i(uniforms[i ? "uMorphAfter" : "uMorphBefore"], 4 + i);
        }
        gl.uniform1f(uniforms.uMorph, this.amount);
        gl.uniform1f(uniforms.uMorphMix, this.blend);
        gl.uniform2f(uniforms.uMorphSize, w * .48, h * .48);
    }
    private upload() {
        const gl = this.gl;
        if (!this.textures.length)
            this.textures = [gl.createTexture()!, gl.createTexture()!];
        for (let i = 0; i < 2; i++) {
            gl.bindTexture(gl.TEXTURE_2D, this.textures[i]);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, this.width, this.height, 0, gl.RGBA, gl.FLOAT, i ? this.after : this.before);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        }
    }
    destroy() { this.disposed = true; for (const texture of this.textures)
        this.gl.deleteTexture(texture); }
}
