<template>
  <div class="remotion-preview-wrap">
    <div ref="host" class="remotion-preview"></div>
    <div v-if="!ready" class="remotion-skeleton skeleton" aria-hidden="true"></div>
  </div>
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
const ready = ref(false)
// The Player API (event-emitter.d.ts) has no "ready"/"canplay" event; it only
// fires `frameupdate` once frames are actually rendered, which may never
// happen before the viewer presses play. So whichever comes first wins: the
// player's own first frameupdate, or two animation frames after mount (long
// enough for React/Remotion's first paint, short enough not to look stuck).
// The callback ref below re-fires on every draw() (a new inline function each
// time, so React re-invokes it even for the same underlying instance), so
// both the instance and the listener are tracked to detach cleanly instead of
// piling up duplicate listeners.
let playerInstance = null
let firstFrameListener = null

function detachFrameListener() {
  if (playerInstance && firstFrameListener) {
    playerInstance.removeEventListener('frameupdate', firstFrameListener)
  }
  firstFrameListener = null
}

function markReady() {
  ready.value = true
  detachFrameListener()
}

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
    ref: (instance) => {
      if (!instance) return
      playerInstance = instance
      if (ready.value || firstFrameListener) return
      firstFrameListener = () => markReady()
      instance.addEventListener('frameupdate', firstFrameListener)
    },
  }))
}

onMounted(() => {
  root = createRoot(host.value)
  draw()
  requestAnimationFrame(() => requestAnimationFrame(markReady))
})
watch(() => [props.spec, props.clipStyle], draw, { deep: true })
onBeforeUnmount(() => {
  detachFrameListener()
  root?.unmount()
  root = null
})
</script>

<style scoped>
.remotion-preview-wrap { position: relative; width: 100%; aspect-ratio: 9 / 16; border-radius: 10px; overflow: hidden; }
.remotion-preview { width: 100%; height: 100%; aspect-ratio: 9 / 16; background: #000; border-radius: 10px; overflow: hidden; }
.remotion-skeleton { position: absolute; inset: 0; border-radius: 10px; }
</style>
