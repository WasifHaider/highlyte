import type { ClipSpec } from '../schema'
import { fileDuration } from './timeline'

export const MIN_CLIP_S = 8
export const MAX_CLIP_S = 60
export const NUDGE_S = 0.5
export const LEAD_S = 0.22
export const AIR_S = 0.4
export const PREV_GUARD_S = 0.03
export const NEXT_GUARD_S = 0.05

export type Bounds = { start: number; end: number }
export type Move = { ok: true; bounds: Bounds } | { ok: false; reason: string }

const EDGE = 'That is the edge of the spare video.'
const ENDS = /[.?!]["')\]]?$/
const r3 = (n: number) => Math.round(n * 1000) / 1000

export const canTrim = (spec: ClipSpec) => fileDuration(spec) !== null

function check(spec: ClipSpec, b: Bounds): Move {
  const file = fileDuration(spec) as number
  if (b.start < 0 || b.end > file + 1e-6) return { ok: false, reason: EDGE }
  if (b.end - b.start < MIN_CLIP_S - 1e-6) return { ok: false, reason: 'Clips must be at least 8 s.' }
  if (b.end - b.start > MAX_CLIP_S + 1e-6) return { ok: false, reason: 'Clips can be at most 60 s.' }
  return { ok: true, bounds: { start: r3(b.start), end: r3(b.end) } }
}

export function nudge(spec: ClipSpec, edge: 'start' | 'end', deltaS: number): Move {
  if (!canTrim(spec)) return { ok: false, reason: 'Re-run the video to trim this clip.' }
  const file = fileDuration(spec) as number
  const b = { start: spec.start, end: spec.end }
  if (edge === 'start') b.start = Math.min(Math.max(0, r3(b.start + deltaS)), b.end)
  else b.end = Math.max(Math.min(file, r3(b.end + deltaS)), b.start)
  if (b.start === spec.start && b.end === spec.end) return { ok: false, reason: EDGE }
  return check(spec, b)
}

export function sentence(spec: ClipSpec, edge: 'start' | 'end', dir: -1 | 1): Move {
  if (!canTrim(spec)) return { ok: false, reason: 'Re-run the video to trim this clip.' }
  const words = spec.words
  const file = fileDuration(spec) as number
  const none = dir < 0 ? 'No earlier sentence in the spare video.' : 'No later sentence in the spare video.'
  if (edge === 'start') {
    const starts = words.map((w, i) => i).filter(i => i === 0 || ENDS.test(words[i - 1].text))
    const current = words.findIndex(w => w.start >= spec.start - 1e-6)
    const pickI = dir < 0 ? [...starts].reverse().find(i => i < current) : starts.find(i => i > current)
    if (pickI === undefined || current < 0) return { ok: false, reason: none }
    const w = words[pickI]
    let t = w.start - LEAD_S
    if (pickI > 0) t = Math.max(t, words[pickI - 1].end + PREV_GUARD_S)
    return check(spec, { start: Math.min(Math.max(t, 0), w.start), end: spec.end })
  }
  const ends = words.map((w, i) => i).filter(i => ENDS.test(words[i].text))
  let current = -1
  words.forEach((w, i) => { if (w.end <= spec.end + 1e-6) current = i })
  const pickI = dir > 0 ? ends.find(i => i > current) : [...ends].reverse().find(i => i < current)
  if (pickI === undefined) return { ok: false, reason: none }
  const w = words[pickI]
  let t = w.end + AIR_S
  if (pickI < words.length - 1) t = Math.min(t, words[pickI + 1].start - NEXT_GUARD_S)
  return check(spec, { start: spec.start, end: Math.max(Math.min(t, file), w.end) })
}
