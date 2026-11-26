import { FPS } from '../constants'
import type { ClipSpec, Word } from '../schema'
import { toClipTime } from './timeline'

// Tightening (style.tighten) cuts dead air out of a clip: pauses in the
// speech ('pauses'), or pauses and filler sounds ('all'). Nothing is cut
// from the file; the clip plays as a run of kept pieces of it, and
// everything drawn on top (captions, zoom) is moved onto the shorter
// output timeline. All times here are clip time (lib/timeline.ts), and
// "source" means the clip's own time before tightening.

export const MIN_PAUSE_S = 0.4   // shorter pauses are part of the rhythm
export const KEEP_S = 0.15       // leave this much of each pause on both sides
export const MIN_CUT_S = 0.12    // don't bother cutting less than this
export const MIN_PIECE_S = 0.3   // never leave a kept piece shorter than this

// Vocal fillers only: Hinglish "toh", "matlab" and the like carry meaning.
const FILLERS = new Set(['uh', 'um', 'umm', 'uhh', 'uhm', 'hmm', 'hm', 'er', 'erm', 'ah', 'eh'])
const norm = (text: string) => text.toLowerCase().replace(/[^a-z]/g, '')
export const isFiller = (w: Word) => !w.emphasis && FILLERS.has(norm(w.text))

export type Piece = { from: number; to: number; outStart: number }

export type Timeline = {
  pieces: Piece[]
  length: number          // output length, seconds
  tightened: boolean      // false: one piece covering the whole clip
}

type Span = [number, number]

function merge(spans: Span[]): Span[] {
  const sorted = spans.filter(([a, b]) => b > a).sort((x, y) => x[0] - y[0])
  const out: Span[] = []
  for (const [a, b] of sorted) {
    const last = out[out.length - 1]
    if (last && a <= last[1]) last[1] = Math.max(last[1], b)
    else out.push([a, b])
  }
  return out
}

// What to cut from a clip of `length` seconds.
export function cutsFor(spec: ClipSpec, mode: string | undefined, length: number): Span[] {
  if (mode !== 'pauses' && mode !== 'all') return []
  const words = spec.words
  const first = words.length ? words[0].start : 0
  const last = words.length ? words[words.length - 1].end : length
  const cuts: Span[] = []
  for (const [a, b] of spec.silences ?? []) {
    // Only pauses between the first and last word: the clip's lead-in and
    // tail were placed on purpose by the cutter.
    const from = Math.max(a, first)
    const to = Math.min(b, last)
    if (to - from < MIN_PAUSE_S) continue
    cuts.push([from + KEEP_S, to - KEEP_S])
  }
  if (mode === 'all') {
    for (const w of words) if (isFiller(w)) cuts.push([w.start, w.end])
  }
  return merge(cuts).filter(([a, b]) => b - a >= MIN_CUT_S)
}

export function buildTimeline(spec: ClipSpec, mode: string | undefined): Timeline {
  const length = Math.max(0, spec.end - spec.start)
  const cuts = cutsFor(spec, mode, length)
  const pieces: Piece[] = []
  let cursor = 0
  let out = 0
  for (const [a, b] of [...cuts, [length, length] as Span]) {
    // A piece too short to read as a shot is kept by dropping this cut.
    if (a - cursor < MIN_PIECE_S && a < length && pieces.length > 0) continue
    if (a > cursor) {
      pieces.push({ from: cursor, to: a, outStart: out })
      out += a - cursor
    }
    cursor = Math.max(cursor, b)
  }
  if (pieces.length === 0) pieces.push({ from: 0, to: length, outStart: 0 })
  return { pieces, length: out || length, tightened: pieces.length > 1 || pieces[0].to - pieces[0].from < length }
}

// Source time shown at output time t.
export function toSource(tl: Timeline, t: number): number {
  for (const p of tl.pieces) {
    const len = p.to - p.from
    if (t < p.outStart + len) return p.from + Math.max(0, t - p.outStart)
  }
  const last = tl.pieces[tl.pieces.length - 1]
  return last.to
}

// Output time of source time s, or null when s falls in a cut.
export function toOutput(tl: Timeline, s: number): number | null {
  for (const p of tl.pieces) {
    if (s >= p.from && s <= p.to) return p.outStart + (s - p.from)
  }
  return null
}

// Words on the output timeline. A word inside a cut is dropped (a filler);
// one that straddles a cut edge is clamped to its piece.
export function outputWords(tl: Timeline, words: Word[]): Word[] {
  if (!tl.tightened) return words
  const out: Word[] = []
  for (const w of words) {
    const p = tl.pieces.find(x => w.end > x.from && w.start < x.to)
    if (!p) continue
    const start = p.outStart + (Math.max(w.start, p.from) - p.from)
    const end = p.outStart + (Math.min(w.end, p.to) - p.from)
    out.push({ ...w, start: Math.round(start * 1000) / 1000, end: Math.round(end * 1000) / 1000 })
  }
  return out
}

// Frames in the finished clip: the tightened length when tightening is on,
// otherwise the clip's own length. Takes a spec as stored (any version);
// the composition's length on Lambda and in the preview come from here.
export function clipFrames(spec: ClipSpec, mode: string | undefined): number {
  const tl = buildTimeline(toClipTime(spec), mode)
  return Math.max(1, Math.round(tl.length * FPS))
}
