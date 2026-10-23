import { BufferAttribute, BufferGeometry, Group, HalfFloatType, UnsignedByteType, Matrix4, Points, Scene, NeutralToneMapping, Vector2, Vector3, WebGLRenderer, WebGLRenderTarget } from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { SMAAPass } from "three/addons/postprocessing/SMAAPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import type { SpeechFrame } from "../speech-frame";
import { neutralSpeechFrame } from "../speech-frame";
import { PARTICLE_ATTRIBUTES } from "./test-hologram-packed";
import { createHeadMaterials } from "./test-hologram-materials";
import { conversationMotion, HologramInteraction } from "./test-hologram-interaction";
import { createHologramStage } from "./test-hologram-stage";
import { atmosphereView, sculptureEnergy } from "./test-hologram-atmosphere";
import { HologramRotation } from "./test-hologram-rotation";
import { frameHologram, type PortraitFrame } from "./test-hologram-framing";
import { PORTRAIT_HEAD_OFFSET_Y, PORTRAIT_HEAD_SCALE, WORLD_SCULPTURE_POSITION, WORLD_SCULPTURE_SCALE } from "./test-landscape-layout";

export type HeadView = { yaw: number; pitch: number; zoom: number; landscapeYaw: number; landscapePitch: number; x: number; y: number; influence: number; barrier: number; atmosphereX?: number; atmosphereY?: number; manipulating?: boolean; listening?: boolean; responding?: boolean };

/** Owns the complete GPU lifetime. React only owns mounting and input events. */
export class TestHologramEngine {
  private renderer: WebGLRenderer;
  private scene = new Scene();
  private sculpture = new Group();
  private head = new Group();
  private interaction = new HologramInteraction();
  private materials = createHeadMaterials(this.interaction);
  private stage?: ReturnType<typeof createHologramStage>;
  private geometries: BufferGeometry[] = [];
  private particleGeometry?: BufferGeometry;
  private particleBudget = 43264;
  private composer?: EffectComposer;
  private bloom?: UnrealBloomPass;
  private pointer = new Vector3();
  private cameraRight = new Vector3(1, 0, 0);
  private cameraUp = new Vector3(0, 1, 0);
  private inverseHead = new Matrix4();
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

