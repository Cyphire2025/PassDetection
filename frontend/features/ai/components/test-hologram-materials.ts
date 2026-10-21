import { FrontSide, NormalBlending, ShaderMaterial, Vector3, Vector4, type IUniform, type Texture } from "three";
import { HEAD_FRAGMENT, HEAD_VERTEX, SURFACE_FRAGMENT, WIRE_FRAGMENT } from "./test-hologram-shaders";

export type HeadUniforms = {
  displacement: IUniform<Texture | null>;
  velocity: IUniform<Texture | null>;
  articulation: IUniform<Vector4>;
  cursor: IUniform<Vector3>;
  closure: IUniform<number>; blink: IUniform<number>; time: IUniform<number>;
  motion: IUniform<number>; dark: IUniform<number>; opacity: IUniform<number>;
  pixelRatio: IUniform<number>; viewportHeight: IUniform<number>; pointScale: IUniform<number>;
};

/** One shared articulation/lighting state keeps mesh, authored edges and particles aligned. */
export function createHeadMaterials() {
  const uniforms: HeadUniforms = {
    displacement: { value: null }, velocity: { value: null },
    articulation: { value: new Vector4() }, cursor: { value: new Vector3() },
    closure: { value: 0 }, blink: { value: 0 }, time: { value: 0 }, motion: { value: 1 },
    dark: { value: 1 }, opacity: { value: 1 }, pixelRatio: { value: 1 },
    viewportHeight: { value: 600 }, pointScale: { value: .0045 },
  };
  const common = { uniforms, vertexShader: HEAD_VERTEX, transparent: true,
    depthTest: true, blending: NormalBlending, toneMapped: true };
  const points = new ShaderMaterial({ ...common, name: "Human particle spheres",
    defines: { PARTICLE_DYNAMICS: 1 }, fragmentShader: HEAD_FRAGMENT, depthWrite: false });
  const surface = new ShaderMaterial({ ...common, name: "Human translucent depth surface",
    fragmentShader: SURFACE_FRAGMENT, depthWrite: true, side: FrontSide,
    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
  const wire = new ShaderMaterial({ ...common, name: "Human authored edge light",
    fragmentShader: WIRE_FRAGMENT, depthWrite: false });
  return { points, surface, wire, uniforms };
}
