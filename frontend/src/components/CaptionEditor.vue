<template>
  <div class="captions-edit">
    <div class="row">
      <button v-if="!open" class="btn" @click="start">Edit captions</button>
      <button v-if="!open && edited" class="btn ghost" :disabled="busy" @click="reset">Reset to original</button>
    </div>
    <div v-if="open" class="lines">
      <label v-for="(line, i) in lines" :key="line.index" class="line">
        <span class="time">{{ clock(line.start) }}</span>
        <input v-model="texts[i]" type="text" />
      </label>
      <div class="row">
        <button class="btn" :disabled="busy || saveDisabled" @click="save">{{ busy ? 'Saving…' : 'Save captions' }}</button>
        <button class="btn ghost" :disabled="busy" @click="cancel">Cancel</button>
      </div>
    </div>
    <div v-if="error" class="error">{{ error }}</div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { captionLines, editLine, lineText } from '@renderer/captions/edit'
import { useJobStore } from '../stores/jobStore'

const props = defineProps({
  clipId: { type: String, required: true },
  words: { type: Array, required: true },
  edited: { type: Boolean, default: false },
})
const emit = defineEmits(['draft'])
const jobStore = useJobStore()

// Mirrors backend.captions.MAX_WORD_CHARS: catch the same limit here so
// a bad edit gets a clear message instead of a 422 after Save.
const MAX_WORD_CHARS = 40

const open = ref(false)
const busy = ref(false)
const error = ref('')
const texts = ref([])
const lines = computed(() => captionLines(props.words))

// Applied last line first, so each line's word index stays valid.
const draft = computed(() => {
  if (!open.value) return null
  let out = props.words
  for (let i = lines.value.length - 1; i >= 0; i--) {
    const line = lines.value[i]
    if (texts.value[i] !== lineText(line)) out = editLine(out, line, texts.value[i] ?? '')
  }
  return out
})
watch(draft, d => emit('draft', d))

const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// Nothing to save once every line has been cleared out.
const saveDisabled = computed(() => open.value && (draft.value?.length ?? 0) === 0)

function overlongWordLine() {
  for (let i = 0; i < lines.value.length; i++) {
    const hasOverlong = (texts.value[i] || '').split(/\s+/).some(t => t.length > MAX_WORD_CHARS)
    if (hasOverlong) return lines.value[i]
  }
  return null
}

function start() {
  texts.value = lines.value.map(lineText)
  error.value = ''
  open.value = true
}
function cancel() {
  open.value = false
}
async function save() {
  const overlong = overlongWordLine()
  if (overlong) {
    error.value = `The line at ${clock(overlong.start)} has a word over ${MAX_WORD_CHARS} characters.`
    return
  }
  busy.value = true
  error.value = ''
  try {
    await jobStore.saveCaptions(props.clipId, draft.value)
    open.value = false
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Failed to save captions'
  } finally {
    busy.value = false
  }
}
async function reset() {
  busy.value = true
  error.value = ''
  try {
    await jobStore.resetCaptions(props.clipId)
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Failed to reset captions'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.captions-edit { margin-top: 10px; }
.row { display: flex; gap: 8px; margin-top: 8px; }
.lines { display: flex; flex-direction: column; gap: 6px; max-height: 280px; overflow-y: auto; }
.line { display: flex; align-items: center; gap: 8px; }
.time { font-family: monospace; font-size: 11.5px; color: var(--ink-soft); width: 36px; flex-shrink: 0; }
.line input { flex: 1; min-width: 0; border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font-size: 13px; }
.btn { border: 1px solid var(--border); background: var(--accent-soft); color: var(--accent-text); border-radius: 6px; padding: 4px 10px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.btn.ghost { background: transparent; color: var(--ink-soft); }
.btn:disabled { opacity: .6; cursor: default; }
.error { color: #9C3B14; font-size: 12.5px; margin-top: 6px; }
</style>
