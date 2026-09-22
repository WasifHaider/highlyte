<template>
  <div>
    <div class="results-header">
      <div class="results-title">Highlights</div>
      <div class="select-all" @click="jobStore.toggleSelectAll()">
        <div class="checkbox" :class="{ checked: jobStore.allSelected }">
          <span v-if="jobStore.allSelected">✓</span>
        </div>
        Select all
      </div>
    </div>

    <div class="clip-list">
      <ClipRow
        v-for="clip in jobStore.clips"
        :key="clip.id"
        :clip="clip"
        :is-selected="!!jobStore.selected[clip.id]"
        :is-playing="jobStore.playingClipId === clip.id"
        @toggle="jobStore.toggleClip(clip.id)"
        @play="jobStore.setPlaying(clip.id)"
      />
    </div>
  </div>
</template>

<script setup>
import { useJobStore } from '../stores/jobStore'
import ClipRow from './ClipRow.vue'

const jobStore = useJobStore()
</script>

<style scoped>
.results-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 18px; flex-wrap: wrap; gap: 8px; }
.results-title { font-family: var(--font-serif); font-size: 26px; font-weight: 500; }
.select-all { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; color: var(--ink-soft); }
.checkbox {
  width: 16px; height: 16px; border-radius: 4px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; color: #fff;
  background: #fff; border: 1.5px solid var(--border);
}
.checkbox.checked { background: var(--accent); border-color: var(--accent); }
.clip-list { display: flex; flex-direction: column; gap: 16px; }
</style>
