<template>
  <div class="video-card">
    <div class="thumb">video<br />thumbnail</div>
    <div class="video-info">
      <div class="video-title">{{ meta.title }}</div>
      <div class="video-meta">{{ meta.channel }} · {{ meta.durationLabel }}</div>
      <div class="status-note">{{ statusNote }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  meta: { type: Object, required: true },
  statusNote: { type: String, default: '' },
})
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
  font-family: monospace;
  font-size: 10px;
  color: var(--ink-faint);
  text-align: center;
}
.video-info { flex: 1; min-width: 200px; display: flex; flex-direction: column; justify-content: center; }
.video-title { font-family: var(--font-serif); font-size: 22px; font-weight: 500; line-height: 1.3; }
.video-meta { margin-top: 8px; font-size: 13px; color: var(--ink-soft); }
.status-note { margin-top: 6px; font-size: 12px; color: var(--accent); font-weight: 500; }
</style>
