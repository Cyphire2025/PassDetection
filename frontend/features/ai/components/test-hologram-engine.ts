import { BufferAttribute, BufferGeometry, Group, HalfFloatType, Matrix4, Points, Scene, NeutralToneMapping, Vector2, Vector3, WebGLRenderer, WebGLRenderTarget } from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { SMAAPass } from "three/addons/postprocessing/SMAAPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import type { SpeechFrame } from "../speech-frame";
import { neutralSpeechFrame } from "../speech-frame";
import type { HumanHeadGeometry } from "./human-head-geometry";
import { HEAD_ATTRIBUTES, sampleHead } from "./test-hologram-particles";
import { createHeadMaterials } from "./test-hologram-materials";
import { HologramSimulation } from "./test-hologram-simulation";
import { createHologramStage } from "./test-hologram-stage";
import { atmosphereView, sculptureEnergy } from "./test-hologram-atmosphere";
import { prepareTestHead } from "./test-hologram-adult-head";
import { headFieldUniforms, loadHeadFields, type HeadFields } from "./test-hologram-fields";
import { HologramRotation } from "./test-hologram-rotation";
import { frameHologram, type PortraitFrame } from "./test-hologram-framing";
import { PORTRAIT_HEAD_OFFSET_Y, PORTRAIT_HEAD_SCALE, WORLD_SCULPTURE_POSITION, WORLD_SCULPTURE_SCALE } from "./test-landscape-layout";

export type HeadView = { yaw: number; pitch: number; zoom: number; landscapeYaw: number; landscapePitch: number; x: number; y: number; influence: number; barrier: number; atmosphereX?: number; atmosphereY?: number; manipulating?: boolean };

/** Owns the complete GPU lifetime. React only owns mounting and input events. */
export class TestHologramEngine {
  private renderer: WebGLRenderer;
  private scene = new Scene();
  private sculpture = new Group();
  private head = new Group();
  private materials = createHeadMaterials();
  private stage?: ReturnType<typeof createHologramStage>;
  private geometries: BufferGeometry[] = [];
  private simulation?: HologramSimulation;
  private fields?: HeadFields;
  private fieldAbort = new AbortController();
  private seedPositions!: Float32Array;
  private particleSide = 176;
  private composer?: EffectComposer;
  private bloom?: UnrealBloomPass;
  private pointer = new Vector3();
  private cameraRight = new Vector3(1, 0, 0);
  private cameraUp = new Vector3(0, 1, 0);
  private viewProjection = new Matrix4();
  private lowPower = false;
  private dpr = 1;
  private quality = 1;
  private width = 0;
  private height = 0;
  private portraitFrame?: PortraitFrame;
  private previousTime = 0;
  private sampleTime = 0;
  private sampleFrames = 0;
  private previousFrameAt = 0;
  private destroyed = false;
  private shaderFailed = false;
  private speechEnergy = 0;
  private rotation = new HologramRotation();

