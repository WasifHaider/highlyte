import type { ClipSpec } from '../schema'

// Spec v2 stores words and face data for the whole cut file (times from the
// file start) so a clip can be nudged without a re-cut. Everything that
// draws a clip works in clip time (0 = the clip's first frame), so v2 specs
// are converted here, in one place. v1 specs are already in clip time.
export function toClipTime(spec: ClipSpec): ClipSpec {
  if (spec.version !== 2) return spec
  const { start, end } = spec
  const length = end - start
  const shift = (t: number) => Math.round((t - start) * 1000) / 1000
  return {
    ...spec,
    words: spec.words
      .filter(w => w.end > start && w.start < end)
      .map(w => ({ ...w, start: shift(w.start), end: shift(w.end) })),
    reframe: {
      ...spec.reframe,
      faces: spec.reframe.faces.map(f => ({ ...f, track: f.track.map(p => ({ ...p, t: shift(p.t) })) })),
      speakerTimeline: spec.reframe.speakerTimeline.map(s => ({ ...s, t: shift(s.t) })),
      shots: (spec.reframe.shots ?? [])
        .filter(s => s.end > start && s.start < end)
        .map(s => ({ ...s, start: Math.max(0, shift(s.start)), end: Math.min(length, shift(s.end)) })),
    },
  }
}

export function fileDuration(spec: ClipSpec): number | null {
  return spec.version === 2 && spec.source.duration ? spec.source.duration : null
}
