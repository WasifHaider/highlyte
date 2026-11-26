export const FPS = 30

// Output sizes per aspect ratio (Aspect in schema.ts, backend/spec.py).
// Every size is 1080 wide, so caption and title pixel sizes carry over.
export const SIZES = {
  '9:16': { width: 1080, height: 1920 },
  '4:5': { width: 1080, height: 1350 },
  '1:1': { width: 1080, height: 1080 },
} as const

export type AspectId = keyof typeof SIZES
export type Size = { width: number; height: number }

// A style saved before aspects could be chosen is 9:16.
export const sizeFor = (aspect: string | undefined): Size => SIZES[aspect as AspectId] ?? SIZES['9:16']

// The 9:16 size, for code that has no style at hand.
export const OUT_W = SIZES['9:16'].width
export const OUT_H = SIZES['9:16'].height

export const durationInFrames = (spec: { start: number; end: number }): number =>
  Math.max(1, Math.round((spec.end - spec.start) * FPS))
