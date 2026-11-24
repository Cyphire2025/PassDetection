export const VERTEX = `
precision highp float;
attribute vec3 position;
attribute vec3 color;
uniform vec2 viewport;
uniform vec2 rotation;
uniform float time;
uniform float energy;
uniform float motion;
uniform float pointSize;
uniform float speaking;
varying vec3 tint;
varying float opacity;
varying float spriteSize;
void main() {
  vec3 p = position;
  float mouth = exp(-pow((p.y + 0.145) / 0.065, 2.0) - pow(p.x / 0.16, 2.0));
  p.y -= mouth * energy * speaking * 0.014 * motion;
  p.z += sin(time * 1.2 + p.y * 4.0) * 0.002 * motion;
  float yaw = rotation.x * motion, pitch = rotation.y * motion;
  p.xz = mat2(cos(yaw), -sin(yaw), sin(yaw), cos(yaw)) * p.xz;
  p.yz = mat2(cos(pitch), -sin(pitch), sin(pitch), cos(pitch)) * p.yz;
  float perspective = 2.8 / (2.8 - p.z);
  float scale = min(viewport.x / 0.8, viewport.y) * 0.94;
  gl_Position = vec4(p.x * scale / viewport.x * 2.0 * perspective, p.y * scale / viewport.y * 2.0 * perspective, -p.z * 0.1, 1.0);
  gl_PointSize = pointSize * perspective;
  spriteSize = gl_PointSize;
  tint = color;
  opacity = 0.92 + sin(time * 1.1 + p.x * 37.0 + p.y * 23.0) * 0.08 * motion;
}`;

export const FRAGMENT = `
precision mediump float;
varying vec3 tint;
varying float opacity;
varying float spriteSize;
uniform float dark;
void main() {
  float radius = length(gl_PointCoord - vec2(0.5));
  // Subpixel circles on a regular grid create large moire bands across skin.
  // Dense surface samples cover pixels; only larger particles need round edges.
  float alpha = mix(1.0, 1.0 - smoothstep(0.30, 0.5, radius), smoothstep(2.0, 3.5, spriteSize));
  float luminance = dot(tint, vec3(0.2126, 0.7152, 0.0722));
  vec3 lightInk = mix(vec3(0.10, 0.18, 0.24), vec3(0.47, 0.60, 0.65), luminance);
  gl_FragColor = vec4(mix(lightInk, tint * 1.16, dark), alpha * opacity);
}`;

/** A sampled portrait on an anatomical relief, with real XYZ parallax.
 * It is not a scanned or fully rigged human mesh. Keep the viewing arc subtle.
 */
export function portraitPoints(image: HTMLImageElement, mobile: boolean) {
  const height = mobile ? 600 : 900, width = Math.round(height * image.naturalWidth / image.naturalHeight);
  const canvas = document.createElement("canvas"); canvas.width = width; canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("Portrait sampling unavailable");
  context.drawImage(image, 0, 0, width, height);
  const pixels = context.getImageData(0, 0, width, height).data;
  const vertices: number[] = [], colors: number[] = [];
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const offset = (y * width + x) * 4;
    const light = Math.max(pixels[offset], pixels[offset + 1], pixels[offset + 2]);
    if (light < 20) continue;
    const px = (x - width / 2) / height, py = 0.5 - y / height;
    const oval = Math.max(0, 1 - (px / .30) ** 2 - ((py - .05) / .46) ** 2);
    const nose = .075 * Math.exp(-((px / .055) ** 2) - ((py + .025) / .10) ** 2);
    const cheeks = .018 * Math.exp(-(((Math.abs(px) - .12) / .07) ** 2) - ((py + .05) / .10) ** 2);
    vertices.push(px, py, Math.sqrt(oval) * .14 + nose + cheeks);
    colors.push(pixels[offset] / 255, pixels[offset + 1] / 255, pixels[offset + 2] / 255);
  }
  return { vertices: new Float32Array(vertices), colors: new Float32Array(colors), height };
}
