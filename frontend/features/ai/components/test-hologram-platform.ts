import { BufferAttribute, BufferGeometry, CylinderGeometry, Group, LineSegments, Mesh, Points, ShaderMaterial, Vector2, Vector4, WireframeGeometry, type Texture } from "three";
import { PLATFORM_HORIZONTAL_SCALE, SNOW_ISLAND, WORLD_SCULPTURE_SCALE } from "./test-landscape-layout";
import { BAND_FRAGMENT, CYLINDER_FRAGMENT, CYLINDER_VERTEX, PLATFORM_VERTEX, STONE_FRAGMENT } from "./test-hologram-platform-shaders";
import { createHologramProjector } from "./test-hologram-projector";
import { pedestalDiscGeometry } from "./test-hologram-stone-geometry";
export { pedestalDiscGeometry } from "./test-hologram-stone-geometry";

export const CONTAINMENT = { radius: .84, bottom: -1.10, top: 1.08 } as const;
export const PEDESTAL = [
  { radius: 1.12, height: .055, y: -1.2125 },
  { radius: .90, height: .060, y: -1.13 },
] as const;
export const PEDESTAL_BAND = { radius: .885, height: .025, y: -1.1725 } as const;

/** Fine irregular cells share vertices across a closed, short-edge cylinder. */
export function containmentCylinderGeometry() {
  const columns = 80, rows = 44, capRings = 10, positions: number[] = [], indices: number[] = [];
  let seed = 41821;
  const jitter = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return (seed / 4294967296 - .5) * .48; };
  for (let row = 0; row <= rows; row++) for (let column = 0; column < columns; column++) {
    const angle = (column + (row % 2) * .5 + jitter()) / columns * Math.PI * 2;
    const height = (row + (row > 0 && row < rows ? jitter() : 0)) / rows;
    positions.push(Math.sin(angle) * CONTAINMENT.radius, CONTAINMENT.bottom + height * (CONTAINMENT.top - CONTAINMENT.bottom), Math.cos(angle) * CONTAINMENT.radius);
  }
  const squaredDistance = (a: number, b: number) => (positions[a * 3] - positions[b * 3]) ** 2 + (positions[a * 3 + 1] - positions[b * 3 + 1]) ** 2 + (positions[a * 3 + 2] - positions[b * 3 + 2]) ** 2;
  for (let row = 0; row < rows; row++) for (let column = 0; column < columns; column++) {
    const a = row * columns + column, b = row * columns + (column + 1) % columns;
    const c = (row + 1) * columns + column, d = (row + 1) * columns + (column + 1) % columns;
    if (squaredDistance(a, d) < squaredDistance(b, c)) indices.push(a, b, d, a, d, c);
    else indices.push(a, b, c, b, d, c);
  }
  for (const top of [false, true]) {
    const y = top ? CONTAINMENT.top : CONTAINMENT.bottom;
    let outer = top ? rows * columns : 0;
    const triangle = (a: number, b: number, c: number) => { if (top) indices.push(a, b, c); else indices.push(a, c, b); };
    // Keep cap edges comparable to side cells instead of drawing full-radius
    // fan spokes. Reuse each boundary ring, preserving watertight topology.
    for (let ring = 1; ring < capRings; ring++) {
      const inner = positions.length / 3;
      for (let column = 0; column < columns; column++) {
        const angle = (column + jitter()) / columns * Math.PI * 2;
        const radius = CONTAINMENT.radius * (1 - (ring + jitter() * .45) / capRings);
        positions.push(Math.sin(angle) * radius, y, Math.cos(angle) * radius);
      }
      for (let column = 0; column < columns; column++) {
        const next = (column + 1) % columns;
        triangle(outer + column, outer + next, inner + column);
        triangle(outer + next, inner + next, inner + column);
      }
      outer = inner;
    }
    const center = positions.length / 3; positions.push(0, y, 0);
    for (let column = 0; column < columns; column++) triangle(center, outer + column, outer + (column + 1) % columns);
  }
  const geometry = new BufferGeometry().setAttribute("position", new BufferAttribute(new Float32Array(positions), 3));
  geometry.setIndex(indices); geometry.computeBoundingSphere(); return geometry;
}

function containmentRimsGeometry() {
  const positions: number[] = [];
  for (const y of [CONTAINMENT.bottom, CONTAINMENT.top]) for (let index = 0; index < 128; index++) {
    for (const step of [index, index + 1]) {
      const angle = step / 128 * Math.PI * 2;
      positions.push(Math.sin(angle) * CONTAINMENT.radius, y, Math.cos(angle) * CONTAINMENT.radius);
    }
  }
  return new BufferGeometry().setAttribute("position", new BufferAttribute(new Float32Array(positions), 3));
}

