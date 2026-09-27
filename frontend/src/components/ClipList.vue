<template>
  <div>
    <div class="grid-header">
      <div
        class="select-all"
        role="checkbox"
        :aria-checked="jobStore.allSelected"
        tabindex="0"
        aria-label="Select all"
        @click="jobStore.toggleSelectAll()"
        @keydown.space.prevent="jobStore.toggleSelectAll()"
        @keydown.enter.prevent="jobStore.toggleSelectAll()"
      >
        <div class="checkbox" :class="{ checked: jobStore.allSelected }">
          <svg v-if="jobStore.allSelected" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>
        </div>
        <span class="header-title">Highlights</span>
      </div>
      <button
        v-if="hasVerticalClips"
        class="btn btn-ghost btn-sm style-all-btn"
        :class="{ open: showStyleAll }"
        :aria-expanded="showStyleAll"
        @click="showStyleAll = !showStyleAll"
      >Style all</button>
    </div>

    <StyleAllBar v-if="showStyleAll" />

    <div class="clip-grid">
      <ClipCard
        v-for="clip in jobStore.clips"
        :key="clip.id"
        :clip="clip"
        :is-selected="!!jobStore.selected[clip.id]"
        @toggle="jobStore.toggleClip(clip.id)"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useJobStore } from '../stores/jobStore'
import ClipCard from './ClipCard.vue'
import StyleAllBar from './StyleAllBar.vue'

const jobStore = useJobStore()
const hasVerticalClips = computed(() => jobStore.clips.some(c => c.spec))
const showStyleAll = ref(false)
</script>

<style scoped>
.grid-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; gap: 8px; flex-wrap: wrap; }
.select-all { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.checkbox {
  width: 16px; height: 16px; border-radius: 4px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; color: #fff;
  background: #fff; border: 1.5px solid var(--border);
}
.checkbox.checked { background: var(--accent); border-color: var(--accent); }
.header-title { font-size: 14px; font-weight: 600; }
.style-all-btn.open { background: var(--accent-soft); color: var(--accent-text); }
.clip-grid {
  display: grid; gap: 24px; grid-template-columns: repeat(3, minmax(0, 1fr));
}
@media (max-width: 1024px) { .clip-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .clip-grid { grid-template-columns: 1fr; } }
</style>
