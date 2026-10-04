<template>
  <div class="trim-controls">
    <div v-if="!trimmable" class="note">Re-run the video to trim this clip.</div>
    <template v-else>
      <div class="trim-header">
        <span class="trim-title">TRIM</span>
        <span class="trim-header-right">
          <span class="trim-length tabular">{{ lengthLabel }}</span>
          <button
            v-if="clip.boundsEdited"
            type="button"
            class="trim-reset"
            :class="{ disabled }"
            :disabled="disabled"
            @click="reset()"
          >Reset</button>
        </span>
      </div>
      <div class="trim-row">
        <span class="trim-label">Start</span>
        <button class="btn btn-secondary btn-sm" :disabled="disabled || !startBack.ok" :title="startBack.ok ? '' : startBack.reason"
          @click="apply(startBack)">◀ Sentence</button>
        <button class="btn btn-secondary btn-sm" :disabled="disabled || !startMinus.ok" :title="startMinus.ok ? '' : startMinus.reason"
          @click="apply(startMinus)">−0.5 s</button>
        <button class="btn btn-secondary btn-sm" :disabled="disabled || !startPlus.ok" :title="startPlus.ok ? '' : startPlus.reason"
          @click="apply(startPlus)">+0.5 s</button>
        <button class="btn btn-secondary btn-sm" :disabled="disabled || !startFwd.ok" :title="startFwd.ok ? '' : startFwd.reason"
          @click="apply(startFwd)">Sentence ▶</button>
      </div>
      <div class="trim-row">
        <span class="trim-label">End</span>
        <button class="btn btn-secondary btn-sm" :disabled="disabled || !endBack.ok" :title="endBack.ok ? '' : endBack.reason"
          @click="apply(endBack)">◀ Sentence</button>
        <button class="btn btn-secondary btn-sm" :disabled="disabled || !endMinus.ok" :title="endMinus.ok ? '' : endMinus.reason"
          @click="apply(endMinus)">−0.5 s</button>
        <button class="btn btn-secondary btn-sm" :disabled="disabled || !endPlus.ok" :title="endPlus.ok ? '' : endPlus.reason"
          @click="apply(endPlus)">+0.5 s</button>
        <button class="btn btn-secondary btn-sm" :disabled="disabled || !endFwd.ok" :title="endFwd.ok ? '' : endFwd.reason"
          @click="apply(endFwd)">Sentence ▶</button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { canTrim, nudge, sentence, NUDGE_S } from '@renderer/lib/trim'
import { useJobStore } from '../stores/jobStore'

const props = defineProps({
  clip: { type: Object, required: true },
})

const jobStore = useJobStore()

const trimmable = computed(() => canTrim(props.clip.spec))
const disabled = computed(() => !!props.clip.pendingAction)

const startBack = computed(() => sentence(props.clip.spec, 'start', -1))
const startFwd = computed(() => sentence(props.clip.spec, 'start', 1))
const startMinus = computed(() => nudge(props.clip.spec, 'start', -NUDGE_S))
const startPlus = computed(() => nudge(props.clip.spec, 'start', NUDGE_S))

const endBack = computed(() => sentence(props.clip.spec, 'end', -1))
const endFwd = computed(() => sentence(props.clip.spec, 'end', 1))
const endMinus = computed(() => nudge(props.clip.spec, 'end', -NUDGE_S))
const endPlus = computed(() => nudge(props.clip.spec, 'end', NUDGE_S))

const lengthLabel = computed(() => `${(props.clip.spec.end - props.clip.spec.start).toFixed(1)} s`)

function apply(move) {
  if (!move.ok || disabled.value) return
  jobStore.updateBounds(props.clip.id, move.bounds)
}
function reset() {
  jobStore.resetBounds(props.clip.id)
}
</script>

<style scoped>
.trim-controls {
  display: flex; flex-direction: column; gap: 8px;
}
.trim-header { display: flex; align-items: center; justify-content: space-between; }
.trim-title { font-size: 11px; font-weight: 500; letter-spacing: .05em; text-transform: uppercase; color: var(--ink-soft); }
.trim-header-right { display: flex; align-items: center; gap: 8px; }
.trim-length { font-size: 12px; color: var(--ink); }
.trim-reset {
  font: 600 12px var(--font-sans); color: var(--accent); cursor: pointer;
  background: none; border: none; padding: 0;
}
.trim-reset.disabled { opacity: .5; cursor: default; pointer-events: none; }
.trim-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.trim-label { font-size: 11.5px; color: var(--ink-faint); width: 36px; flex-shrink: 0; }
.note { font-size: 12px; color: var(--ink-faint); }
</style>
