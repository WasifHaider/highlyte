<template>
  <div class="bottombar">
    <div class="bottombar-inner">
      <span class="selection-label">{{ label }}</span>
      <button class="export-btn" :class="{ active: jobStore.selectedCount > 0 }" @click="onExport">
        Export selected
      </button>
    </div>
    <div v-if="toastMsg" class="toast">{{ toastMsg }}</div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useJobStore } from '../stores/jobStore'
import { clipDownloadUrl } from '../services/highlyteApi'

const jobStore = useJobStore()
const toastMsg = ref('')

const label = computed(() => {
  const n = jobStore.selectedCount
  return n === 0 ? 'Select clips to export' : `${n} of ${jobStore.clips.length} clips selected`
})

function onExport() {
  const selectedClips = jobStore.clips.filter(c => jobStore.selected[c.id])
  if (selectedClips.length === 0) return
  for (const c of selectedClips) {
    const a = document.createElement('a')
    a.href = clipDownloadUrl(c.downloadUrl)
    a.download = ''
    document.body.appendChild(a)
    a.click()
    a.remove()
  }
  toastMsg.value = `Exporting ${selectedClips.length} clip${selectedClips.length === 1 ? '' : 's'}…`
  setTimeout(() => { toastMsg.value = '' }, 2400)
}
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
.export-btn {
  border: none; border-radius: 8px; padding: 10px 20px; font-size: 13.5px; font-weight: 600;
  font-family: var(--font-sans); cursor: default; color: #fff;
  background: rgba(43,38,32,0.25);
}
.export-btn.active { background: var(--accent); cursor: pointer; }
.toast {
  position: fixed; bottom: 90px; left: 50%; transform: translateX(-50%);
  background: var(--ink); color: var(--bg); padding: 10px 18px; border-radius: 999px;
  font-size: 13px; z-index: 40; animation: toastIn .2s ease;
}
</style>
