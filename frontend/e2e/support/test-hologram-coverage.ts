import type { Page } from "@playwright/test";

export type CoverageRect = { left: number; right: number; top: number; bottom: number };
export type RenderedHead = { width: number; height: number; left: number; top: number; scaleX: number; scaleY: number; mask: string; at: number; time: number };
type CoverageWindow = Window & { __captureRenderedHead: (rect: CoverageRect) => Promise<RenderedHead> };

/** Read before/after the actual head draw; never substitute shaders or output. */
export async function observeRenderedHead(page: Page) {
  await page.addInitScript(() => {
    const active = new WeakMap<WebGL2RenderingContext, WebGLProgram | null>();
    const heads = new WeakMap<WebGLProgram, boolean>();
    let pending: { rect: CoverageRect; resolve: (result: RenderedHead) => void; reject: (error: Error) => void; timer: number } | undefined;
    Object.defineProperty(window, "__captureRenderedHead", { value: (rect: CoverageRect) => new Promise<RenderedHead>((resolve, reject) => {
      if (pending) { reject(new Error("A head coverage capture is already pending")); return; }
      const timer = window.setTimeout(() => { pending = undefined; reject(new Error("No actual head draw was observed")); }, 15000);
      pending = { rect, resolve, reject, timer };
    }) });
    const half = (value: number) => {
      const sign = value & 0x8000 ? -1 : 1, exponent = value >> 10 & 31, mantissa = value & 1023;
      return sign * (exponent ? 1 + mantissa / 1024 : mantissa / 1024) * 2 ** (exponent ? exponent - 15 : -14);
    };
    const before = (gl: WebGL2RenderingContext, mode: number) => {
      const program = active.get(gl);
      if (!pending || mode !== gl.POINTS || !program) return;
      let head = heads.get(program);
      if (head === undefined) {
        head = gl.getUniformLocation(program, "articulation") !== null
          && (gl.getUniformLocation(program, "displacement") !== null || gl.getUniformLocation(program, "pointerStrokes[0]") !== null);
        heads.set(program, head);
      }
      if (!head) return;
      const request = pending; pending = undefined; clearTimeout(request.timer);
      const previous = gl.getParameter(gl.READ_FRAMEBUFFER_BINDING) as WebGLFramebuffer | null;
      try {
        const target = gl.getParameter(gl.DRAW_FRAMEBUFFER_BINDING) as WebGLFramebuffer | null;
        if (!target) throw new Error("Head coverage requires the actual scene render target");
        gl.bindFramebuffer(gl.READ_FRAMEBUFFER, target);
        const viewport = gl.getParameter(gl.VIEWPORT) as Int32Array;
        const scaleX = viewport[2] / innerWidth, scaleY = viewport[3] / innerHeight;
        const left = Math.max(0, Math.floor(request.rect.left * scaleX));
        const top = Math.max(0, Math.floor(request.rect.top * scaleY));
        const width = Math.min(viewport[2], Math.ceil(request.rect.right * scaleX)) - left;
        const height = Math.min(viewport[3], Math.ceil(request.rect.bottom * scaleY)) - top;
        const format = gl.getParameter(gl.IMPLEMENTATION_COLOR_READ_FORMAT) as number;
        const type = gl.getParameter(gl.IMPLEMENTATION_COLOR_READ_TYPE) as number;
        if (format !== gl.RGBA || (type !== gl.FLOAT && type !== gl.HALF_FLOAT && type !== gl.UNSIGNED_BYTE)) throw new Error(`Unsupported scene color readback ${format}/${type}`);
        const read = () => {
          const pixels = type === gl.FLOAT ? new Float32Array(width * height * 4) : type === gl.HALF_FLOAT ? new Uint16Array(width * height * 4) : new Uint8Array(width * height * 4);
          gl.readPixels(left, viewport[3] - top - height, width, height, format, type, pixels);
          const error = gl.getError();
          if (error !== gl.NO_ERROR) throw new Error(`Scene coverage read failed: WebGL ${error}`);
          return pixels;
        };
        const initial = read();
        const value = (pixels: Float32Array | Uint16Array | Uint8Array, index: number) => type === gl.HALF_FLOAT ? half(pixels[index]) : type === gl.UNSIGNED_BYTE ? pixels[index] / 255 : pixels[index];
        return () => {
          try {
            const final = read(), mask = new Uint8Array(width * height);
            for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
              const index = ((height - 1 - y) * width + x) * 4;
              let difference = 0;
              for (let axis = 0; axis < 3; axis++) difference += Math.abs(value(final, index + axis) - value(initial, index + axis));
              mask[y * width + x] = difference > .0005 ? 255 : 0;
            }
            let binary = "";
            for (let offset = 0; offset < mask.length; offset += 16384) binary += String.fromCharCode(...mask.subarray(offset, offset + 16384));
            request.resolve({ width, height, left, top, scaleX, scaleY, mask: btoa(binary), at: performance.now(), time: Number(gl.getUniform(program, gl.getUniformLocation(program, "time")!)) });
          } catch (error) { request.reject(error instanceof Error ? error : new Error(String(error))); }
          finally { gl.bindFramebuffer(gl.READ_FRAMEBUFFER, previous); }
        };
      } catch (error) {
        gl.bindFramebuffer(gl.READ_FRAMEBUFFER, previous);
        request.reject(error instanceof Error ? error : new Error(String(error)));
      }
    };
    const prototype = WebGL2RenderingContext.prototype, use = prototype.useProgram;
    prototype.useProgram = function (program) { active.set(this, program); return use.call(this, program); };
    const arrays = prototype.drawArrays, elements = prototype.drawElements;
    prototype.drawArrays = function (mode, first, count) { const finish = before(this, mode); arrays.call(this, mode, first, count); finish?.(); };
    prototype.drawElements = function (mode, count, type, offset) { const finish = before(this, mode); elements.call(this, mode, count, type, offset); finish?.(); };
  });
}

export const renderedHead = (page: Page, rect: CoverageRect) => page.evaluate((bounds) => (window as unknown as CoverageWindow).__captureRenderedHead(bounds), rect);
