<template>
  <div class="video-card">
    <div class="thumb">
      <img v-if="meta.thumbnailUrl && !imgFailed" :src="meta.thumbnailUrl" alt="" @error="imgFailed = true" />
      <span v-else class="play" aria-hidden="true"></span>
    </div>
    <div class="video-info">
      <div class="video-title">{{ meta.title }}</div>
      <div class="video-meta">{{ meta.channel }} · {{ meta.durationLabel }}</div>
      <div class="status-note">{{ statusNote }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  meta: { type: Object, required: true },
  statusNote: { type: String, default: '' },
})
const imgFailed = ref(false)
</script>

<style scoped>
.video-card {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
  margin-bottom: 44px;
}
.thumb {
  width: 180px;
  height: 101px;
  flex-shrink: 0;
  border-radius: 10px;
  background: repeating-linear-gradient(45deg,#F0EDE4,#F0EDE4 8px,#E3DFD3 8px,#E3DFD3 16px);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-faint);
  overflow: hidden;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.play { width: 0; height: 0; border-top: 10px solid transparent; border-bottom: 10px solid transparent; border-left: 15px solid var(--ink-faint); }
.video-info { flex: 1; min-width: 200px; display: flex; flex-direction: column; justify-content: center; }
.video-title { font-family: var(--font-serif); font-size: 22px; font-weight: 500; line-height: 1.3; }
.video-meta { margin-top: 8px; font-size: 13px; color: var(--ink-soft); }
.status-note { margin-top: 6px; font-size: 12px; color: var(--accent); font-weight: 500; }
</style>
