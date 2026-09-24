// A window of the source frame (in source pixels) with the output's aspect
// ratio, centred horizontally on cx (0-1) and clamped inside the frame.
export type Crop = { x: number; y: number; w: number; h: number }

export function cropWindow(srcW: number, srcH: number, cx: number, aspect: number): Crop {
  let h = srcH
  let w = h * aspect
  if (w > srcW) {
    w = srcW
    h = w / aspect
  }
  const x = Math.min(Math.max(cx * srcW - w / 2, 0), srcW - w)
  return { x, y: (srcH - h) / 2, w, h }
}
