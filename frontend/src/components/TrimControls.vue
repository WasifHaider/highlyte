<template>
  <div class="trim-controls">
    <div v-if="!trimmable" class="note">Re-run the video to trim this clip.</div>
    <template v-else>
      <div class="trim-row">
        <span class="trim-label">Start:</span>
        <button class="trim-btn" :disabled="disabled || !startBack.ok" :title="startBack.ok ? '' : startBack.reason"
          @click="apply(startBack)">◀ Sentence</button>
        <button class="trim-btn" :disabled="disabled || !startMinus.ok" :title="startMinus.ok ? '' : startMinus.reason"
          @click="apply(startMinus)">−0.5 s</button>
        <button class="trim-btn" :disabled="disabled || !startPlus.ok" :title="startPlus.ok ? '' : startPlus.reason"
          @click="apply(startPlus)">+0.5 s</button>
        <button class="trim-btn" :disabled="disabled || !startFwd.ok" :title="startFwd.ok ? '' : startFwd.reason"
          @click="apply(startFwd)">Sentence ▶</button>
      </div>
      <div class="trim-row">
        <span class="trim-label">End:</span>
        <button class="trim-btn" :disabled="disabled || !endBack.ok" :title="endBack.ok ? '' : endBack.reason"
          @click="apply(endBack)">◀ Sentence</button>
        <button class="trim-btn" :disabled="disabled || !endMinus.ok" :title="endMinus.ok ? '' : endMinus.reason"
          @click="apply(endMinus)">−0.5 s</button>
        <button class="trim-btn" :disabled="disabled || !endPlus.ok" :title="endPlus.ok ? '' : endPlus.reason"
          @click="apply(endPlus)">+0.5 s</button>
        <button class="trim-btn" :disabled="disabled || !endFwd.ok" :title="endFwd.ok ? '' : endFwd.reason"
          @click="apply(endFwd)">Sentence ▶</button>
      </div>
      <div class="trim-row">
        <span class="trim-length">{{ lengthLabel }}</span>
        <a v-if="clip.boundsEdited" class="trim-reset" :class="{ disabled }" @click="!disabled && reset()">Reset</a>
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
.trim-controls { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
.trim-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.trim-label { font-size: 12px; color: var(--ink-soft); width: 34px; flex-shrink: 0; }
.trim-btn {
  border: 1px solid var(--border); background: var(--accent-soft); color: var(--accent-text);
  border-radius: 6px; padding: 3px 9px; font-size: 12px; font-weight: 600; cursor: pointer;
}
.trim-btn:disabled { opacity: .5; cursor: default; }
.trim-length { font-size: 12px; color: var(--ink-faint); }
.trim-reset { font-size: 12px; color: var(--accent-text); font-weight: 600; cursor: pointer; }
.trim-reset.disabled { opacity: .5; cursor: default; pointer-events: none; }
.note { font-size: 12px; color: var(--ink-faint); }
</style>
