import type { ExpoWebGLRenderingContext as GL } from 'expo-gl';

import type { JourneyRoute } from '../model/journey-route';
import { createBuffer, createProgram } from './gl-program';
import { boundedCamera, cameraForRoute, cameraMatrix, geoVector, type GlobeCamera, type Vec3 } from './globe-math';
import { EARTH_FRAGMENT, EARTH_VERTEX, OBJECT_FRAGMENT, OBJECT_VERTEX } from './globe-shaders';
import type { LandMask } from './land-asset';
import { uploadLandTexture } from './land-texture';
import { endpointMesh, planeMesh, routeTube } from './route-mesh';

type Mesh = { buffer: WebGLBuffer; count: number };
type Uniforms = { camera: WebGLUniformLocation | null; aspect: WebGLUniformLocation | null; scale: WebGLUniformLocation | null };
export type GlobeRenderer = ReturnType<typeof createGlobeRenderer>;

export function createGlobeRenderer(gl: GL, land: LandMask, mode: 'card' | 'expanded', onFrameError?: () => void) {
  const buffers: WebGLBuffer[] = [];
  const programs: WebGLProgram[] = [];
  const textures: WebGLTexture[] = [];
  let disposed = false;
  let frame = 0;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    buffers.forEach((buffer) => gl.deleteBuffer(buffer));
    programs.forEach((program) => gl.deleteProgram(program));
    textures.forEach((texture) => gl.deleteTexture(texture));
  };

  try {
    const earth = createProgram(gl, EARTH_VERTEX, EARTH_FRAGMENT);
    programs.push(earth);
    const objects = createProgram(gl, OBJECT_VERTEX, OBJECT_FRAGMENT);
    programs.push(objects);
    const buffer = (data: Float32Array, dynamic = false) => {
      const created = createBuffer(gl, data, dynamic);
      buffers.push(created);
      return { buffer: created, count: data.length / 3 };
    };
    const quad = buffer(new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]));
    const plane = buffer(new Float32Array(99), true);
    const texture = uploadLandTexture(gl, land);
    textures.push(texture);

    const uniforms = (program: WebGLProgram): Uniforms => ({
      camera: gl.getUniformLocation(program, 'uCamera'),
      aspect: gl.getUniformLocation(program, 'uAspect'),
      scale: gl.getUniformLocation(program, 'uScale'),
    });
    const earthUniforms = uniforms(earth);
    const objectUniforms = uniforms(objects);
    const cardUniform = gl.getUniformLocation(earth, 'uCard');
    const landUniform = gl.getUniformLocation(earth, 'uLand');
    const colorUniform = gl.getUniformLocation(objects, 'uColor');
    const earthPosition = gl.getAttribLocation(earth, 'aPosition');
    const objectPosition = gl.getAttribLocation(objects, 'aPosition');
    let route: JourneyRoute | null = null;
    let endpoints: readonly [Vec3, Vec3] | null = null;
    let meshes: Mesh[] = [];
    let current = cameraForRoute(null);
    let target = { ...current };
    let active = false;
    let reducedMotion = false;
    let previousTime = 0;
    let needsFrame = true;

    const deleteMeshes = () => {
      meshes.forEach((mesh) => {
        gl.deleteBuffer(mesh.buffer);
        const index = buffers.indexOf(mesh.buffer);
        if (index >= 0) buffers.splice(index, 1);
      });
      meshes = [];
    };

    const draw = () => {
      const width = gl.drawingBufferWidth;
      const height = gl.drawingBufferHeight;
      if (!width || !height) return;
      const shorter = Math.min(width, height);
      const matrix = cameraMatrix(current);
      const setCamera = (locations: Uniforms) => {
        gl.uniformMatrix3fv(locations.camera, false, matrix);
        gl.uniform2f(locations.aspect, width / shorter, height / shorter);
        gl.uniform1f(locations.scale, 0.82 * current.zoom);
      };
      gl.viewport(0, 0, width, height);
      gl.disable(gl.DEPTH_TEST);
      gl.disable(gl.CULL_FACE);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(earth);
      setCamera(earthUniforms);
      gl.uniform1f(cardUniform, mode === 'card' ? 1 : 0);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.uniform1i(landUniform, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, quad.buffer);
      gl.enableVertexAttribArray(earthPosition);
      gl.vertexAttribPointer(earthPosition, 2, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      gl.disableVertexAttribArray(earthPosition);

      if (endpoints) {
        gl.useProgram(objects);
        setCamera(objectUniforms);
        gl.enableVertexAttribArray(objectPosition);
        const drawMesh = (mesh: Mesh, color: readonly [number, number, number, number]) => {
          gl.bindBuffer(gl.ARRAY_BUFFER, mesh.buffer);
          gl.vertexAttribPointer(objectPosition, 3, gl.FLOAT, false, 0, 0);
          gl.uniform4f(colorUniform, ...color);
          gl.drawArrays(gl.TRIANGLES, 0, mesh.count);
        };
        if (meshes[0]) drawMesh(meshes[0], [0.72, 0.91, 0.32, 0.95]);
        meshes.slice(1).forEach((mesh, index) => drawMesh(mesh,
          index % 2 === 0 ? [0.80, 0.96, 0.52, 0.7] : [0.97, 1, 0.93, 1]));
        // Both card and modal renderers use one monotonic clock. The aircraft
        // keeps its position when the destination card expands or closes.
        const progress = reducedMotion ? 0.45 : ((performance.now() + 3500) % 16000) / 16000;
        const vertices = planeMesh(endpoints[0], endpoints[1], progress);
        gl.bindBuffer(gl.ARRAY_BUFFER, plane.buffer);
        gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.DYNAMIC_DRAW);
        plane.count = vertices.length / 3;
        const fade = Math.min(1, progress * 16, (1 - progress) * 16);
        drawMesh(plane, [0.98, 1, 0.99, fade]);
        gl.disableVertexAttribArray(objectPosition);
      }
      gl.flush();
      gl.endFrameEXP();
    };

    const tick = (timestamp: number) => {
      frame = 0;
      if (disposed || !active) return;
      const delta = previousTime ? Math.min(48, timestamp - previousTime) : 16;
      previousTime = timestamp;
      const ease = reducedMotion ? 1 : 1 - Math.exp(-delta / 75);
      current = {
        longitude: current.longitude + (target.longitude - current.longitude) * ease,
        latitude: current.latitude + (target.latitude - current.latitude) * ease,
        zoom: current.zoom + (target.zoom - current.zoom) * ease,
      };
      try { draw(); } catch { dispose(); onFrameError?.(); return; }
      needsFrame = Math.abs(target.longitude - current.longitude) + Math.abs(target.latitude - current.latitude)
        + Math.abs(target.zoom - current.zoom) > 0.0001;
      if ((!reducedMotion && route) || needsFrame) frame = requestAnimationFrame(tick);
    };
    const invalidate = () => {
      if (active && !disposed && !frame) frame = requestAnimationFrame(tick);
    };

    return {
      dispose,
      renderStill: draw,
      getCamera: (): GlobeCamera => ({ ...target }),
      setCamera(camera: GlobeCamera) { target = boundedCamera(camera); invalidate(); },
      resetView() {
        target = cameraForRoute(route);
        const turn = target.longitude - current.longitude;
        target.longitude = current.longitude + Math.atan2(Math.sin(turn), Math.cos(turn));
        invalidate();
      },
      setRoute(nextRoute: JourneyRoute | null) {
        if (disposed) return;
        route = nextRoute;
        current = cameraForRoute(route);
        target = { ...current };
        deleteMeshes();
        endpoints = route ? [geoVector(route.origin), geoVector(route.destination)] : null;
        if (endpoints) {
          meshes.push(buffer(routeTube(...endpoints)));
          endpoints.forEach((point) => {
            meshes.push(buffer(endpointMesh(point, 0.043, true)), buffer(endpointMesh(point, 0.02)));
          });
        }
        invalidate();
      },
      setActive(nextActive: boolean) {
        active = nextActive;
        previousTime = 0;
        if (!active) { cancelAnimationFrame(frame); frame = 0; }
        else invalidate();
      },
      setReducedMotion(value: boolean) { reducedMotion = value; invalidate(); },
    };
  } catch (error) {
    dispose();
    throw error;
  }
}
