<template>
  <div class="style-all">
    <div class="bar-title">Style all clips</div>
    <div class="fields">
      <label class="field">
        <span>Layout</span>
        <select v-model="form.layout">
          <option v-for="l in LAYOUTS" :key="l.value" :value="l.value">{{ l.label }}</option>
        </select>
      </label>
      <label class="field">
        <span>Captions</span>
        <select v-model="form.captionPreset">
          <option v-for="p in PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
        </select>
      </label>
      <label class="field color">
        <span>Accent colour</span>
        <input v-model="form.accent" type="color" />
      </label>
      <label class="check">
        <input v-model="form.showHook" type="checkbox" /> Show hook title
      </label>
      <button class="apply" @click="apply">Apply to all</button>
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
.style-all { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; margin-bottom: 20px; }
.bar-title { font-weight: 600; font-size: 14px; margin-bottom: 10px; }
.fields { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-soft); min-width: 150px; }
.field select {
  font-family: var(--font-sans); font-size: 13.5px; color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 9px; background: #fff;
}
.field.color { min-width: 0; }
.field input[type="color"] { width: 48px; height: 34px; border: 1px solid var(--border); border-radius: 8px; padding: 2px; background: #fff; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-soft); padding-bottom: 8px; }
.apply {
  border: none; border-radius: 8px; padding: 9px 16px; font-size: 13.5px; font-weight: 600;
  font-family: var(--font-sans); color: #fff; background: var(--accent); cursor: pointer;
}
.hint { margin-top: 10px; font-size: 12px; color: var(--ink-faint); }
</style>
