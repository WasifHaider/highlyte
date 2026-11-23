import { useMemo } from 'react'
import { AbsoluteFill, getRemotionEnvironment, OffthreadVideo, useCurrentFrame, useVideoConfig } from 'remotion'
import { sizeFor } from '../constants'
import { framePlan } from '../lib/frame'
import { switchTimes, zoomAt } from '../lib/zoom'
import { resolveView } from '../lib/view'
import type { ClipSpec, Layout } from '../schema'
import { resolveSrc } from '../source'
import { CroppedVideo } from './CroppedVideo'

const BLUR = { filter: 'blur(40px)', transform: 'scale(1.15)' } as const

// Behind a fit (letterboxed) frame. Rendering draws a blurred copy of the
// video. The browser preview would need a second video element for that,
// mounted and unmounted at every fit shot, which reloads and drifts out of
// sync; there it uses the clip's still poster instead (or plain black when
// none is given). This is the one place the preview differs from the render.
const FitBackground: React.FC<{ src: string; trimBefore: number; posterUrl?: string }> = ({ src, trimBefore, posterUrl }) => {
  if (getRemotionEnvironment().isPlayer) {
    return posterUrl ? (
      <AbsoluteFill style={BLUR}>
        <img src={posterUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      </AbsoluteFill>
    ) : null
  }
  return (
    <AbsoluteFill style={BLUR}>
      <OffthreadVideo src={src} trimBefore={trimBefore} muted style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
    </AbsoluteFill>
  )
}

export const LayoutView: React.FC<{ spec: ClipSpec; layout: Layout; aspect?: string; zoom?: string; posterUrl?: string }> = ({ spec, layout, aspect, zoom, posterUrl }) => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const t = frame / fps
  const src = resolveSrc(spec.source.url)
  const trimBefore = Math.round(spec.start * fps)
  const { width: srcW, height: srcH } = spec.source

  const size = sizeFor(aspect)
  const OUT_W = size.width
  const length = spec.end - spec.start
  const switches = useMemo(() => switchTimes(spec.words, length), [spec.words, length])
  const z = zoomAt(t, spec.words, zoom, length, switches)
  const plan = framePlan(spec, layout, resolveView(spec, layout, t), t, size, z)

  // The primary panel carries the sound: a separate <Audio> would download
  // the whole file a second time, and every media element on a slow
  // connection competes for the same bandwidth. The primary is mounted for
  // the whole clip in every layout, so the sound never restarts.
  // pauseWhenBuffering (off by default in Remotion 4) stops the timeline
  // while any media element loads. Without it the captions run on, the
  // picture freezes, and on a slow connection Remotion keeps seeking the
  // video to catch up, which only starts another load: the preview never
  // recovers until the page is reloaded. Rendering ignores it.
  // The children keep the same slots in every frame and layout (background,
  // primary, secondary), so a camera cut or a layout change only
  // changes props on mounted elements and never remounts a video.
  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      {plan.fit ? <FitBackground src={src} trimBefore={trimBefore} posterUrl={posterUrl} /> : null}
      <CroppedVideo key="primary" src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={OUT_W}
        crop={plan.primary.crop} boxH={plan.primary.boxH} top={plan.primary.top} />
      {plan.secondary ? (
        <CroppedVideo key="secondary" src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={OUT_W} muted
          crop={plan.secondary.crop} boxH={plan.secondary.boxH} top={plan.secondary.top} visible={plan.secondary.visible} />
      ) : null}
    </AbsoluteFill>
  )
}
