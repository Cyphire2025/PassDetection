import { BackSide, BufferAttribute, BufferGeometry, Color, Group, Mesh, PerspectiveCamera, PlaneGeometry, Points, ShaderMaterial, SphereGeometry, Vector2, Vector4, type WebGLRenderer } from "three";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { createPortraitPlatform } from "./test-hologram-platform";
import { createPedestalGroundContact } from "./test-hologram-ground-contact";
import { createHologramSpill } from "./test-hologram-spill";
import { loadLandscapeAssets } from "./test-landscape-assets";
import { applyLandscapePlacement, FOUNDATION_PLACEMENT, LANDSCAPE_FOV, LANDSCAPE_POSITION, LANDSCAPE_TARGET, landscapeOrbitAround, ORIGINAL_GROUND, ORIGINAL_MOUNTAINS, panoramicPlacements, SNOW_ISLAND, type Placement } from "./test-landscape-layout";
import { FLOOR_FRAGMENT, GRADE_FRAGMENT, LANDSCAPE_VERTEX, SKY_FRAGMENT, SMOKE_FRAGMENT, SNOW_FRAGMENT, SNOW_VERTEX, TERRAIN_FRAGMENT } from "./test-hologram-terrain-shaders";

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
  const platform = createPortraitPlatform(), group = platform.group, landscape = new Group();
  landscape.name = "Original Igloo alpine landscape";
  const camera = new PerspectiveCamera(LANDSCAPE_FOV, 1, .1, 2000);
  // Keep the original ground anchor visible with a wider surrounding panorama.
  camera.position.set(...LANDSCAPE_POSITION); camera.lookAt(...LANDSCAPE_TARGET);
  const lookAround = landscapeOrbitAround(camera);
  const resolution = new Vector2(1, 1), timeUniform = { value: 0 };
  const spill = createHologramSpill();
  const common = { ...spill.uniforms, time: timeUniform, resolution: { value: resolution }, colorLow: { value: new Color("#afb6c7") }, colorHigh: { value: new Color("#d1d6e3") } };
  const geometries: BufferGeometry[] = [], materials: ShaderMaterial[] = [];
  const material = (name: string, fragmentShader: string, uniforms = {}, transparent = false) => {
    const result = new ShaderMaterial({ name, uniforms: { ...common, ...uniforms }, vertexShader: LANDSCAPE_VERTEX, fragmentShader, transparent, toneMapped: false });
    materials.push(result); return result;
  };
  const colorGrade = new ShaderPass(new ShaderMaterial({ name: "Original landscape color lookup", uniforms: { tDiffuse: { value: null }, lut: { value: null }, lutSize: { value: 32 }, resolution: { value: resolution } },
    vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }", fragmentShader: GRADE_FRAGMENT, depthTest: false, depthWrite: false, toneMapped: false }));
  const skyGeometry = new SphereGeometry(800, 12, 12), skyMaterial = material("Alpine overcast gradient", SKY_FRAGMENT, { tWind: { value: null } });
  skyMaterial.side = BackSide; skyMaterial.depthWrite = false;
  const sky = new Mesh(skyGeometry, skyMaterial); sky.name = "Alpine sky"; sky.renderOrder = -10;
  landscape.add(sky); geometries.push(skyGeometry);
  const snowGeometry = snowfallGeometry(), snowMaterial = material("Drifting snow", SNOW_FRAGMENT, { pixelRatio: { value: 1 } }, true);
  snowMaterial.vertexShader = SNOW_VERTEX; snowMaterial.depthWrite = false;
  const snow = new Points(snowGeometry, snowMaterial); snow.name = "Alpine snowfall"; snow.frustumCulled = false; snow.renderOrder = 5;
  snow.position.copy(camera.position);
  landscape.add(snow); geometries.push(snowGeometry);
  const assets = loadLandscapeAssets(renderer);
  let groundContact: ReturnType<typeof createPedestalGroundContact> | undefined;
  let disposed = false;
  const place = (name: string, geometry: BufferGeometry, surface: ShaderMaterial, placements: Placement[]) => placements.forEach((placement, index) => {
    const mesh = new Mesh(geometry, surface); mesh.name = `${name} ${index + 1}`;
    applyLandscapePlacement(mesh, placement); landscape.add(mesh);
  });
  const ready = assets.ready.then((loaded) => {
    if (disposed) return;
    skyMaterial.uniforms.tWind.value = loaded.wind;
    platform.setSnowTexture(loaded.groundMap);
    groundContact = createPedestalGroundContact(loaded.ground, loaded.groundMap, loaded.wind, spill.uniforms); landscape.add(groundContact.mesh);
    const terrain = (name: string, map: typeof loaded.groundMap, mountain: number, edge: Vector2, radiusScale: number, worldSnow = 0) => {
      const uniforms = { tMap: { value: map }, tWind: { value: loaded.wind }, mountain: { value: mountain }, edge: { value: edge }, radiusScale: { value: radiusScale }, worldSnow: { value: worldSnow }, snowIsland: { value: new Vector4(...SNOW_ISLAND) } };
      const core = material(name, TERRAIN_FRAGMENT, { ...uniforms, edgePass: { value: 0 } });
      const feather = material(`${name} feather`, TERRAIN_FRAGMENT, { ...uniforms, edgePass: { value: 1 } }, true);
      // Opaque terrain establishes correct depth first; faded skirts blend later
      // without masking distant peaks/snow with partially transparent depth.
      feather.depthWrite = false;
      return { core, feather };
    };
    const placeTerrain = (name: string, geometry: BufferGeometry, surface: ReturnType<typeof terrain>, placements: Placement[]) => {
      place(name, geometry, surface.core, placements); place(`${name} feather`, geometry, surface.feather, placements);
    };
    const surround = panoramicPlacements();
    const mountainMaterial = terrain("Baked mountain relief", loaded.mountainMap, 1, new Vector2(.7, .9), .1085);
    const groundMaterial = terrain("Baked snow ground", loaded.groundMap, 0, new Vector2(.85, 1), .1085);
    const surroundMaterial = terrain("Blended surrounding snow ground", loaded.groundMap, 0, new Vector2(.45, 1), .1085, 1);
    placeTerrain("Original mountain", loaded.mountain, mountainMaterial, ORIGINAL_MOUNTAINS);
    placeTerrain("Surrounding mountain", loaded.mountain, mountainMaterial, surround.mountains);
    placeTerrain("Original snow ground", loaded.ground, groundMaterial, ORIGINAL_GROUND);
    placeTerrain("Surrounding snow ground", loaded.ground, surroundMaterial, surround.ground);
    const floorMaterial = material("Continuous snowfield", FLOOR_FRAGMENT, { tMap: { value: loaded.groundMap }, tWind: { value: loaded.wind }, snowIsland: { value: new Vector4(...SNOW_ISLAND) } });
    place("Continuous snowfield", loaded.patch, floorMaterial, [FOUNDATION_PLACEMENT]);
    placeTerrain("Snowfield patch", loaded.patch, terrain("Baked snowfield patch", loaded.groundMap, 0, new Vector2(.3, .48), 1), PATCHES);
    const smokeGeometry = new PlaneGeometry(20, 5), smokeMaterial = material("Low drifting mountain haze", SMOKE_FRAGMENT, { tWind: { value: loaded.wind } }, true);
    smokeMaterial.depthWrite = false; geometries.push(smokeGeometry);
    place("Valley haze", smokeGeometry, smokeMaterial, [[[-5, 1.25, -10], [1, 1, 1], [0, 0, 0], 2], [[13.45, 3, -4], [1, 1, 1], [0, -10, 0], 2]]);
    colorGrade.uniforms.lut.value = loaded.grade;
  });
  void ready.catch(() => undefined);
  return {
    group, landscape, camera, colorGrade, ready, lookAround,
    resize(width: number, height: number) {
      camera.aspect = Math.max(1, width) / Math.max(1, height); camera.updateProjectionMatrix();
      resolution.set(Math.max(1, width), Math.max(1, height)).multiplyScalar(renderer.getPixelRatio());
    },
    update(time: number, barrier: number, _dark: boolean, opacity: number, speech = 0) {
      if (disposed) return;
      timeUniform.value = time; snowMaterial.uniforms.pixelRatio.value = renderer.getPixelRatio();
      snow.position.copy(camera.position);
      spill.update(opacity, speech);
      platform.update(time, barrier, opacity, speech);
      groundContact?.update(opacity, time);
    },
    dispose() {
      if (disposed) return;
      disposed = true; platform.dispose(); groundContact?.dispose(); landscape.removeFromParent(); landscape.clear();
      assets.dispose(); colorGrade.dispose();
      geometries.forEach((geometry) => geometry.dispose()); materials.forEach((surface) => surface.dispose());
    },
  };
}
