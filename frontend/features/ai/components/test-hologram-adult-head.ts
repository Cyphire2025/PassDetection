import { BufferAttribute, BufferGeometry } from "three";
import { HEAD_MORPHS, type HumanHeadGeometry } from "./human-head-geometry";
import { styleHeadHair } from "./test-hologram-hair";

type Appearance = "female" | "male";
const smooth = (low: number, high: number, value: number) => {
  const t = Math.max(0, Math.min(1, (value - low) / (high - low)));
  return t * t * (3 - 2 * t);
};

/** Gentle adult proportions; the orbital region and visible lip seam stay fixed. */
function shape(x: number, y: number, z: number, appearance: Appearance): [number, number, number] {
  const front = smooth(-.10, .25, z), lower = 1 - smooth(-.18, .02, y);
  const neck = smooth(-.92, -.72, y);
  const mouth = (1 - smooth(.19, .29, Math.abs(x))) * (1 - smooth(.09, .17, Math.abs(y + .39))) * smooth(.30, .48, z);
  const weight = front * lower * neck * (1 - mouth);
  const cheek = Math.exp(-(((Math.abs(x) - .30) / .16) ** 2 + ((y + .12) / .23) ** 2)) * weight;
  return [x * (1 - .025 * cheek), y - .04 * Math.max(0, .1722 - y) * weight,
    z - (appearance === "female" ? .012 : .009) * cheek];
}

/** Transform rest and each authored pose together, retaining their vertex mapping. */
export function refineAdultHead(source: HumanHeadGeometry, appearance: Appearance): HumanHeadGeometry {
  const positions = new Float32Array(source.positions.length);
  const morphs = Object.fromEntries(HEAD_MORPHS.map((key) => [key, new Float32Array(positions.length)])) as HumanHeadGeometry["morphs"];
  for (let offset = 0; offset < positions.length; offset += 3) {
    const x = source.positions[offset], y = source.positions[offset + 1], z = source.positions[offset + 2];
    const rest = shape(x, y, z, appearance); positions.set(rest, offset);
    for (const key of HEAD_MORPHS) {
      const delta = source.morphs[key], posed = shape(x + delta[offset], y + delta[offset + 1], z + delta[offset + 2], appearance);
      for (let axis = 0; axis < 3; axis++) morphs[key][offset + axis] = posed[axis] - rest[axis];
    }
  }
  const geometry = new BufferGeometry().setAttribute("position", new BufferAttribute(positions, 3));
  geometry.setIndex(new BufferAttribute(source.triangles, 1)); geometry.computeVertexNormals();
  const normals = Float32Array.from(geometry.getAttribute("normal").array); geometry.dispose();
  return { positions, normals, morphs, triangles: source.triangles, edges: source.edges };
}

/** The renderer and offline volume bake must use this identical preparation path. */
export function prepareTestHead(mesh: HumanHeadGeometry, appearance: Appearance) {
  return styleHeadHair(refineAdultHead(mesh, appearance), appearance);
}
