import { AbsoluteFill, useCurrentFrame, useVideoConfig } from 'remotion'
import { Captions } from './captions/Captions'
import { HookTitle } from './HookTitle'
import { LayoutView } from './layouts/LayoutView'
import { captionPositionAt } from './lib/view'
import type { ClipProps } from './schema'

export const ClipComposition: React.FC<ClipProps> = ({ spec, style }) => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const position = captionPositionAt(spec, style, frame / fps)
  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      <LayoutView spec={spec} layout={style.layout} />
      <Captions words={spec.words} preset={style.captionPreset} accent={style.accent} position={position} />
      {style.showHook && style.hookTitle ? <HookTitle text={style.hookTitle} /> : null}
    </AbsoluteFill>
  )
}
