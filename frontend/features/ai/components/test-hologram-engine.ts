import { BufferAttribute, BufferGeometry, Group, HalfFloatType, LineSegments, Matrix4, Mesh, PerspectiveCamera, Points, Scene, NeutralToneMapping, Vector2, Vector3, WebGLRenderer, WebGLRenderTarget } from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { SMAAPass } from "three/addons/postprocessing/SMAAPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import type { SpeechFrame } from "../speech-frame";
import { neutralSpeechFrame } from "../speech-frame";
import type { HumanHeadGeometry } from "./human-head-geometry";
import { HEAD_ATTRIBUTES, meshAttributes, sampleHead } from "./test-hologram-particles";
import { createHeadMaterials } from "./test-hologram-materials";
import { HologramSimulation } from "./test-hologram-simulation";
import { createHologramStage } from "./test-hologram-stage";

export type HeadView = { yaw: number; pitch: number; zoom: number; landscapeYaw: number; landscapePitch: number; x: number; y: number; influence: number; barrier: number };
type PortraitFrame = { left: number; top: number; width: number; height: number };

/** Owns the complete GPU lifetime. React only owns mounting and input events. */
export class TestHologramEngine {
  private renderer: WebGLRenderer;
  private scene = new Scene();
  private landscapeScene = new Scene();
  private camera = new PerspectiveCamera(37, 1, .1, 120);
  private head = new Group();
  private materials = createHeadMaterials();
  private stage?: ReturnType<typeof createHologramStage>;
  private geometries: BufferGeometry[] = [];
  private simulation?: HologramSimulation;
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

