import { AbsoluteFill } from 'remotion'
import { Captions } from './captions/Captions'
import { HookTitle } from './HookTitle'
import { LayoutView } from './layouts/LayoutView'
import type { ClipProps } from './schema'

export const ClipComposition: React.FC<ClipProps> = ({ spec, style }) => {
  // Split layout puts captions on the seam between the two panels.
  const position = style.layout === 'split' ? 'middle' : style.captionPosition
  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      <LayoutView spec={spec} layout={style.layout} />
      <Captions words={spec.words} preset={style.captionPreset} accent={style.accent} position={position} />
      {style.showHook && style.hookTitle ? <HookTitle text={style.hookTitle} /> : null}
    </AbsoluteFill>
  )
}
