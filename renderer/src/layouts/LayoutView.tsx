import { AbsoluteFill, OffthreadVideo, useCurrentFrame, useVideoConfig } from 'remotion'
import { OUT_H, OUT_W } from '../constants'
import { cropWindow } from '../lib/crop'
import { sampleTrack } from '../lib/track'
import { resolveView } from '../lib/view'
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

  const view = resolveView(spec, layout, t)

  if (view.kind === 'fit') {
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

  if (view.kind === 'two') {
    const top = faces.find(f => f.id === view.topId) ?? faces[0]
    const bottom = faces.find(f => f.id === view.bottomId) ?? faces[0]
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

  const face = faces.find(f => f.id === view.faceId) ?? faces[0]
  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      <CroppedVideo src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={OUT_W} boxH={OUT_H}
        crop={cropWindow(srcW, srcH, sampleTrack(face.track, t).cx, OUT_W / OUT_H)} />
    </AbsoluteFill>
  )
}
