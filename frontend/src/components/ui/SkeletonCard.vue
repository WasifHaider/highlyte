<template>
  <div class="card skeleton-card" :class="variant" aria-hidden="true">
    <div class="thumb skeleton"></div>
    <div class="body">
      <template v-if="variant === 'clip'">
        <div class="bar trim skeleton"></div>
        <div class="bar text skeleton"></div>
        <div class="row">
          <div class="bar btn skeleton"></div>
          <div class="bar btn skeleton"></div>
        </div>
      </template>
      <template v-else>
        <div class="bar text-80 skeleton"></div>
        <div class="bar text-50 skeleton"></div>
        <div class="bar chip skeleton"></div>
      </template>
    </div>
  </div>
</template>

<script setup>
defineProps({
  variant: { type: String, default: 'project' }, // 'project' | 'clip'
})
</script>

<style scoped>
.skeleton-card { overflow: hidden; display: flex; flex-direction: column; }
.thumb { aspect-ratio: 16 / 9; }
.skeleton-card.clip { flex-direction: row; gap: 16px; padding: 14px; }
.skeleton-card.clip .thumb { aspect-ratio: 9 / 16; width: 112px; flex-shrink: 0; border-radius: 10px; }
.skeleton-card.clip .body { flex: 1; padding: 0; }
.body { padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.bar { border-radius: 6px; }
.text-80 { height: 14px; width: 80%; }
.text-50 { height: 14px; width: 50%; }
.chip { height: 20px; width: 72px; border-radius: 999px; }
.trim { height: 28px; width: 100%; }
.text { height: 14px; width: 60%; }
.row { display: flex; gap: 8px; }
.btn { height: 28px; flex: 1; }
</style>
