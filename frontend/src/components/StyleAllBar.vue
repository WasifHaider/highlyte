<template>
  <div class="style-all">
    <div class="fields">
      <label class="field">
        <span class="field-label">Layout</span>
        <select class="select" v-model="form.layout">
          <option v-for="l in LAYOUTS" :key="l.value" :value="l.value">{{ l.label }}</option>
        </select>
      </label>
      <label class="field">
        <span class="field-label">Captions</span>
        <select class="select" v-model="form.captionPreset">
          <option v-for="p in PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
        </select>
      </label>
      <label class="field color">
        <span class="field-label">Accent colour</span>
        <div class="color-box">
          <input v-model="form.accent" type="color" />
        </div>
      </label>
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
import { LAYOUTS, PRESETS } from '../utils/clipStyle'

const APPLIED_MESSAGE_MS = 2400

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
.field.color { min-width: 0; }
.color-box {
  display: flex; align-items: center; height: 36px; border: 1px solid var(--border); border-radius: 8px;
  padding: 0 8px; background: #fff;
}
.color-box input[type="color"] { width: 24px; height: 24px; border: none; padding: 0; background: none; cursor: pointer; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-soft); padding-bottom: 8px; }
.check input[type="checkbox"] { accent-color: var(--accent); }
.apply { margin-left: 4px; }
.hint { margin-top: 10px; font-size: 12.5px; color: var(--ink-faint); }
</style>
