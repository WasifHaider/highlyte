import { OUT_H, OUT_W } from '../constants'
import type { ClipSpec, Layout } from '../schema'
import { cropWindow, type Crop } from './crop'
import { sampleTrack } from './track'
import type { View } from './view'

export const PANEL_H = OUT_H / 2

// One video panel: which part of the source it shows (`crop`, source
// pixels), the box it fills (full output width, `boxH` tall, `top` from the
// top edge) and whether it is shown at all.
export type Panel = { crop: Crop; boxH: number; top: number; visible: boolean }

export type FramePlan = { primary: Panel; secondary: Panel | null; fit: boolean }

// Where each video panel goes at time t. The set of panels depends only on
// the chosen layout, never on the current shot: a panel that disappears at a
// camera cut would be unmounted, and a remounted video in the browser
// preview reloads its source and drifts behind the audio. So the primary
// panel always exists (fit is a letterboxed full-frame crop of it) and the
// secondary exists for the whole clip whenever split is chosen, hidden
// during shots that aren't split.
export function framePlan(spec: ClipSpec, layout: Layout, view: View, t: number): FramePlan {
  const { width: srcW, height: srcH } = spec.source
  const faces = spec.reframe.faces
  const faceCx = (id: number | undefined): number =>
    sampleTrack((faces.find(f => f.id === id) ?? faces[0]).track, t).cx

  const hasSecondary = layout === 'split' && faces.length >= 2
  const secondaryId = view.kind === 'two' ? view.bottomId : faces[1]?.id
  const secondary: Panel | null = hasSecondary
    ? {
        crop: cropWindow(srcW, srcH, faceCx(secondaryId), OUT_W / PANEL_H),
        boxH: PANEL_H,
        top: PANEL_H,
        visible: view.kind === 'two',
      }
    : null

  if (view.kind === 'fit') {
    const boxH = (OUT_W * srcH) / srcW
    return {
      primary: { crop: { x: 0, y: 0, w: srcW, h: srcH }, boxH, top: (OUT_H - boxH) / 2, visible: true },
      secondary,
      fit: true,
    }
  }

  const isTwo = view.kind === 'two'
  const boxH = isTwo ? PANEL_H : OUT_H
  return {
    primary: {
      crop: cropWindow(srcW, srcH, faceCx(isTwo ? view.topId : view.faceId), OUT_W / boxH),
      boxH,
      top: 0,
      visible: true,
    },
    secondary,
    fit: false,
  }
}
