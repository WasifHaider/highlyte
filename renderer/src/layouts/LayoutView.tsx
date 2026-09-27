import { AbsoluteFill, Audio, OffthreadVideo, useCurrentFrame, useVideoConfig } from 'remotion'
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
        <Audio src={src} trimBefore={trimBefore} />
        <AbsoluteFill style={{ filter: 'blur(40px)', transform: 'scale(1.15)' }}>
          <OffthreadVideo src={src} trimBefore={trimBefore} muted style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        </AbsoluteFill>
        <AbsoluteFill style={{ justifyContent: 'center' }}>
          <OffthreadVideo src={src} trimBefore={trimBefore} muted style={{ width: OUT_W, height: (OUT_W * srcH) / srcW }} />
        </AbsoluteFill>
      </AbsoluteFill>
    )
  }

  // 'two' and 'one' share one tree shape (Audio, then a stable primary panel,
  // then an optional secondary panel) so a switch at a camera cut only
  // changes props on already-mounted elements instead of remounting them —
  // that would restart audio and flash black in the browser preview.
  const isTwo = view.kind === 'two'
  const primaryFace = faces.find(f => f.id === (isTwo ? view.topId : view.faceId)) ?? faces[0]
  const secondaryFace = isTwo ? faces.find(f => f.id === view.bottomId) ?? faces[0] : null
  const primaryBoxH = isTwo ? PANEL_H : OUT_H
  const primaryAspect = OUT_W / primaryBoxH

  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      <Audio src={src} trimBefore={trimBefore} />
      <CroppedVideo key="primary" src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={OUT_W} boxH={primaryBoxH} muted
        crop={cropWindow(srcW, srcH, sampleTrack(primaryFace.track, t).cx, primaryAspect)} />
      {secondaryFace ? (
        <CroppedVideo key="secondary" src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={OUT_W} boxH={PANEL_H} muted
          crop={cropWindow(srcW, srcH, sampleTrack(secondaryFace.track, t).cx, OUT_W / PANEL_H)} />
      ) : null}
    </AbsoluteFill>
  )
}