  constructor(private canvas: HTMLCanvasElement, geometry: HumanHeadGeometry) {
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
      const side = software ? 192 : this.lowPower ? 256 : 384;
      this.materials.uniforms.pointScale.value = .0045 * 192 / side;
      const sampled = sampleHead(geometry, side * side);
      this.simulation = new HologramSimulation(renderer, sampled[0], side, this.lowPower);
      const surface = this.geometry(meshAttributes(geometry), geometry.triangles);
      const wire = this.geometry(meshAttributes(geometry), geometry.edges);
      const particles = this.geometry(sampled);
      const lookup = new Float32Array(side * side * 2);
      for (let i = 0; i < side * side; i++) { lookup[i * 2] = (i % side + .5) / side; lookup[i * 2 + 1] = (Math.floor(i / side) + .5) / side; }
      particles.setAttribute("lookup", new BufferAttribute(lookup, 2));
      const points = new Points(particles, this.materials.points);
      points.frustumCulled = false;
      const skin = new Mesh(surface, this.materials.surface), lattice = new LineSegments(wire, this.materials.wire);
      skin.renderOrder = 1; lattice.renderOrder = 2; points.renderOrder = 3;
      this.head.add(skin, lattice, points);
      this.scene.add(this.stage.group, this.head);
      this.landscapeScene.add(this.stage.landscape);
      this.camera.position.set(0, .04, 4.25);
      this.camera.lookAt(0, -.02, 0);
      const target = new WebGLRenderTarget(1, 1, { type: HalfFloatType, depthBuffer: true });
      this.composer = new EffectComposer(renderer, target);
      this.composer.addPass(new RenderPass(this.landscapeScene, this.stage.camera));
      this.composer.addPass(this.stage.colorGrade);
      const portraitPass = new RenderPass(this.scene, this.camera);
      portraitPass.clear = false; portraitPass.clearDepth = true;
      this.composer.addPass(portraitPass);
      this.bloom = new UnrealBloomPass(new Vector2(1, 1), .36, .65, .85);
      this.composer.addPass(this.bloom);
      this.composer.addPass(new OutputPass());
      if (!this.lowPower) this.composer.addPass(new SMAAPass());
    } catch (error) { this.destroy(true); throw error; }
  }

  private geometry(values: Float32Array[], indices?: Uint16Array) {
    const geometry = new BufferGeometry();
    HEAD_ATTRIBUTES.forEach((name, index) => geometry.setAttribute(name, new BufferAttribute(values[index], 3)));
    if (indices) geometry.setIndex(new BufferAttribute(indices, 1));
    this.geometries.push(geometry);
    return geometry;
  }

  async prepare() {
    await this.stage?.ready;
    if (this.destroyed) return;
    const target = this.renderer.getRenderTarget();
    try {
      this.renderer.setRenderTarget(this.composer!.readBuffer);
      await this.renderer.compileAsync(this.landscapeScene, this.stage!.camera);
      if (this.destroyed) return;
      await this.renderer.compileAsync(this.scene, this.camera);
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
    this.width = width; this.height = height;
    if (frame) this.portraitFrame = frame;
    this.dpr = Math.min(devicePixelRatio || 1, this.lowPower ? 1.15 : 1.5) * this.quality;
    this.renderer.setPixelRatio(this.dpr);
    this.renderer.setSize(Math.max(1, width), Math.max(1, height), false);
    this.composer?.setPixelRatio(this.dpr);
    this.composer?.setSize(Math.max(1, width), Math.max(1, height));
    this.stage?.resize(width, height);
    this.camera.aspect = width / Math.max(1, height);
    // The landscape fills the viewport; preserve the face's size and location
    // within its layout slot as the conversation panel and mobile keyboard move.
    const portrait = this.portraitFrame ?? { left: 0, top: 0, width, height };
    const portraitFov = Math.max(37, 37 / Math.min(1, portrait.width / Math.max(1, portrait.height) * 1.22));
    this.camera.fov = 2 * Math.atan(Math.tan(portraitFov * Math.PI / 360) * height / Math.max(1, portrait.height)) * 180 / Math.PI;
    this.camera.updateProjectionMatrix();
    this.camera.projectionMatrix.elements[8] = 1 - (portrait.left + portrait.width / 2) / Math.max(1, width) * 2;
    this.camera.projectionMatrix.elements[9] = (portrait.top + portrait.height / 2) / Math.max(1, height) * 2 - 1;
    this.camera.projectionMatrixInverse.copy(this.camera.projectionMatrix).invert();
  }

  draw(time: number, view: HeadView, speech: SpeechFrame, dark: boolean, motion: boolean, opacity: number) {
    if (this.destroyed || !this.simulation || !this.composer || this.width <= 0 || this.height <= 0) return;
    const frameAt = performance.now();
    const frameDuration = this.previousFrameAt ? (frameAt - this.previousFrameAt) / 1000 : 0;
    this.previousFrameAt = motion ? frameAt : 0;
    const dt = this.previousTime ? Math.min(.05, Math.max(0, time - this.previousTime)) : 1 / 60;
    this.previousTime = time;
    this.head.rotation.set(view.pitch, view.yaw, 0, "YXZ");
    this.head.scale.setScalar(view.zoom);
    this.head.updateMatrixWorld();
    this.camera.updateMatrixWorld();
    this.viewProjection.multiplyMatrices(this.camera.projectionMatrix, this.camera.matrixWorldInverse);
    this.pointer.set(view.x, view.y, motion ? view.influence : 0);
    this.simulation.update(dt, time, { motion, pointer: this.pointer, modelMatrix: this.head.matrixWorld, viewProjection: this.viewProjection, cameraRight: this.cameraRight, cameraUp: this.cameraUp });
    const u = this.materials.uniforms;
    const speaking = motion && speech.active;
    u.displacement.value = this.simulation.displacement; u.velocity.value = this.simulation.velocity;
    u.articulation.value.set(speaking ? speech.jaw * (1 - speech.closure) : 0, speaking ? speech.round : 0, speaking ? speech.wide : 0, speaking ? speech.fricative : 0);
    u.closure.value = speaking ? speech.closure * .4 : 0;
    const blinkPhase = time % 4.7;
    u.blink.value = motion && blinkPhase < .16 ? Math.sin(blinkPhase / .16 * Math.PI) : 0;
    u.time.value = time; u.motion.value = Number(motion); u.dark.value = 0; u.opacity.value = opacity;
    u.pixelRatio.value = this.dpr; u.viewportHeight.value = this.height; u.cursor.value.copy(this.pointer);
    this.stage?.lookAround(view.landscapeYaw, view.landscapePitch);
    this.stage?.update(time, view.barrier, dark, opacity);
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

  destroy(releaseContext = false) {
    if (this.destroyed) return;
    this.destroyed = true;
    this.simulation?.dispose();
    this.geometries.forEach((geometry) => geometry.dispose());
    this.materials.points.dispose(); this.materials.surface.dispose(); this.materials.wire.dispose();
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
