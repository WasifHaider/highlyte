import { AbsoluteFill, OffthreadVideo, useCurrentFrame, useVideoConfig } from 'remotion'
import { OUT_H, OUT_W } from '../constants'
import { cropWindow } from '../lib/crop'
import { activeFace } from '../lib/speaker'
import { sampleTrack } from '../lib/track'
import type { ClipSpec, Layout } from '../schema'
import { resolveSrc } from '../source'
import { CroppedVideo } from './CroppedVideo'

const PANEL_H = OUT_H / 2

export const LayoutView: React.FC<{ spec: ClipSpec; layout: Layout }> = ({ spec, layout }) => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const t = frame / fps
  const src = resolveSrc(spec.source.url)
  const trimBefore = Math.round(spec.start * fps)
  const { width: srcW, height: srcH } = spec.source
  const faces = spec.reframe.faces

  // Layouts that need faces fall back gracefully when analysis found none.
  const effective: Layout = faces.length === 0 ? 'fit' : layout === 'split' && faces.length < 2 ? 'follow' : layout

  if (effective === 'fit') {
    return (
      <AbsoluteFill style={{ backgroundColor: 'black' }}>
        <AbsoluteFill style={{ filter: 'blur(40px)', transform: 'scale(1.15)' }}>
          <OffthreadVideo src={src} trimBefore={trimBefore} muted style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        </AbsoluteFill>
        <AbsoluteFill style={{ justifyContent: 'center' }}>
          <OffthreadVideo src={src} trimBefore={trimBefore} style={{ width: OUT_W, height: (OUT_W * srcH) / srcW }} />
        </AbsoluteFill>
      </AbsoluteFill>
    )
  }

  if (effective === 'split') {
    // Order panels by where each person sits at the start, so they never swap mid-clip.
    const [top, bottom] = [faces[0], faces[1]].sort((a, b) => (a.track[0]?.cx ?? 0.5) - (b.track[0]?.cx ?? 0.5))
    const aspect = OUT_W / PANEL_H
    return (
      <AbsoluteFill style={{ backgroundColor: 'black' }}>
        <CroppedVideo src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={OUT_W} boxH={PANEL_H}
          crop={cropWindow(srcW, srcH, sampleTrack(top.track, t).cx, aspect)} />
        <CroppedVideo src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={OUT_W} boxH={PANEL_H} muted
          crop={cropWindow(srcW, srcH, sampleTrack(bottom.track, t).cx, aspect)} />
      </AbsoluteFill>
    )
  }

  const faceId = effective === 'speaker' ? activeFace(spec.reframe.speakerTimeline, t) ?? faces[0].id : faces[0].id
  const face = faces.find(f => f.id === faceId) ?? faces[0]
  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      <CroppedVideo src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={OUT_W} boxH={OUT_H}
        crop={cropWindow(srcW, srcH, sampleTrack(face.track, t).cx, OUT_W / OUT_H)} />
    </AbsoluteFill>
  )
}
