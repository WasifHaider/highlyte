<template>
  <div class="style-all">
    <div class="fields">
      <div class="field">
        <span class="field-label">Layout</span>
        <UiSelect v-model="form.layout" :options="layoutOptions" aria-label="Layout" />
      </div>
      <div class="field">
        <span class="field-label">Captions</span>
        <UiSelect v-model="form.captionPreset" :options="captionOptions" aria-label="Captions" />
      </div>
      <div class="field color">
        <span class="field-label">Accent colour</span>
        <UiColorField v-model="form.accent" aria-label="Accent colour" />
      </div>
      <label class="check">
        <input v-model="form.showHook" type="checkbox" /> Show hook title
      </label>
      <button class="btn btn-primary btn-sm apply" @click="apply">Apply to all</button>
    </div>
    <div class="hint">
      <template v-if="appliedCount">Applied to {{ appliedCount }} clip{{ appliedCount === 1 ? '' : 's' }}.</template>
      <template v-else>Clips that can't use a face layout keep their automatic layout. Hook titles stay per clip.</template>
    </div>
  </div>
</template>

<script setup>
import { onUnmounted, reactive, ref } from 'vue'
import { useJobStore } from '../stores/jobStore'
import UiSelect from './ui/UiSelect.vue'
import UiColorField from './ui/UiColorField.vue'
import { LAYOUTS, PRESETS } from '../utils/clipStyle'

const APPLIED_MESSAGE_MS = 2400
const layoutOptions = LAYOUTS.map(l => ({ value: l.value, label: l.label }))
const captionOptions = PRESETS.map(p => ({ value: p.value, label: p.label }))

const jobStore = useJobStore()
// Start from the first clip's current style so the bar reflects what's there.
const first = jobStore.clips.find(c => c.spec)?.style || {}
const form = reactive({
  layout: first.layout || 'fit',
  captionPreset: first.captionPreset || 'karaoke',
  accent: first.accent || '#FFD400',
  showHook: first.showHook ?? true,
})
const appliedCount = ref(0)
let timer = null

function apply() {
  appliedCount.value = jobStore.applyStyleToAll({ ...form })
  clearTimeout(timer)
  timer = setTimeout(() => { appliedCount.value = 0 }, APPLIED_MESSAGE_MS)
}
onUnmounted(() => clearTimeout(timer))
</script>

<style scoped>
.style-all { background: var(--bg-subtle); border-radius: 12px; padding: 16px; margin-bottom: 20px; }
.fields { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 4px; min-width: 150px; }
.field.color { min-width: 0; width: 212px; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-soft); padding-bottom: 8px; }
.check input[type="checkbox"] { accent-color: var(--accent); }
.apply { margin-left: 4px; }
.hint { margin-top: 10px; font-size: 12.5px; color: var(--ink-faint); }
</style>
