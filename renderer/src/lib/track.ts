import type { TrackPoint } from '../schema'

// Face tracks come pre-smoothed from Python; here we only interpolate.
// When a face disappears the crop holds its last position for HOLD_S,
// then eases back to centre over EASE_S.
export const HOLD_S = 2
export const EASE_S = 0.5

const lerp = (a: number, b: number, k: number) => a + (b - a) * k

export function sampleTrack(track: TrackPoint[], t: number): { cx: number; cy: number } {
  if (track.length === 0) return { cx: 0.5, cy: 0.5 }
  let i = -1
  for (let k = 0; k < track.length; k++) {
    if (track[k].t <= t) i = k
    else break
  }
  if (i === -1) {
    const first = track[0]
    return first.t - t <= HOLD_S ? { cx: first.cx, cy: first.cy } : { cx: 0.5, cy: 0.5 }
  }
  const prev = track[i]
  const next = track[i + 1]
  if (next && next.t - prev.t <= HOLD_S) {
    const k = (t - prev.t) / (next.t - prev.t)
    return { cx: lerp(prev.cx, next.cx, k), cy: lerp(prev.cy, next.cy, k) }
  }
  const since = t - prev.t
  if (since <= HOLD_S) return { cx: prev.cx, cy: prev.cy }
  const k = Math.min(1, (since - HOLD_S) / EASE_S)
  return { cx: lerp(prev.cx, 0.5, k), cy: lerp(prev.cy, 0.5, k) }
}