const unit = (value: number) => Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;

/** Stone, projector and cage share the world anchor while the head turns within. */
export function createPortraitPlatform() {
  const group = new Group(); group.name = "Portrait pedestal and cylindrical enclosure";
  group.scale.set(PLATFORM_HORIZONTAL_SCALE, 1, PLATFORM_HORIZONTAL_SCALE);
  const opacity = { value: 0 }, time = { value: 0 }, strength = { value: 0 };
  const material = (name: string, fragmentShader: string, depthWrite = false) => new ShaderMaterial({ name, vertexShader: PLATFORM_VERTEX, fragmentShader, uniforms: { opacity }, transparent: true, depthWrite, toneMapped: false });
  const stone = material("Frosted layered stone", STONE_FRAGMENT, true), bandMaterial = material("Recessed icy pedestal band", BAND_FRAGMENT, true);
  Object.assign(stone.uniforms, { tSnow: { value: null }, hasSnow: { value: 0 }, snowIsland: { value: new Vector4(...SNOW_ISLAND) }, snowSpan: { value: 2.3 * WORLD_SCULPTURE_SCALE } });
  const discGeometry = pedestalDiscGeometry(), baseGeometry = pedestalDiscGeometry(true);
  const bandGeometry = new CylinderGeometry(PEDESTAL_BAND.radius, PEDESTAL_BAND.radius, PEDESTAL_BAND.height, 96, 1, true);
  PEDESTAL.forEach((tier, index) => {
    const disc = new Mesh(index === 0 ? baseGeometry : discGeometry, stone); disc.name = `Stone pedestal tier ${index + 1}`;
    disc.position.y = tier.y; disc.scale.set(tier.radius, tier.height, tier.radius); group.add(disc);
  });
  const band = new Mesh(bandGeometry, bandMaterial); band.name = "Pedestal recessed glow band";
  band.position.y = PEDESTAL_BAND.y; group.add(band);
  const closed = containmentCylinderGeometry(), wire = new WireframeGeometry(closed);
  const nodeGeometry = new BufferGeometry().setAttribute("position", closed.getAttribute("position").clone()); closed.dispose();
  const rimGeometry = containmentRimsGeometry();
  const enclosure = new ShaderMaterial({ name: "Cylindrical interaction scan", vertexShader: CYLINDER_VERTEX, fragmentShader: CYLINDER_FRAGMENT, uniforms: { time, strength, heightBounds: { value: new Vector2(CONTAINMENT.bottom, CONTAINMENT.top) } }, transparent: true, depthWrite: false, toneMapped: false });
  const nodeMaterial = enclosure.clone(); nodeMaterial.name = "Cylindrical lattice nodes"; nodeMaterial.defines = { CYLINDER_NODES: 1 }; nodeMaterial.uniforms = enclosure.uniforms;
  const cage = new LineSegments(wire, enclosure); cage.name = "Cylindrical interaction enclosure";
  const nodes = new Points(nodeGeometry, nodeMaterial); nodes.name = "Cylindrical lattice nodes";
  const rims = new LineSegments(rimGeometry, enclosure); rims.name = "Cylindrical circular rims";
  const enclosureObjects = [cage, nodes, rims];
  for (const object of enclosureObjects) { object.renderOrder = 4; group.add(object); }
  const projector = createHologramProjector(); group.add(projector.group);
  const geometries = [discGeometry, baseGeometry, bandGeometry, wire, nodeGeometry, rimGeometry], materials = [stone, bandMaterial, enclosure, nodeMaterial];
  let disposed = false;
  return {
    group,
    setSnowTexture(texture: Texture) {
      if (disposed) return;
      // Borrow the already-loaded atlas. Its loader remains its sole owner.
      stone.uniforms.tSnow.value = texture; stone.uniforms.hasSnow.value = 1;
    },
    update(elapsed: number, interaction: number, entrance: number, speech = 0) {
      if (disposed) return;
      opacity.value = unit(entrance); group.visible = opacity.value > .002;
      time.value = Number.isFinite(elapsed) ? elapsed : 0;
      const energy = Math.max(unit(interaction), unit(speech) * .8);
      strength.value = (.18 + energy * .30) * opacity.value;
      for (const object of enclosureObjects) object.visible = opacity.value > .002;
      projector.update(time.value, opacity.value, energy);
    },
    dispose() {
      if (disposed) return;
      disposed = true; projector.dispose(); group.removeFromParent(); group.clear();
      geometries.forEach((geometry) => geometry.dispose()); materials.forEach((surface) => surface.dispose());
    },
  };
}
