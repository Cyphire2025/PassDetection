export type Rect = { x: number; y: number; w: number; h: number }
export type SculpturePresentation = { phase: "idle" | "listening" | "thinking" | "speaking"; reply: boolean; reveal: number; revealWidth: number; revealHeight: number }
export type SculptureHandle = { invalidate: () => void }
export type SculptureAppearance = { mode: "sculpture" | "logo" | "text" | "emoji" | "face" | "test"; text: string; emoji: "smile" | "heart" | "plane" | "globe" | "star"; stateAnimations: boolean }
export const DEFAULT_APPEARANCE: SculptureAppearance = { mode: "sculpture", text: "Global Connects", emoji: "smile", stateAnimations: true }

export interface EngineOptions {
  interactive: boolean
  strength: number
  radius: number
  density: number
  dotSize: number
  spread: number
  turbulence: number
  returnSpeed: number
  streaks: boolean
  restStyle: "image" | "particles"
  ambient: boolean
  ambientIntensity: number
  speed: number
  intro: boolean
  reducedMotion: boolean
  bg: [number, number, number]
  /** null = detected from the image corners */
  imgBg: [number, number, number] | null
  /** 0 – 2: how much the whole sculpture flows while the cursor is over it */
  liquid: number
  dark?: boolean
}

export function clamp(v: number, a: number, b: number) {
  return Math.min(b, Math.max(a, v))
}
