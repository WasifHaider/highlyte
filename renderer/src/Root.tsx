import { Composition } from 'remotion'
import { ClipComposition } from './ClipComposition'
import { FPS, OUT_H, OUT_W, durationInFrames, sizeFor } from './constants'
import { clipFrames } from './lib/tighten'
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
    // Lambda sizes each render from its style's aspect (9:16 when unset).
    calculateMetadata={({ props }: { props: ClipProps }) => ({
      durationInFrames: clipFrames(props.spec, props.style.tighten),
      ...sizeFor(props.style.aspect),
    })}
  />
)
