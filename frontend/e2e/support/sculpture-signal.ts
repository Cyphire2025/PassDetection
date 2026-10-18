import type { Page } from "@playwright/test";

/** Count the engine's real draw instances without adding product diagnostics. */
export async function observeSculpture(page: Page) {
  await page.addInitScript(() => {
    const draw = WebGL2RenderingContext.prototype.drawArraysInstanced;
    WebGL2RenderingContext.prototype.drawArraysInstanced = function (mode, first, count, instances) {
      (this.canvas as HTMLCanvasElement & { __particles?: number }).__particles = instances;
      return draw.call(this, mode, first, count, instances);
    };
  });
}

export async function sculptureSignal(page: Page) {
  return page.getByTestId("voice-sculpture").locator("canvas").last().evaluate((element) => {
    const canvas = element as HTMLCanvasElement & { __particles?: number };
    const gl = canvas.getContext("webgl2");
    if (!gl) throw new Error("The sculpture's WebGL context is missing");
    const program = gl.getParameter(gl.CURRENT_PROGRAM) as WebGLProgram;
    const uniform = (name: string) => {
      const location = gl.getUniformLocation(program, name);
      return location ? Number(gl.getUniform(program, location)) : 0;
    };
    return { pointer: uniform("uPointerPresence"), voice: uniform("uVoice"), particles: canvas.__particles ?? 0, error: gl.getError() };
  });
}
