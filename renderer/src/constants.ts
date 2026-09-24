export const FPS = 30
export const OUT_W = 1080
export const OUT_H = 1920

export const durationInFrames = (spec: { start: number; end: number }): number =>
  Math.max(1, Math.round((spec.end - spec.start) * FPS))
