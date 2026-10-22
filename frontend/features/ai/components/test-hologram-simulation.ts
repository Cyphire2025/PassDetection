import * as THREE from "three";
import { GPUComputationRenderer, type Variable } from "three/addons/misc/GPUComputationRenderer.js";
import { HologramFluid } from "./test-hologram-fluid";
import { DISPLACEMENT_STEP, VELOCITY_STEP } from "./test-hologram-simulation-shaders";
import { headFieldUniforms, type HeadFields } from "./test-hologram-fields";

export type HologramSimulationOptions = {
  motion: boolean;
  pointer: THREE.Vector3;
  modelMatrix: THREE.Matrix4;
  enclosureMatrix?: THREE.Matrix4;
  viewProjection: THREE.Matrix4;
  cameraRight: THREE.Vector3;
  cameraUp: THREE.Vector3;
  speechEnergy?: number;
};

/** Absolute enclosure-space particles advect through the moving anatomical volume. */
export class HologramSimulation {
  private readonly compute: GPUComputationRenderer;
  private readonly rest: THREE.DataTexture;
  private readonly uniforms: Record<string, THREE.IUniform>;
  private readonly inverseModel = new THREE.Matrix4();
  private readonly headToEnclosure = new THREE.Matrix4();
  private readonly enclosureToHead = new THREE.Matrix4();
  private readonly previousEnclosureToHead = new THREE.Matrix4();
  private readonly frameDelta = new THREE.Matrix4();
  private fluid?: HologramFluid;
  private displacementVariable!: Variable;
  private velocityVariable!: Variable;
  private copyMaterial?: THREE.Material;
  private moving = false;
  private disposed = false;

  constructor(renderer: THREE.WebGLRenderer, positions: Float32Array, side: number, lowPower: boolean, fields: HeadFields) {
    if (!Number.isInteger(side) || side < 1 || side > renderer.capabilities.maxTextureSize
      || positions.length !== side * side * 3) throw new Error("Invalid hologram particle texture dimensions.");
    if (!renderer.extensions.has("EXT_color_buffer_float")) {
      throw new Error("Hologram simulation requires floating-point render targets.");
    }
    const data = new Float32Array(side * side * 4);
    for (let i = 0; i < side * side; i++) {
      for (let axis = 0; axis < 3; axis++) {
        const value = positions[i * 3 + axis];
        if (!Number.isFinite(value)) throw new Error("Invalid hologram rest geometry.");
        data[i * 4 + axis] = value;
      }
      data[i * 4 + 3] = i < Math.ceil(side * side * .6) ? 1 : 0;
    }
    this.rest = new THREE.DataTexture(data, side, side, THREE.RGBAFormat, THREE.FloatType);
    this.rest.needsUpdate = true;
    this.compute = new GPUComputationRenderer(side, side, renderer);
    this.compute.setDataType(THREE.FloatType);
    this.uniforms = {
      uRest: { value: this.rest }, uFluid: { value: null }, uDt: { value: 0 }, uTime: { value: 0 }, uSpeechEnergy: { value: 0 },
      uInitialize: { value: 1 }, ...headFieldUniforms(fields),
      uModel: { value: new THREE.Matrix4() }, uInverseModel: { value: this.inverseModel },
      uEnclosure: { value: new THREE.Matrix4() }, uInverseEnclosure: { value: new THREE.Matrix4() },
      headToEnclosure: { value: this.headToEnclosure }, enclosureToHead: { value: this.enclosureToHead },
      uFrameDelta: { value: this.frameDelta },
      uViewProjection: { value: new THREE.Matrix4() },
      uCameraRight: { value: new THREE.Vector3() }, uCameraUp: { value: new THREE.Vector3() },
    };
    // The addon's private copy material is not disposed by its dispose() method.
    // Capture its first initialization pass and restore renderer state on failure too.
    const draw = this.compute.doRenderTarget.bind(this.compute);
    this.compute.doRenderTarget = (material, output) => {
      this.copyMaterial ??= material;
      const target = renderer.getRenderTarget();
      const face = renderer.getActiveCubeFace(), mip = renderer.getActiveMipmapLevel();
      const xr = renderer.xr.enabled, shadow = renderer.shadowMap.autoUpdate;
      try { draw(material, output); }
      finally {
        renderer.setRenderTarget(target, face, mip);
        renderer.xr.enabled = xr;
        renderer.shadowMap.autoUpdate = shadow;
      }
    };
    try {
      this.fluid = new HologramFluid(renderer, lowPower);
      this.displacementVariable = this.variable("textureDisplacement", DISPLACEMENT_STEP);
      this.velocityVariable = this.variable("textureVelocity", VELOCITY_STEP);
      const dependencies = [this.displacementVariable, this.velocityVariable];
      for (const variable of dependencies) this.compute.setVariableDependencies(variable, dependencies);
      const error = this.compute.init();
      if (error) throw new Error(error);
    } catch (error) { this.dispose(); throw error; }
  }

