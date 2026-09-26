<template>
  <div class="captions-edit">
    <div class="row">
      <button v-if="!open" class="btn" @click="start">Edit captions</button>
      <button v-if="!open && edited" class="btn ghost" :disabled="busy" @click="reset">Reset to original</button>
    </div>
    <div v-if="open" class="lines">
      <label v-for="line in lines" :key="line.index" class="line">
        <span class="time">{{ clock(line.start - (props.start ?? 0)) }}</span>
        <input :value="textOf(line)" type="text" @input="texts[line.index] = $event.target.value" />
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
  start: { type: Number, default: null },
  end: { type: Number, default: null },
  // The clip's revision (bumped by Swap/Regenerate) and whether an action
  // is running on it: either one closes the editor, so a replaced clip
  // never receives the old clip's texts.
  revision: { type: Number, default: 0 },
  pending: { type: Boolean, default: false },
})
const emit = defineEmits(['draft'])
const jobStore = useJobStore()

// Mirrors backend.captions.MAX_WORD_CHARS: catch the same limit here so
// a bad edit gets a clear message instead of a 422 after Save.
const MAX_WORD_CHARS = 40

const open = ref(false)
const busy = ref(false)
const error = ref('')
// Keyed by line.index (a line's position in the whole, untrimmed clip), not
// by position in `lines`: a trim adds or drops edge lines while the editor
// is open, and positional texts would then land on the wrong lines. A line
// with no entry (it came into view after opening) is left as it is.
const texts = ref({})
// When start/end are set (v2 spec, trimmed clip), only the lines inside the
// clip's bounds are shown/edited — each line keeps its global `from` so
// editLine still applies to the full, untrimmed word list.
const lines = computed(() => {
  const all = captionLines(props.words)
  if (props.start == null || props.end == null) return all
  return all.filter(line => line.end > props.start && line.start < props.end)
})

// Applied last line first, so each line's word index stays valid.
const draft = computed(() => {
  if (!open.value) return null
  let out = props.words
  for (let i = lines.value.length - 1; i >= 0; i--) {
    const line = lines.value[i]
    const text = texts.value[line.index]
    if (text !== undefined && text !== lineText(line)) out = editLine(out, line, text)
  }
  return out
})
watch(draft, d => emit('draft', d))

function textOf(line) {
  return texts.value[line.index] ?? lineText(line)
}

// A replaced clip (new revision) or one an action has started on must not
// keep an editor open over it: the action makes the editor unreachable, and
// the old texts belong to the old words.
watch(() => [props.revision, props.pending], ([revision, pending], [oldRevision]) => {
  if (pending || revision !== oldRevision) close()
})

const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// Nothing to save once every line has been cleared out.
const saveDisabled = computed(() => open.value && (draft.value?.length ?? 0) === 0)

function overlongWordLine() {
  for (const line of lines.value) {
    const hasOverlong = textOf(line).split(/\s+/).some(t => t.length > MAX_WORD_CHARS)
    if (hasOverlong) return line
  }
  return null
}

function start() {
  texts.value = Object.fromEntries(lines.value.map(line => [line.index, lineText(line)]))
  error.value = ''
  open.value = true
}
function close() {
  open.value = false
  texts.value = {}
}
function cancel() {
  close()
}
async function save() {
  const overlong = overlongWordLine()
  if (overlong) {
    error.value = `The line at ${clock(overlong.start - (props.start ?? 0))} has a word over ${MAX_WORD_CHARS} characters.`
    return
  }
  busy.value = true
  error.value = ''
  try {
    await jobStore.saveCaptions(props.clipId, draft.value)
    close()
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
