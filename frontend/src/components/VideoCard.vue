<template>
  <div class="video-card">
    <div class="thumb">
      <img v-if="meta.thumbnailUrl && !imgFailed" :src="meta.thumbnailUrl" alt="" @error="imgFailed = true" />
      <span v-else class="play" aria-hidden="true"></span>
    </div>
    <div class="video-info">
      <div class="video-title">{{ meta.title }}</div>
      <div class="video-meta">{{ meta.channel }} · {{ meta.durationLabel }}</div>
      <div v-if="statusNote" class="status-note">
        <template v-if="noteParts.count">{{ noteParts.prefix }}<span class="accent-count">{{ noteParts.count }}</span></template>
        <template v-else>{{ statusNote }}</template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  meta: { type: Object, required: true },
  statusNote: { type: String, default: '' },
})
const imgFailed = ref(false)

// Purely presentational: if statusNote already contains a trailing "N thing"
// segment (e.g. "Processed · 6 highlights found"), colour that segment
// accent. Otherwise render statusNote plainly. Does not change how
// statusNote is built.
const noteParts = computed(() => {
  const note = props.statusNote || ''
  const idx = note.lastIndexOf('·')
  if (idx === -1) return { prefix: note, count: '' }
  const after = note.slice(idx + 1).trim()
  if (/^\d/.test(after)) {
    return { prefix: note.slice(0, idx + 1) + ' ', count: after }
  }
  return { prefix: note, count: '' }
})
</script>

<style scoped>
.video-card {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}
.thumb {
  width: 80px;
  height: 45px;
  flex-shrink: 0;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--bg-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.play { width: 0; height: 0; border-top: 7px solid transparent; border-bottom: 7px solid transparent; border-left: 10px solid var(--ink-faint); }
.video-info { min-width: 0; }
.video-title {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.video-meta { margin-top: 2px; font-size: 12.5px; color: var(--ink-soft); }
.status-note { margin-top: 2px; font-size: 12.5px; color: var(--ink-soft); }
.accent-count { color: var(--accent); font-weight: 500; }
</style>
