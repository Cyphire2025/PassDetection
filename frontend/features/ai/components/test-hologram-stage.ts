import { BackSide, BufferAttribute, BufferGeometry, Color, Group, LineSegments, Mesh, PerspectiveCamera, PlaneGeometry, Points, ShaderMaterial, SphereGeometry, Vector2, type WebGLRenderer } from "three";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { containmentLines } from "./test-hologram-particles";
import { loadLandscapeAssets } from "./test-landscape-assets";
import { ENCLOSURE_FRAGMENT, GRADE_FRAGMENT, LANDSCAPE_VERTEX, SKY_FRAGMENT, SMOKE_FRAGMENT, SNOW_FRAGMENT, SNOW_VERTEX, TERRAIN_FRAGMENT } from "./test-hologram-terrain-shaders";

type Placement = [position: number[], scale: number[], degrees: number[], order?: number];
const MOUNTAINS: Placement[] = [
  [[59.53, -1, -11.84], [4, 3.14, 4], [4.1, -42.8, 5]],
  [[1, -2.21, -23], [2, 2, 2], [3.5, 30, 0]],
  [[75, 0, -90], [8, 8, 8], [3.2, -16.7, -2.6]],
  [[250, 11.33, -133], [10, 10, 10], [13.2, 20, 5]],
  [[-25.22, -1.59, -53.05], [2.5, 2.5, 2.5], [3.5, 25, 0]],
];
const GROUND: Placement[] = [
  [[0, 0, 0], [1, 1, 1], [0, 0, 0], 2],
  [[-3.76, -.58, 12.5], [.6, .6, .6], [-5.1, 0, 0]],
  [[-17.63, -.01, 2], [1, 1, 1], [2.7, .8, 0], 3],
  [[3.12, -.75, -1.02], [1.5, .66, 1.5], [0, 0, 0]],
  [[6, .16, 15.78], [1, 1, 1], [1.1, 0, 7], 2],
  [[16.06, .34, 4], [1, 1, 1], [0, 0, 0], 2],
];
const PATCHES: Placement[] = [
  [[-9.34, -1.77, 6.96], [7, 7, 7], [0, 0, 0], 0],
  [[-8.82, -1.35, 11.69], [8, 8, 8], [-5.5, -25.6, 0], 0],
];

function snowfallGeometry() {
  const points = new Float32Array(1200 * 3), seeds = new Float32Array(1200);
  let seed = 4181;
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  for (let i = 0; i < seeds.length; i++) {
    points[i * 3] = random() * 50 - 25; points[i * 3 + 1] = random() * 20 - 10;
    points[i * 3 + 2] = random() * 50 - 25; seeds[i] = random();
  }
  return new BufferGeometry().setAttribute("position", new BufferAttribute(points, 3)).setAttribute("seed", new BufferAttribute(seeds, 1));
}