  constructor(private canvas: HTMLCanvasElement, geometry: HumanHeadGeometry, private appearance: "male" | "female") {
    this.renderer = new WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: "high-performance" });
    try {
      const renderer = this.renderer, gl = renderer.getContext();
      if (!gl.getExtension("EXT_color_buffer_float")) throw new Error("Floating point graphics unavailable");
      renderer.debug.onShaderError = () => { this.shaderFailed = true; };
      renderer.setClearColor(0xb5bac3, 1);
      renderer.toneMapping = NeutralToneMapping;
      renderer.toneMappingExposure = 1;
      this.stage = createHologramStage(renderer);
      const debug = gl.getExtension("WEBGL_debug_renderer_info");
      const software = debug && /swiftshader|llvmpipe|software/i.test(String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)));
      this.lowPower = Boolean(software) || canvas.clientWidth < 640 || navigator.hardwareConcurrency <= 4;
      this.quality = software ? .75 : 1;
      const grainBudgetSide = software ? 160 : this.lowPower ? 192 : 256;
      const side = software ? 176 : this.lowPower ? 208 : 280;
      this.particleSide = side;
      // Add material without shrinking the grains the user approved.
      this.materials.uniforms.pointScale.value = .006 * 192 / grainBudgetSide;
      const styledHead = prepareTestHead(geometry, appearance);
      const sampled = sampleHead(styledHead, side * side);
      this.seedPositions = sampled[0];
      const particles = this.geometry(sampled);
      const lookup = new Float32Array(side * side * 2);
      for (let i = 0; i < side * side; i++) { lookup[i * 2] = (i % side + .5) / side; lookup[i * 2 + 1] = (Math.floor(i / side) + .5) / side; }
      particles.setAttribute("lookup", new BufferAttribute(lookup, 2));
      const points = new Points(particles, this.materials.points);
      points.frustumCulled = false;
      // Anatomy is carried by the moving particle volume itself. A solid support
      // mesh would remain visible underneath any patch extracted by the cursor.
      points.renderOrder = 3;
      this.head.add(points);
      this.head.position.y = PORTRAIT_HEAD_OFFSET_Y;
      this.sculpture.position.set(...WORLD_SCULPTURE_POSITION);
      this.sculpture.scale.setScalar(WORLD_SCULPTURE_SCALE);
      this.sculpture.add(this.stage.group, this.head);
      // The platform intersects the original ground and shares its depth buffer.
      // A camera-aligned overlay cannot establish contact with uneven terrain.
      this.scene.add(this.stage.landscape, this.sculpture);
      const target = new WebGLRenderTarget(1, 1, { type: HalfFloatType, depthBuffer: true });
      this.composer = new EffectComposer(renderer, target);
      this.composer.addPass(new RenderPass(this.scene, this.stage.camera));
      this.composer.addPass(this.stage.colorGrade);
      this.bloom = new UnrealBloomPass(new Vector2(1, 1), .36, .65, .85);
      this.composer.addPass(this.bloom);
      this.composer.addPass(new OutputPass());
      if (!this.lowPower) this.composer.addPass(new SMAAPass());
    } catch (error) { this.destroy(true); throw error; }
  }

  private geometry(values: Float32Array[]) {
    const geometry = new BufferGeometry();
    HEAD_ATTRIBUTES.forEach((name, index) => geometry.setAttribute(name, new BufferAttribute(values[index], 3)));
    this.geometries.push(geometry);
    return geometry;
  }

  async prepare() {
    const fields = await loadHeadFields(this.appearance, this.fieldAbort.signal);
    if (this.destroyed) { fields.dispose(); return; }
    this.fields = fields;
    Object.assign(this.materials.uniforms, headFieldUniforms(fields));
    this.simulation = new HologramSimulation(this.renderer, this.seedPositions, this.particleSide, this.lowPower, fields);
    await this.stage?.ready;
    if (this.destroyed) return;
    const target = this.renderer.getRenderTarget();
    try {
      this.renderer.setRenderTarget(this.composer!.readBuffer);
      await this.renderer.compileAsync(this.scene, this.stage!.camera);
      if (this.destroyed) return;
      const view = { yaw: -.18, pitch: .02, zoom: 1, landscapeYaw: 0, landscapePitch: 0, x: 0, y: 0, influence: 0, barrier: 0 };
      // Compile fluid, particle-state, lighting and postprocessing behind the still.
      this.draw(0, view, neutralSpeechFrame(), true, true, 0);
      this.draw(0, view, neutralSpeechFrame(), true, false, 0);
      this.previousTime = 0; this.sampleTime = 0; this.sampleFrames = 0; this.previousFrameAt = 0;
      if (this.shaderFailed) throw new Error("3D shader compilation failed");
    } finally { if (!this.destroyed) this.renderer.setRenderTarget(target); }
  }

  resize(width: number, height: number, frame?: PortraitFrame) {
    const dpr = Math.min(devicePixelRatio || 1, this.lowPower ? 1.15 : 1.5) * this.quality;
    const bufferChanged = width !== this.width || height !== this.height || dpr !== this.dpr;
    this.width = width; this.height = height;
    if (frame) this.portraitFrame = frame;
    this.dpr = dpr;
    // Drawer transitions change portrait bounds, not the full-screen buffer.
    // Three resets canvas dimensions even when setSize receives the same values.
    if (bufferChanged) {
      this.renderer.setPixelRatio(dpr);
      this.renderer.setSize(Math.max(1, width), Math.max(1, height), false);
      this.composer?.setPixelRatio(dpr);
      this.composer?.setSize(Math.max(1, width), Math.max(1, height));
    }
    this.stage?.resize(width, height);
    const portrait = this.portraitFrame ?? { left: 0, top: 0, width, height };
    if (this.stage) {
      // Reframe the entire world when the conversation drawer opens. Terrain,
      // contact shadow and sculpture must always keep the same perspective.
      frameHologram(this.stage.camera, Math.max(1, width), Math.max(1, height), portrait);
    }
  }

  draw(time: number, view: HeadView, speech: SpeechFrame, dark: boolean, motion: boolean, opacity: number, level = 0) {
    if (this.destroyed || !this.simulation || !this.composer || !this.stage || this.width <= 0 || this.height <= 0) return;
    const frameAt = performance.now();
    const frameDuration = this.previousFrameAt ? (frameAt - this.previousFrameAt) / 1000 : 0;
    this.previousFrameAt = motion ? frameAt : 0;
    const dt = this.previousTime ? Math.min(.25, Math.max(0, time - this.previousTime)) : 1 / 60;
    this.previousTime = time;
    const atmosphere = atmosphereView(time, view.atmosphereX ?? 0, view.atmosphereY ?? 0, motion);
    this.stage.lookAround(view.landscapeYaw + atmosphere.yaw, view.landscapePitch + atmosphere.pitch);
    const camera = this.stage.camera;
    this.sculpture.rotation.y = Math.atan2(camera.position.x, camera.position.z);
    const idleYaw = this.rotation.advance(frameDuration, motion && opacity > 0, level > .035 || speech.active, view.manipulating);
    this.head.rotation.set(view.pitch, view.yaw + idleYaw, 0, "YXZ");
    this.head.scale.setScalar(view.zoom * PORTRAIT_HEAD_SCALE);
    this.sculpture.updateMatrixWorld(true);
    this.viewProjection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    this.cameraRight.setFromMatrixColumn(camera.matrixWorld, 0).normalize();
    this.cameraUp.setFromMatrixColumn(camera.matrixWorld, 1).normalize();
    this.pointer.set(view.x, view.y, motion ? view.influence : 0);
    const energy = sculptureEnergy(level, speech.active ? speech.energy : 0, motion);
    // Audio envelopes follow elapsed time, not the capped physics clock. A slow
    // GPU must not stretch a short utterance into seconds of residual glow.
    const energyDt = frameDuration > 0 ? frameDuration : 1 / 60;
    this.speechEnergy = motion ? this.speechEnergy + (energy - this.speechEnergy) * (1 - Math.exp(-energyDt * (energy > this.speechEnergy ? 18 : 7))) : 0;
    this.simulation.update(dt, time, { motion, pointer: this.pointer, modelMatrix: this.head.matrixWorld, enclosureMatrix: this.sculpture.matrixWorld, viewProjection: this.viewProjection, cameraRight: this.cameraRight, cameraUp: this.cameraUp, speechEnergy: this.speechEnergy });
    const u = this.materials.uniforms;
    u.headToEnclosure.value.copy(this.sculpture.matrixWorld).invert().multiply(this.head.matrixWorld);
    u.enclosureToHead.value.copy(u.headToEnclosure.value).invert();
    const speaking = motion && speech.active;
    u.displacement.value = this.simulation.displacement; u.velocity.value = this.simulation.velocity;
    u.articulation.value.set(speaking ? speech.jaw * (1 - speech.closure) : 0, speaking ? speech.round : 0, speaking ? speech.wide : 0, speaking ? speech.fricative : 0);
    u.closure.value = speaking ? speech.closure * .4 : 0;
    const blinkPhase = time % 4.7;
    u.blink.value = motion && blinkPhase < .16 ? Math.sin(blinkPhase / .16 * Math.PI) : 0;
    u.time.value = time; u.motion.value = Number(motion); u.dark.value = 0; u.opacity.value = opacity;
    u.speechEnergy.value = this.speechEnergy;
    u.pixelRatio.value = this.dpr; u.viewportHeight.value = this.height; u.cursor.value.copy(this.pointer);
    this.stage.update(time, view.barrier, dark, opacity, this.speechEnergy);
    if (this.bloom) this.bloom.strength = .24;
    this.composer.render(dt);
    if (this.shaderFailed) throw new Error("3D shader compilation failed");
    // Simulation time is capped for stability. Resolution must instead respond
    // to actual frame intervals, otherwise slow GPUs appear faster than they are.
    if (motion && frameDuration > 0 && frameDuration < 3) this.adaptResolution(frameDuration);
  }

  private adaptResolution(dt: number) {
    this.sampleTime += dt; this.sampleFrames++;
    if (this.sampleTime < 2) return;
    const fps = this.sampleFrames / this.sampleTime;
    const next = Math.max(.65, Math.min(1, this.quality + (fps < 36 ? -.1 : fps > 57 ? .05 : 0)));
    this.sampleTime = 0; this.sampleFrames = 0;
    if (next !== this.quality) { this.quality = next; this.resize(this.width, this.height); }
  }

  suspend() { this.previousFrameAt = 0; }

  resetRotation() { return this.rotation.reset(); }

  destroy(releaseContext = false) {
    if (this.destroyed) return;
    this.destroyed = true;
    this.fieldAbort.abort();
    this.simulation?.dispose();
    this.fields?.dispose();
    this.geometries.forEach((geometry) => geometry.dispose());
    this.materials.points.dispose();
    this.stage?.dispose();
    // r186's bloom dispose omits the high-pass filter material.
    this.bloom?.materialHighPassFilter.dispose();
    this.composer?.passes.forEach((pass) => { if (pass !== this.stage?.colorGrade) pass.dispose(); });
    this.composer?.dispose();
    this.renderer.dispose();
    // Three retains placeholder textures and scratch framebuffers per context.
    // Release them when this canvas is retired, never during a live rebuild.
    if (releaseContext && !this.renderer.getContext().isContextLost()) this.renderer.forceContextLoss();
  }
}
