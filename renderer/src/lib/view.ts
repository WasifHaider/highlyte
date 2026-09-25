import type { ClipSpec, Layout } from '../schema'
import { activeShot } from './shots'
import { activeFace } from './speaker'

// What the frame shows at time t. Clips with shots switch at each camera
// cut; clips analysed before shots existed keep the old whole-clip rules.
export type View = { kind: 'fit' } | { kind: 'one'; faceId: number } | { kind: 'two'; topId: number; bottomId: number }

export function resolveView(spec: ClipSpec, layout: Layout, t: number): View {
  const { faces, speakerTimeline, shots } = spec.reframe
  if (faces.length === 0 || layout === 'fit') return { kind: 'fit' }

  const shot = activeShot(shots, t)
  if (shot) {
    if (shot.kind === 'none' || shot.faceIds.length === 0) return { kind: 'fit' }
    if (layout === 'split' && shot.kind === 'two') return { kind: 'two', topId: shot.faceIds[0], bottomId: shot.faceIds[1] }
    if (layout === 'speaker') {
      const speaking = activeFace(speakerTimeline, t)
      if (speaking !== null && shot.faceIds.includes(speaking)) return { kind: 'one', faceId: speaking }
    }
    return { kind: 'one', faceId: shot.faceIds[0] }
  }

  if (layout === 'split' && faces.length >= 2) {
    const [top, bottom] = [faces[0], faces[1]].sort((a, b) => (a.track[0]?.cx ?? 0.5) - (b.track[0]?.cx ?? 0.5))
    return { kind: 'two', topId: top.id, bottomId: bottom.id }
  }
  if (layout === 'speaker') return { kind: 'one', faceId: activeFace(speakerTimeline, t) ?? faces[0].id }
  return { kind: 'one', faceId: faces[0].id }
}
