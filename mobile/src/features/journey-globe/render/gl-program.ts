import type { ExpoWebGLRenderingContext as GL } from 'expo-gl';

export function createProgram(gl: GL, vertexSource: string, fragmentSource: string): WebGLProgram {
  const shaders: WebGLShader[] = [];
  const program = gl.createProgram();
  if (!program) throw new Error('GL program unavailable');
  try {
    for (const [type, source] of [[gl.VERTEX_SHADER, vertexSource], [gl.FRAGMENT_SHADER, fragmentSource]] as const) {
      const shader = gl.createShader(type);
      if (!shader) throw new Error('GL shader unavailable');
      shaders.push(shader);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error('Globe shader could not compile');
      gl.attachShader(program, shader);
    }
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Globe shader could not link');
    return program;
  } catch (error) {
    try { gl.deleteProgram(program); } catch { /* Preserve the original failure after context loss. */ }
    throw error;
  } finally {
    shaders.forEach((shader) => {
      try { gl.deleteShader(shader); } catch { /* Continue releasing the other shader handles. */ }
    });
  }
}

export function createBuffer(gl: GL, vertices: Float32Array, dynamic = false): WebGLBuffer {
  const buffer = gl.createBuffer();
  if (!buffer) throw new Error('Globe vertex buffer unavailable');
  try {
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, vertices, dynamic ? gl.DYNAMIC_DRAW : gl.STATIC_DRAW);
    return buffer;
  } catch (error) {
    try { gl.deleteBuffer(buffer); } catch { /* Native context may already be gone. */ }
    throw error;
  }
}
