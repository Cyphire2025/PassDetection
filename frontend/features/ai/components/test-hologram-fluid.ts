import * as THREE from "three";
import { FullScreenQuad } from "three/addons/postprocessing/Pass.js";
import { FLUID_ADVECT, FLUID_DIVERGENCE, FLUID_PRESSURE, FLUID_PROJECT, FLUID_VERTEX } from "./test-hologram-fluid-shaders";

/** Bounded velocity/wake field; pressure projection keeps pointer strokes coherent. */
export class HologramFluid {
  private readonly targets: THREE.WebGLRenderTarget[] = [];
  private readonly materials: THREE.ShaderMaterial[] = [];
  private readonly quad = new FullScreenQuad();
  private readonly clearColor = new THREE.Color();
  private readonly drawingSize = new THREE.Vector2();
  private readonly previous = new THREE.Vector2();
  private readonly pointer = new THREE.Vector2();
  private readonly impulse = new THREE.Vector2();
  private readonly uniforms: Record<string, THREE.IUniform>;
  private velocityIndex = 0;
  private pressureIndex = 2;
  private pointerActive = false;
  private disposed = false;

  constructor(private readonly renderer: THREE.WebGLRenderer, private readonly lowPower: boolean) {
    const size = lowPower ? 96 : 128;
    this.uniforms = {
      uVelocity: { value: null }, uPressure: { value: null }, uDivergence: { value: null },
      uTexel: { value: new THREE.Vector2(1 / size, 1 / size) }, uDt: { value: 0 },
      uPointer: { value: this.pointer }, uPrevious: { value: this.previous },
      uImpulse: { value: this.impulse }, uAspect: { value: 1 },
    };
    try {
      for (let i = 0; i < 5; i++) this.targets.push(new THREE.WebGLRenderTarget(size, size, {
        type: THREE.HalfFloatType, format: THREE.RGBAFormat,
        minFilter: i < 2 ? THREE.LinearFilter : THREE.NearestFilter,
        magFilter: i < 2 ? THREE.LinearFilter : THREE.NearestFilter,
        depthBuffer: false, stencilBuffer: false,
      }));
      for (const fragmentShader of [FLUID_ADVECT, FLUID_DIVERGENCE, FLUID_PRESSURE, FLUID_PROJECT]) {
        this.materials.push(new THREE.ShaderMaterial({
          uniforms: this.uniforms, vertexShader: FLUID_VERTEX, fragmentShader,
          depthTest: false, depthWrite: false, blending: THREE.NoBlending, toneMapped: false,
        }));
      }
      this.reset();
    } catch (error) { this.dispose(); throw error; }
  }

  get velocity(): THREE.Texture { return this.targets[this.velocityIndex].texture; }

  update(dt: number, pointer: THREE.Vector3): void {
    if (this.disposed) return;
    const valid = Number.isFinite(pointer.x) && Number.isFinite(pointer.y) && Number.isFinite(pointer.z);
    const active = valid && pointer.z > 0 && Math.abs(pointer.x) <= 1.1 && Math.abs(pointer.y) <= 1.1;
    // Inactive coordinates must also stay representable as GLSL floats: a zero
    // impulse cannot neutralize NaN produced by an infinite stroke position.
    this.pointer.set(active ? pointer.x * 0.5 + 0.5 : 0.5, active ? pointer.y * 0.5 + 0.5 : 0.5);
    // Entering/leaving the canvas never draws a stroke from the stale pointer.
    if (!active || !this.pointerActive) this.previous.copy(this.pointer);
    this.impulse.subVectors(this.pointer, this.previous).clampLength(0, 0.08);
    this.impulse.multiplyScalar(active ? Math.min(pointer.z, 1) * 24 : 0);
    this.renderer.getDrawingBufferSize(this.drawingSize);
    this.uniforms.uAspect.value = this.drawingSize.x / Math.max(this.drawingSize.y, 1);
    this.uniforms.uDt.value = dt;

    const target = this.renderer.getRenderTarget();
    const face = this.renderer.getActiveCubeFace(), mip = this.renderer.getActiveMipmapLevel();
    const xr = this.renderer.xr.enabled, shadow = this.renderer.shadowMap.autoUpdate;
    try {
      this.renderer.xr.enabled = false;
      this.renderer.shadowMap.autoUpdate = false;
      this.uniforms.uVelocity.value = this.velocity;
      this.draw(0, 1 - this.velocityIndex);
      this.velocityIndex = 1 - this.velocityIndex;
      this.uniforms.uVelocity.value = this.velocity;
      this.draw(1, 4);
      this.uniforms.uDivergence.value = this.targets[4].texture;
      const iterations = this.lowPower ? 6 : 10;
      // Previous pressure is a warm start; divergence and projection use this frame's flow.
      for (let i = 0; i < iterations; i++) {
        this.uniforms.uPressure.value = this.targets[this.pressureIndex].texture;
        this.draw(2, 5 - this.pressureIndex);
        this.pressureIndex = 5 - this.pressureIndex;
      }
      this.uniforms.uPressure.value = this.targets[this.pressureIndex].texture;
      this.draw(3, 1 - this.velocityIndex);
      this.velocityIndex = 1 - this.velocityIndex;
    } finally {
      this.renderer.setRenderTarget(target, face, mip);
      this.renderer.xr.enabled = xr;
      this.renderer.shadowMap.autoUpdate = shadow;
    }
    this.previous.copy(this.pointer);
    this.pointerActive = active;
  }

  reset(): void {
    if (this.disposed) return;
    const target = this.renderer.getRenderTarget();
    const face = this.renderer.getActiveCubeFace(), mip = this.renderer.getActiveMipmapLevel();
    const alpha = this.renderer.getClearAlpha();
    this.renderer.getClearColor(this.clearColor);
    try {
      this.renderer.setClearColor(0, 0);
      for (const output of this.targets) {
        this.renderer.setRenderTarget(output);
        const gl = this.renderer.getContext();
        if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
          throw new Error("Hologram flow requires renderable half-float textures.");
        }
        this.renderer.clear(true, false, false);
      }
    } finally {
      this.renderer.setClearColor(this.clearColor, alpha);
      this.renderer.setRenderTarget(target, face, mip);
    }
    this.pointerActive = false;
    this.impulse.set(0, 0);
  }

  private draw(material: number, target: number): void {
    this.quad.material = this.materials[material];
    this.renderer.setRenderTarget(this.targets[target]);
    this.quad.render(this.renderer);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.quad.dispose();
    for (const material of this.materials) material.dispose();
    for (const target of this.targets) target.dispose();
  }
}
