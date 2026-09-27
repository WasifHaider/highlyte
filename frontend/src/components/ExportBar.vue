<template>
  <div class="export-pill">
    <span class="selection-label">{{ label }}</span>
    <div class="divider"></div>
    <a v-if="zipUrl" class="zip-link" :href="zipUrl">
      <span class="zip-full">Download zip</span>
      <span class="zip-short">Zip</span>
    </a>
    <button
      class="btn btn-primary export-btn"
      :disabled="!canExport"
      :title="jobStore.renderingEnabled ? '' : 'Rendering not configured'"
      @click="jobStore.exportSelected()"
    >
      {{ jobStore.renderingEnabled ? 'Render & export' : 'Rendering not configured' }}
    </button>
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
.export-pill {
  position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); z-index: 30;
  display: flex; align-items: center; gap: 16px;
  background: #fff; border: 1px solid var(--border); border-radius: 999px;
  box-shadow: 0 4px 12px rgba(0,0,0,.08);
  padding: 10px 16px;
  max-width: calc(100vw - 32px);
}
.selection-label { font-size: 13.5px; font-weight: 500; color: var(--ink); white-space: nowrap; }
.divider { width: 1px; height: 16px; background: var(--border); flex-shrink: 0; }
.zip-link { font-size: 13.5px; font-weight: 600; color: var(--ink-soft); text-decoration: none; white-space: nowrap; }
.zip-link:hover { color: var(--ink); }
.zip-short { display: none; }
.export-btn { height: 32px; border-radius: 999px; padding: 0 16px; white-space: nowrap; }
@media (max-width: 480px) {
  .export-pill { gap: 10px; padding: 10px 12px; }
  .zip-full { display: none; }
  .zip-short { display: inline; }
  .selection-label { overflow: hidden; text-overflow: ellipsis; }
}
</style>
