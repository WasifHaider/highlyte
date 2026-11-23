import { useMemo } from 'react'
import { AbsoluteFill, getRemotionEnvironment, OffthreadVideo, Sequence, useCurrentFrame, useVideoConfig } from 'remotion'
import { sizeFor } from '../constants'
import { framePlan, type FramePlan } from '../lib/frame'
import { buildTimeline, toSource, type Timeline } from '../lib/tighten'
import { switchTimes, zoomAt } from '../lib/zoom'
import { resolveView } from '../lib/view'
import type { ClipSpec, Layout, Word } from '../schema'
import { resolveSrc } from '../source'
import { CroppedVideo } from './CroppedVideo'

const BLUR = { filter: 'blur(40px)', transform: 'scale(1.15)' } as const
const FADE_FRAMES = 2 // audio fade at each tightening cut, so cuts don't click
// Below the shortest cut (MIN_CUT_S), so every cut in the preview is a seek.
const PREVIEW_CUT_SHIFT_S = 0.1

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

type PanelsProps = {
  plan: FramePlan
  src: string
  trimBefore: number
  srcW: number
  srcH: number
  outW: number
  posterUrl?: string
  volume?: (f: number) => number
  acceptableTimeShift?: number
}

// The primary panel carries the sound: a separate <Audio> would download
// the whole file a second time, and every media element on a slow
// connection competes for the same bandwidth. The primary is mounted for
// the whole clip (or the whole kept piece) in every layout, so the sound
// never restarts. The children keep the same slots in every frame and
// layout (background, primary, secondary), so a camera cut or a layout
// change only changes props on mounted elements and never remounts a video.
const Panels: React.FC<PanelsProps> = ({ plan, src, trimBefore, srcW, srcH, outW, posterUrl, volume, acceptableTimeShift }) => (
  <>
    {plan.fit ? <FitBackground src={src} trimBefore={trimBefore} posterUrl={posterUrl} /> : null}
    <CroppedVideo key="primary" src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={outW}
      crop={plan.primary.crop} boxH={plan.primary.boxH} top={plan.primary.top} volume={volume}
      acceptableTimeShift={acceptableTimeShift} />
    {plan.secondary ? (
      <CroppedVideo key="secondary" src={src} trimBefore={trimBefore} srcW={srcW} srcH={srcH} boxW={outW} muted
        crop={plan.secondary.crop} boxH={plan.secondary.boxH} top={plan.secondary.top} visible={plan.secondary.visible}
        acceptableTimeShift={acceptableTimeShift} />
    ) : null}
  </>
)

type Props = {
  spec: ClipSpec
  layout: Layout
  aspect?: string
  zoom?: string
  posterUrl?: string
  // Tightening (lib/tighten.ts): the kept pieces and the words on the
  // output timeline. Without them the clip plays straight through.
  timeline?: Timeline
  words?: Word[]
}

export const LayoutView: React.FC<Props> = ({ spec, layout, aspect, zoom, posterUrl, timeline, words }) => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const tl = useMemo(() => timeline ?? buildTimeline(spec, 'off'), [timeline, spec])
  const outWords = words ?? spec.words
  const tOut = frame / fps
  // Faces, shots and speakers are measured on the source; zoom follows the
  // words as they are heard.
  const t = tl.tightened ? toSource(tl, tOut) : tOut
  const src = resolveSrc(spec.source.url)
  const { width: srcW, height: srcH } = spec.source

  const size = sizeFor(aspect)
  const switches = useMemo(() => switchTimes(outWords, tl.length), [outWords, tl.length])
  const z = zoomAt(tOut, outWords, zoom, tl.length, switches)
  const plan = framePlan(spec, layout, resolveView(spec, layout, t), t, size, z)
  const common = { plan, src, srcW, srcH, outW: size.width, posterUrl }

  // pauseWhenBuffering (CroppedVideo) stops the timeline while any media
  // element loads. Without it the captions run on, the picture freezes,
  // and on a slow connection Remotion keeps seeking the video to catch up,
  // which only starts another load: the preview never recovers until the
  // page is reloaded. Rendering ignores it.
  if (!tl.tightened) {
    return (
      <AbsoluteFill style={{ backgroundColor: 'black' }}>
        <Panels {...common} trimBefore={Math.round(spec.start * fps)} />
      </AbsoluteFill>
    )
  }

  // Tightened, in the browser preview: one set of video elements for the
  // whole clip, whose offset into the file changes at each cut, so the
  // video jumps forward with a seek inside data it has mostly buffered
  // already. A new element per piece would download each piece from
  // scratch and stall at every cut on a normal connection.
  if (getRemotionEnvironment().isPlayer) {
    const piece = tl.pieces.find(p => tOut < p.outStart + (p.to - p.from)) ?? tl.pieces[tl.pieces.length - 1]
    return (
      <AbsoluteFill style={{ backgroundColor: 'black' }}>
        <Panels {...common} trimBefore={Math.round((spec.start + piece.from - piece.outStart) * fps)}
          acceptableTimeShift={PREVIEW_CUT_SHIFT_S} />
      </AbsoluteFill>
    )
  }

  // Tightened, rendering: each kept piece plays from its own place in the
  // file (frame-exact, nothing to buffer). The
  // next piece is mounted a second early (premountFor) so its video has
  // loaded and seeked before the cut, and the sound fades over two frames
  // at each cut.
  const total = Math.round(tl.length * fps)
  const starts = tl.pieces.map(p => Math.round(p.outStart * fps))
  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      {tl.pieces.map((p, i) => {
        const from = starts[i]
        const dur = (i + 1 < starts.length ? starts[i + 1] : total) - from
        if (dur <= 0) return null
        const fadeIn = i > 0
        const fadeOut = i < tl.pieces.length - 1
        const volume = (f: number) => Math.min(
          1,
          fadeIn ? (f + 1) / (FADE_FRAMES + 1) : 1,
          fadeOut ? (dur - f) / (FADE_FRAMES + 1) : 1,
        )
        return (
          <Sequence key={i} from={from} durationInFrames={dur} premountFor={fps}>
            <Panels {...common} trimBefore={Math.round((spec.start + p.from) * fps)} volume={volume} />
          </Sequence>
        )
      })}
    </AbsoluteFill>
  )
}