  get displacement(): THREE.Texture { return this.compute.getCurrentRenderTarget(this.displacementVariable).texture; }
  get velocity(): THREE.Texture { return this.compute.getCurrentRenderTarget(this.velocityVariable).texture; }

  update(dt: number, time: number, options: HologramSimulationOptions): void {
    if (this.disposed || !this.fluid) return;
    if (!options.motion) {
      if (this.moving) this.reset();
      this.moving = false;
      return;
    }
    if (!Number.isFinite(dt) || dt <= 0 || !Number.isFinite(time)) return;
    // The shader divides this bounded interval into spatial integration steps.
    // Fluid projection retains its independent, conservative advection interval.
    const step = Math.min(dt, .25);
    this.fluid.update(Math.min(step, 1 / 15), options.pointer);
    this.inverseModel.copy(options.modelMatrix).invert();
    if (options.enclosureMatrix) this.headToEnclosure.copy(options.enclosureMatrix).invert().multiply(options.modelMatrix);
    else this.headToEnclosure.identity();
    this.enclosureToHead.copy(this.headToEnclosure).invert();
    if (this.moving) this.frameDelta.copy(this.headToEnclosure).multiply(this.previousEnclosureToHead);
    else this.frameDelta.identity();
    this.previousEnclosureToHead.copy(this.enclosureToHead);
    this.uniforms.uFluid.value = this.fluid.velocity;
    this.uniforms.uInitialize.value = this.moving ? 0 : 1;
    this.uniforms.uDt.value = step;
    this.uniforms.uTime.value = time % 4096;
    this.uniforms.uSpeechEnergy.value = Number.isFinite(options.speechEnergy) ? Math.max(0, Math.min(1, options.speechEnergy!)) : 0;
    this.uniforms.uModel.value.copy(options.modelMatrix);
    this.uniforms.uEnclosure.value.copy(options.enclosureMatrix ?? options.modelMatrix);
    this.uniforms.uInverseEnclosure.value.copy(this.uniforms.uEnclosure.value).invert();
    this.uniforms.uViewProjection.value.copy(options.viewProjection);
    this.uniforms.uCameraRight.value.copy(options.cameraRight);
    this.uniforms.uCameraUp.value.copy(options.cameraUp);
    this.compute.compute();
    this.moving = true;
  }

  private variable(name: string, shader: string): Variable {
    const zero = new THREE.DataTexture(new Uint8Array(4), 1, 1);
    zero.needsUpdate = true;
    const variable = this.compute.addVariable(name, shader, zero);
    Object.assign(variable.material.uniforms, this.uniforms);
    variable.material.depthTest = false;
    variable.material.depthWrite = false;
    variable.material.blending = THREE.NoBlending;
    variable.material.toneMapped = false;
    return variable;
  }

  private reset(): void {
    for (const variable of [this.displacementVariable, this.velocityVariable]) {
      for (const target of variable.renderTargets) this.compute.renderTexture(variable.initialValueTexture, target);
    }
    this.fluid?.reset();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.fluid?.dispose();
    this.compute.dispose();
    this.copyMaterial?.dispose();
    this.rest.dispose();
  }
}
