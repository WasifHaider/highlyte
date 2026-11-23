import { useMemo } from 'react'
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from 'remotion'
import { Captions } from './captions/Captions'
import { HookTitle } from './HookTitle'
import { LayoutView } from './layouts/LayoutView'
import { ProgressBar } from './ProgressBar'
import { captionPositionAt } from './lib/view'
import { toClipTime } from './lib/timeline'
import type { ClipProps } from './schema'

export const ClipComposition: React.FC<ClipProps> = ({ spec, style, posterUrl }) => {
  const clip = useMemo(() => toClipTime(spec), [spec])
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const position = captionPositionAt(clip, style, frame / fps)
  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      <LayoutView spec={clip} layout={style.layout} aspect={style.aspect} zoom={style.zoom} posterUrl={posterUrl} />
      <Captions words={clip.words} preset={style.captionPreset} accent={style.accent} position={position} font={style.font} aspect={style.aspect} />
      {style.showHook && style.hookTitle ? <HookTitle text={style.hookTitle} font={style.font} aspect={style.aspect} /> : null}
      {style.progressBar === 'top' || style.progressBar === 'bottom'
        ? <ProgressBar edge={style.progressBar} color={style.accent} />
        : null}
    </AbsoluteFill>
  )
}
