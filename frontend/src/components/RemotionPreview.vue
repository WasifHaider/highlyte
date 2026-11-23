<template>
  <div class="remotion-preview-wrap" :style="{ aspectRatio: `${size.width} / ${size.height}` }">
    <div ref="host" class="remotion-preview"></div>
    <div v-if="!ready" class="remotion-skeleton skeleton" aria-hidden="true"></div>
  </div>
</template>

<script setup>
// Hosts the Remotion Player (React) inside this Vue app. The composition
// is imported straight from renderer/src, so the preview is the exact
// code Lambda renders.
import { computed, onBeforeUnmount, onMounted, ref, toRaw, watch } from 'vue'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { Player } from '@remotion/player'
import { ClipComposition } from '@renderer/ClipComposition'
import { FPS, durationInFrames, sizeFor } from '@renderer/constants'

const props = defineProps({
  spec: { type: Object, required: true },
  clipStyle: { type: Object, required: true },
  autoPlay: { type: Boolean, default: false },
  // The clip's still image, used by the preview as the blurred background
  // behind a fit frame (renders draw that background from the video).
  posterUrl: { type: String, default: null },
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

// The serialized props last drawn. The deep watch below also fires when a
// status poll replaces the clip with an identical copy; redrawing then makes
// the Player re-check every media element and can trigger a seek, which
// stutters playback. So only a real change is drawn.
let lastDrawn = null

// The clip's output size (its aspect ratio; 9:16 when the style has none).
const size = computed(() => sizeFor(props.clipStyle?.aspect))

function draw() {
  if (!root) return
  const inputProps = { spec: plain(props.spec), style: plain(props.clipStyle) }
  if (props.posterUrl) inputProps.posterUrl = props.posterUrl
  const key = JSON.stringify([inputProps, props.autoPlay])
  if (key === lastDrawn) return
  lastDrawn = key
  const spec = inputProps.spec
  root.render(createElement(Player, {
    component: ClipComposition,
    inputProps,
    durationInFrames: durationInFrames(spec),
    fps: FPS,
    compositionWidth: size.value.width,
    compositionHeight: size.value.height,
    controls: true,
    autoPlay: props.autoPlay,
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

let rafId1 = null
let rafId2 = null

onMounted(() => {
  root = createRoot(host.value)
  draw()
  rafId1 = requestAnimationFrame(() => {
    rafId2 = requestAnimationFrame(markReady)
  })
})
watch(() => [props.spec, props.clipStyle, props.posterUrl], draw, { deep: true })
onBeforeUnmount(() => {
  if (rafId1 != null) cancelAnimationFrame(rafId1)
  if (rafId2 != null) cancelAnimationFrame(rafId2)
  detachFrameListener()
  root?.unmount()
  root = null
  lastDrawn = null
})
</script>

<style scoped>
.remotion-preview-wrap { position: relative; width: 100%; border-radius: 10px; overflow: hidden; }
.remotion-preview { width: 100%; height: 100%; background: #000; border-radius: 10px; overflow: hidden; }
.remotion-skeleton { position: absolute; inset: 0; border-radius: 10px; }
</style>