  constructor(private canvas: HTMLCanvasElement, sampled: Float32Array[]) {
    this.renderer = new WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: "high-performance" });
    try {
      const renderer = this.renderer, gl = renderer.getContext();
      renderer.debug.onShaderError = () => { this.shaderFailed = true; };
      renderer.setClearColor(0xb5bac3, 1);
      renderer.toneMapping = NeutralToneMapping;
      renderer.toneMappingExposure = 1;
      this.stage = createHologramStage(renderer, true);
      const debug = gl.getExtension("WEBGL_debug_renderer_info");
      const software = debug && /swiftshader|llvmpipe|software/i.test(String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)));
      this.lowPower = Boolean(software) || canvas.clientWidth < 640 || navigator.hardwareConcurrency <= 4;
      this.quality = software ? .75 : 1;
      this.particleBudget = software ? 25600 : this.lowPower ? 30976 : 43264;
      this.materials.uniforms.pointScale.value = .0064 * 208 / Math.sqrt(this.particleBudget);
      const particles = this.geometry(sampled);
      this.particleGeometry = particles;
      particles.setDrawRange(0, this.particleBudget);
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
      const hdr = Boolean(gl.getExtension("EXT_color_buffer_float"));
      const target = new WebGLRenderTarget(1, 1, { type: hdr ? HalfFloatType : UnsignedByteType, depthBuffer: true });
      this.composer = new EffectComposer(renderer, target);
      this.composer.addPass(new RenderPass(this.scene, this.stage.camera));
      this.composer.addPass(this.stage.colorGrade);
      if (hdr) {
        this.bloom = new UnrealBloomPass(new Vector2(1, 1), .36, .65, .85);
        this.composer.addPass(this.bloom);
      }
      this.composer.addPass(new OutputPass());
      if (!this.lowPower) this.composer.addPass(new SMAAPass());
    } catch (error) { this.destroy(true); throw error; }
  }

  private geometry(values: Float32Array[]) {
    const geometry = new BufferGeometry();
    PARTICLE_ATTRIBUTES.forEach((name, index) => geometry.setAttribute(name, new BufferAttribute(values[index], 3)));
    this.geometries.push(geometry);
    return geometry;
  }

  async prepare() {
    await this.stage?.ready;
    if (this.destroyed) return;
    const target = this.renderer.getRenderTarget();
    try {
      this.renderer.setRenderTarget(this.composer!.readBuffer);
      await this.renderer.compileAsync(this.scene, this.stage!.camera);
      if (this.destroyed) return;
      const view = { yaw: -.18, pitch: .02, zoom: 1, landscapeYaw: 0, landscapePitch: 0, x: 0, y: 0, influence: 0, barrier: 0 };
      // The first presented scene is complete; no additional entrance delay.
      this.draw(0, view, neutralSpeechFrame(), true, false, 1);
      this.previousTime = 0; this.sampleTime = 0; this.sampleFrames = 0; this.previousFrameAt = 0;
      if (this.shaderFailed) throw new Error("3D shader compilation failed");
    } finally { if (!this.destroyed) this.renderer.setRenderTarget(target); }
  }

  resize(width: number, height: number, frame?: PortraitFrame) {
    const pixelBudget = this.lowPower ? 1_000_000 : 2_000_000;
    const dpr = Math.min(devicePixelRatio || 1, this.lowPower ? 1.15 : 1.5, Math.sqrt(pixelBudget / Math.max(1, width * height))) * this.quality;
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
    if (this.destroyed || !this.composer || !this.stage || this.width <= 0 || this.height <= 0) return;
    const frameAt = performance.now();
    const frameDuration = this.previousFrameAt ? (frameAt - this.previousFrameAt) / 1000 : 0;
    this.previousFrameAt = motion ? frameAt : 0;
    const dt = this.previousTime ? Math.min(.25, Math.max(0, time - this.previousTime)) : 1 / 60;
    this.previousTime = time;
    const atmosphere = atmosphereView(time, view.atmosphereX ?? 0, view.atmosphereY ?? 0, motion);
    this.stage.lookAround(view.landscapeYaw + atmosphere.yaw, view.landscapePitch + atmosphere.pitch);
    const camera = this.stage.camera;
    this.sculpture.rotation.y = Math.atan2(camera.position.x, camera.position.z);
    const voice = conversationMotion(Boolean(view.listening), Boolean(view.responding), level, speech.active);
    const idleYaw = this.rotation.advance(frameDuration, motion && opacity > 0, voice.holdRotation, view.manipulating);
    this.head.rotation.set(view.pitch, view.yaw + idleYaw, 0, "YXZ");
    this.head.scale.setScalar(view.zoom * PORTRAIT_HEAD_SCALE);
    this.sculpture.updateMatrixWorld(true);
    this.inverseHead.copy(this.head.matrixWorld).invert();
    this.cameraRight.setFromMatrixColumn(camera.matrixWorld, 0).transformDirection(this.inverseHead);
    this.cameraUp.setFromMatrixColumn(camera.matrixWorld, 1).transformDirection(this.inverseHead);
    this.pointer.set(view.x, view.y, motion ? view.influence : 0);
    const energy = sculptureEnergy(level, speech.active ? speech.energy : 0, motion);
    // Audio envelopes follow elapsed time, not the capped physics clock. A slow
    // GPU must not stretch a short utterance into seconds of residual glow.
    const energyDt = frameDuration > 0 ? frameDuration : 1 / 60;
    this.speechEnergy = motion ? this.speechEnergy + (energy - this.speechEnergy) * (1 - Math.exp(-energyDt * (energy > this.speechEnergy ? 18 : 7))) : 0;
    if (motion) this.interaction.update(view.x, view.y, view.influence > .01, time);
    else this.interaction.reset();
    const u = this.materials.uniforms;
    u.headToEnclosure.value.copy(this.sculpture.matrixWorld).invert().multiply(this.head.matrixWorld);
    u.enclosureToHead.value.copy(u.headToEnclosure.value).invert();
    const speaking = motion && speech.active;
    u.pointerRight.value.copy(this.cameraRight); u.pointerUp.value.copy(this.cameraUp);
    u.ambientMotion.value = voice.ambient;
    u.responseGlow.value = motion ? u.responseGlow.value + (voice.response - u.responseGlow.value) * (1 - Math.exp(-energyDt * 12)) : voice.response;
    u.articulation.value.set(speaking ? speech.jaw * (1 - speech.closure) : 0, speaking ? speech.round : 0, speaking ? speech.wide : 0, speaking ? speech.fricative : 0);
    u.closure.value = speaking ? speech.closure * .4 : 0;
    const blinkPhase = time % 4.7;
    u.blink.value = motion && blinkPhase < .16 ? Math.sin(blinkPhase / .16 * Math.PI) : 0;
    u.time.value = time; u.motion.value = Number(motion); u.dark.value = 0; u.opacity.value = opacity;
    u.speechEnergy.value = this.speechEnergy;
    u.pixelRatio.value = this.dpr; u.viewportHeight.value = this.height; u.cursor.value.copy(this.pointer);
    this.stage.update(time, view.barrier, dark, opacity, this.speechEnergy);
    if (this.bloom) this.bloom.strength = .28 + u.responseGlow.value * .10;
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
    if (next !== this.quality) {
      this.quality = next; this.resize(this.width, this.height);
      this.particleGeometry?.setDrawRange(0, Math.floor(this.particleBudget * Math.max(.7, next)));
    }
  }

  suspend() { this.previousFrameAt = 0; this.previousTime = 0; this.interaction.reset(); }

  resetRotation() { return this.rotation.reset(); }

  destroy(releaseContext = false) {
    if (this.destroyed) return;
    this.destroyed = true;
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
