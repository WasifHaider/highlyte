import type { Word } from '../schema'
import type { Crop } from './crop'

// Camera motion on face crops (style.zoom), the "edited" feel of a short:
// - 'emphasis': a quick punch-in on each emphasised word (the words the
//   titles call marked), easing back after it;
// - 'dynamic': the same, plus a jump between a wide and a tight framing
//   every few seconds (always on a word start, so it reads as an edit),
//   with a slow push-in inside each stretch.
// 'off' (and styles saved before zoom existed) never zoom.
export type ZoomMode = 'off' | 'emphasis' | 'dynamic'

export const PUNCH = 1.12        // scale at the peak of a punch-in
export const RISE_S = 0.12       // ease in, starting at the word's start
export const HOLD_S = 0.5        // stay in this long after the word ends
export const FALL_S = 0.35       // ease back out
export const ALT_EVERY_S = 5     // dynamic: switch framing about this often
export const ALT_SCALE = 1.08    // dynamic: the tight framing
export const PUSH = 0.03         // dynamic: slow push-in over each stretch

const smooth = (k: number) => {
  const c = Math.min(1, Math.max(0, k))
  return c * c * (3 - 2 * c)
}

function punchAt(t: number, words: Word[]): number {
  let z = 1
  for (const w of words) {
    if (!w.emphasis || t < w.start || t > w.end + HOLD_S + FALL_S) continue
    const up = smooth((t - w.start) / RISE_S)
    const down = t <= w.end + HOLD_S ? 1 : 1 - smooth((t - w.end - HOLD_S) / FALL_S)
    z = Math.max(z, 1 + (PUNCH - 1) * Math.min(up, down))
  }
  return z
}

// Where the dynamic framing switches: the first word start at or after
// each ALT_EVERY_S mark, so a switch never lands mid-word.
export function switchTimes(words: Word[], length: number): number[] {
  const out: number[] = []
  for (let mark = ALT_EVERY_S; mark < length; mark += ALT_EVERY_S) {
    const w = words.find(x => x.start >= mark && x.start < length && (out.length === 0 || x.start > out[out.length - 1]))
    if (w) out.push(w.start)
  }
  return out
}

function dynamicAt(t: number, switches: number[], length: number): number {
  let i = 0
  while (i < switches.length && switches[i] <= t) i++
  const from = i === 0 ? 0 : switches[i - 1]
  const to = i < switches.length ? switches[i] : length
  const base = i % 2 === 0 ? 1 : ALT_SCALE
  const push = to > from ? (t - from) / (to - from) : 0
  return base * (1 + PUSH * Math.min(1, Math.max(0, push)))
}

// How much to zoom at time t (clip time), 1 meaning no zoom.
export function zoomAt(t: number, words: Word[], mode: string | undefined, length: number, switches?: number[]): number {
  if (mode !== 'emphasis' && mode !== 'dynamic') return 1
  const punch = punchAt(t, words)
  if (mode === 'emphasis') return punch
  return punch * dynamicAt(t, switches ?? switchTimes(words, length), length)
}

// `crop` tightened by `z` around the face: the horizontal centre stays
// where the crop already follows the face, the vertical centre moves
// toward the face's height (cy, 0-1). Kept inside the source frame.
export function zoomCrop(crop: Crop, z: number, cy: number, srcW: number, srcH: number): Crop {
  if (z <= 1) return crop
  const w = crop.w / z
  const h = crop.h / z
  const cx = crop.x + crop.w / 2
  const x = Math.min(Math.max(cx - w / 2, 0), srcW - w)
  const y = Math.min(Math.max(cy * srcH - h / 2, 0), srcH - h)
  return { x, y, w, h }
}
