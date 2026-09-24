<template>
  <div class="bottombar">
    <div class="bottombar-inner">
      <span class="selection-label">{{ label }}</span>
      <div class="actions">
        <a v-if="zipUrl" class="zip-link" :href="zipUrl">Download all (zip)</a>
        <button
          class="export-btn"
          :class="{ active: canExport }"
          :disabled="!canExport"
          :title="jobStore.renderingEnabled ? '' : 'Rendering not configured'"
          @click="jobStore.exportSelected()"
        >
          {{ jobStore.renderingEnabled ? 'Render & export selected' : 'Rendering not configured' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useJobStore } from '../stores/jobStore'
import { rendersZipUrl } from '../services/highlyteApi'

const jobStore = useJobStore()

const label = computed(() => {
  const n = jobStore.selectedCount
  if (n === 0) return 'Select clips to export'
  const renders = jobStore.selectedRenders
  const done = renders.filter(r => r.status === 'done').length
  const busy = renders.filter(r => ['queued', 'rendering'].includes(r.status)).length
  if (busy) return `Rendering ${busy} of ${n} clips… (${done} done)`
  return `${n} of ${jobStore.clips.length} clips selected`
})

const canExport = computed(() => jobStore.renderingEnabled && jobStore.selectedCount > 0)

const zipUrl = computed(() => {
  const renders = jobStore.selectedRenders
  if (renders.length === 0 || renders.length !== jobStore.selectedCount) return null
  if (!renders.every(r => r.status === 'done')) return null
  return rendersZipUrl(renders.map(r => r.id))
})
</script>

<style scoped>
.bottombar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 30;
  background: rgba(255,255,255,0.94); backdrop-filter: blur(6px); border-top: 1px solid var(--border);
}
.bottombar-inner {
  max-width: 800px; margin: 0 auto; padding: 16px 24px;
  display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;
}
.selection-label { font-size: 13.5px; color: var(--ink-soft); }
.actions { display: flex; align-items: center; gap: 14px; }
.zip-link { font-size: 13.5px; font-weight: 600; color: var(--accent); }
.export-btn {
  border: none; border-radius: 8px; padding: 10px 20px; font-size: 13.5px; font-weight: 600;
  font-family: var(--font-sans); cursor: default; color: #fff;
  background: rgba(0,71,65,0.25);
}
.export-btn.active { background: var(--accent); cursor: pointer; }
</style>
