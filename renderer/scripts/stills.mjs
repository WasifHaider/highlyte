// One still per layout x caption preset from the fixture spec, at 1.5 s
// (hook title and captions both visible). Review out/stills by eye.
import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'

const spec = JSON.parse(readFileSync('src/__fixtures__/clip-spec.json', 'utf8'))
mkdirSync('out/stills', { recursive: true })
for (const layout of ['follow', 'speaker', 'split', 'fit']) {
  for (const captionPreset of ['karaoke', 'pop', 'clean']) {
    const props = {
      spec,
      style: { layout, captionPreset, showHook: true, hookTitle: spec.hookTitle, accent: '#FFD400', captionPosition: 'lower' },
    }
    const propsFile = `out/stills/props-${layout}-${captionPreset}.json`
    writeFileSync(propsFile, JSON.stringify(props))
    execFileSync('npx', ['remotion', 'still', 'src/index.ts', 'Clip', `out/stills/${layout}-${captionPreset}.png`,
      `--props=${propsFile}`, '--frame=45'], { stdio: 'inherit', shell: true })
  }
}
