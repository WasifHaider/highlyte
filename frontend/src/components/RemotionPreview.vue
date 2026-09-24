<template>
  <div ref="host" class="remotion-preview"></div>
</template>

<script setup>
// Hosts the Remotion Player (React) inside this Vue app. The composition
// is imported straight from renderer/src, so the preview is the exact
// code Lambda renders.
import { onBeforeUnmount, onMounted, ref, toRaw, watch } from 'vue'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { Player } from '@remotion/player'
import { ClipComposition } from '@renderer/ClipComposition'
import { FPS, OUT_H, OUT_W, durationInFrames } from '@renderer/constants'

const props = defineProps({
  spec: { type: Object, required: true },
  clipStyle: { type: Object, required: true },
})

const host = ref(null)
let root = null

// React must receive plain objects, not Vue's reactive proxies.
const plain = (value) => JSON.parse(JSON.stringify(toRaw(value)))

function draw() {
  if (!root) return
  const spec = plain(props.spec)
  root.render(createElement(Player, {
    component: ClipComposition,
    inputProps: { spec, style: plain(props.clipStyle) },
    durationInFrames: durationInFrames(spec),
    fps: FPS,
    compositionWidth: OUT_W,
    compositionHeight: OUT_H,
    controls: true,
    acknowledgeRemotionLicense: true,
    style: { width: '100%' },
  }))
}

onMounted(() => {
  root = createRoot(host.value)
  draw()
})
watch(() => [props.spec, props.clipStyle], draw, { deep: true })
onBeforeUnmount(() => {
  root?.unmount()
  root = null
})
</script>

<style scoped>
.remotion-preview { width: 100%; aspect-ratio: 9 / 16; background: #000; border-radius: 10px; overflow: hidden; }
</style>
