import { Matrix4, NormalBlending, ShaderMaterial, Vector3, Vector4, type IUniform, type Texture } from "three";
import { HEAD_FRAGMENT, HEAD_VERTEX } from "./test-hologram-shaders";

export type HeadUniforms = {
  displacement: IUniform<Texture | null>;
  velocity: IUniform<Texture | null>;
  articulation: IUniform<Vector4>;
  headToEnclosure: IUniform<Matrix4>; enclosureToHead: IUniform<Matrix4>;
  cursor: IUniform<Vector3>;
  closure: IUniform<number>; blink: IUniform<number>; time: IUniform<number>;
  motion: IUniform<number>; dark: IUniform<number>; opacity: IUniform<number>; speechEnergy: IUniform<number>;
  pixelRatio: IUniform<number>; viewportHeight: IUniform<number>; pointScale: IUniform<number>;
};

/** All visible anatomy, articulation and lighting belongs to the particle volume. */
export function createHeadMaterials() {
  const uniforms: HeadUniforms = {
    displacement: { value: null }, velocity: { value: null },
    articulation: { value: new Vector4() }, cursor: { value: new Vector3() },
    headToEnclosure: { value: new Matrix4() }, enclosureToHead: { value: new Matrix4() },
    closure: { value: 0 }, blink: { value: 0 }, time: { value: 0 }, motion: { value: 1 },
    dark: { value: 1 }, opacity: { value: 1 }, speechEnergy: { value: 0 }, pixelRatio: { value: 1 },
    viewportHeight: { value: 600 }, pointScale: { value: .006 },
  };
  const common = { uniforms, vertexShader: HEAD_VERTEX, transparent: true,
    depthTest: true, blending: NormalBlending, toneMapped: true };
  const points = new ShaderMaterial({ ...common, name: "Human particle spheres",
    fragmentShader: HEAD_FRAGMENT, depthWrite: true });
  return { points, uniforms };
}
