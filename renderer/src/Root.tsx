import { Composition } from 'remotion'
import { ClipComposition } from './ClipComposition'
import { FPS, OUT_H, OUT_W, durationInFrames } from './constants'
import fixture from './__fixtures__/clip-spec.json'
import { clipPropsSchema, type ClipProps } from './schema'

const defaultProps = clipPropsSchema.parse({
  spec: fixture,
  style: {
    layout: fixture.reframe.auto,
    captionPreset: 'karaoke',
    showHook: true,
    hookTitle: fixture.hookTitle,
    accent: '#FFD400',
    captionPosition: 'lower',
  },
})

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Clip"
    component={ClipComposition}
    schema={clipPropsSchema}
    width={OUT_W}
    height={OUT_H}
    fps={FPS}
    durationInFrames={durationInFrames(defaultProps.spec)}
    defaultProps={defaultProps}
    calculateMetadata={({ props }: { props: ClipProps }) => ({ durationInFrames: durationInFrames(props.spec) })}
  />
)