/** Original integration of the provenance-recorded Igloo terrain assets. */
export function createHologramStage(renderer: WebGLRenderer) {
  const group = new Group(), landscape = new Group();
  group.name = "Head interaction enclosure"; landscape.name = "Original Igloo alpine landscape";
  const camera = new PerspectiveCamera(30, 1, .1, 2000);
  // Preserve the terrain perspective while keeping its summit silhouettes
  // inside the viewport above the assistant and header.
  camera.position.set(-14, 4, 14); camera.lookAt(0, 2.5, 0);
  const resolution = new Vector2(1, 1), timeUniform = { value: 0 };
  const common = { time: timeUniform, resolution: { value: resolution }, colorLow: { value: new Color("#afb6c7") }, colorHigh: { value: new Color("#d1d6e3") } };
  const geometries: BufferGeometry[] = [], materials: ShaderMaterial[] = [];
  const material = (name: string, fragmentShader: string, uniforms = {}, transparent = false) => {
    const result = new ShaderMaterial({ name, uniforms: { ...common, ...uniforms }, vertexShader: LANDSCAPE_VERTEX, fragmentShader, transparent, toneMapped: false });
    materials.push(result); return result;
  };
  const colorGrade = new ShaderPass(new ShaderMaterial({ name: "Original landscape color lookup", uniforms: { tDiffuse: { value: null }, lut: { value: null }, lutSize: { value: 32 } },
    vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }", fragmentShader: GRADE_FRAGMENT, depthTest: false, depthWrite: false, toneMapped: false }));
  const skyGeometry = new SphereGeometry(800, 12, 12), skyMaterial = material("Alpine overcast gradient", SKY_FRAGMENT);
  skyMaterial.side = BackSide; skyMaterial.depthWrite = false;
  const sky = new Mesh(skyGeometry, skyMaterial); sky.name = "Alpine sky"; sky.renderOrder = -10;
  landscape.add(sky); geometries.push(skyGeometry);
  const cageGeometry = new BufferGeometry().setAttribute("position", new BufferAttribute(containmentLines(), 3));
  const cageMaterial = material("Interaction enclosure", ENCLOSURE_FRAGMENT, { strength: { value: 0 } }, true);
  cageMaterial.depthWrite = false;
  const cage = new LineSegments(cageGeometry, cageMaterial); cage.name = "Interaction enclosure"; cage.visible = false;
  group.add(cage); geometries.push(cageGeometry);
  const snowGeometry = snowfallGeometry(), snowMaterial = material("Drifting snow", SNOW_FRAGMENT, { pixelRatio: { value: 1 } }, true);
  snowMaterial.vertexShader = SNOW_VERTEX; snowMaterial.depthWrite = false;
  const snow = new Points(snowGeometry, snowMaterial); snow.name = "Alpine snowfall"; snow.frustumCulled = false; snow.renderOrder = 5;
  landscape.add(snow); geometries.push(snowGeometry);
  const assets = loadLandscapeAssets(renderer);
  let disposed = false;
  const place = (name: string, geometry: BufferGeometry, surface: ShaderMaterial, placements: Placement[]) => placements.forEach(([position, scale, degrees, order = 1], index) => {
    const mesh = new Mesh(geometry, surface); mesh.name = `${name} ${index + 1}`;
    mesh.position.fromArray(position); mesh.scale.fromArray(scale);
    mesh.rotation.set(...degrees.map((value) => value * 3.14 / 180) as [number, number, number]);
    mesh.renderOrder = order; mesh.updateMatrixWorld(); mesh.matrixAutoUpdate = false; landscape.add(mesh);
  });
  const ready = assets.ready.then((loaded) => {
    if (disposed) return;
    const terrain = (name: string, map: typeof loaded.groundMap, mountain: number, edge: Vector2, radiusScale: number) => material(name, TERRAIN_FRAGMENT,
      { tMap: { value: map }, tWind: { value: loaded.wind }, mountain: { value: mountain }, edge: { value: edge }, radiusScale: { value: radiusScale } }, true);
    place("Original mountain", loaded.mountain, terrain("Baked mountain relief", loaded.mountainMap, 1, new Vector2(.7, .9), .1085), MOUNTAINS);
    place("Original snow ground", loaded.ground, terrain("Baked snow ground", loaded.groundMap, 0, new Vector2(.85, 1), .1085), GROUND);
    place("Snowfield patch", loaded.patch, terrain("Baked snowfield patch", loaded.groundMap, 0, new Vector2(.3, .48), 1), PATCHES);
    const smokeGeometry = new PlaneGeometry(20, 5), smokeMaterial = material("Low drifting mountain haze", SMOKE_FRAGMENT, { tWind: { value: loaded.wind } }, true);
    smokeMaterial.depthWrite = false; geometries.push(smokeGeometry);
    place("Valley haze", smokeGeometry, smokeMaterial, [[[-5, 1.25, -10], [1, 1, 1], [0, 0, 0], 2], [[13.45, 3, -4], [1, 1, 1], [0, -10, 0], 2]]);
    colorGrade.uniforms.lut.value = loaded.grade;
  });
  void ready.catch(() => undefined);
  return {
    group, landscape, camera, colorGrade, ready,
    resize(width: number, height: number) {
      camera.aspect = Math.max(1, width) / Math.max(1, height); camera.updateProjectionMatrix();
      resolution.set(Math.max(1, width), Math.max(1, height)).multiplyScalar(renderer.getPixelRatio());
    },
    update(time: number, barrier: number, _dark: boolean, opacity: number) {
      if (disposed) return;
      const interaction = Math.max(0, Math.min(1, barrier));
      timeUniform.value = time; snowMaterial.uniforms.pixelRatio.value = renderer.getPixelRatio();
      cage.visible = interaction > .005 && opacity > .002;
      cage.rotation.set(Math.sin(time * .12) * .025, time * .045, Math.sin(time * .09) * .018);
      cageMaterial.uniforms.strength.value = interaction * .10 * Math.max(0, Math.min(1, opacity));
    },
    dispose() {
      if (disposed) return;
      disposed = true; group.removeFromParent(); group.clear(); landscape.removeFromParent(); landscape.clear();
      assets.dispose(); colorGrade.dispose();
      geometries.forEach((geometry) => geometry.dispose()); materials.forEach((surface) => surface.dispose());
    },
  };
}
