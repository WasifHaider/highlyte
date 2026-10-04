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
        @click="toggleStyleAll"
      >Style all</button>
    </div>

    <div v-if="hasVerticalClips" class="collapse" :class="{ open: showStyleAll }">
      <div class="collapse-inner" :inert="!showStyleAll">
        <StyleAllBar :key="styleAllGen" />
      </div>
    </div>

    <TransitionGroup name="rise" tag="div" class="clip-grid" appear>
      <ClipCard
        v-for="clip in jobStore.clips"
        :key="clip.id"
        :clip="clip"
        :is-selected="!!jobStore.selected[clip.id]"
        @toggle="jobStore.toggleClip(clip.id)"
      />
    </TransitionGroup>
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
// StyleAllBar stays mounted through the collapse animation (so it can
// animate closed instead of vanishing), but it should still re-seed its form
// from the current first-clip style each time it's reopened, as before:
// bumping this key forces a fresh instance on every open.
const styleAllGen = ref(0)
function toggleStyleAll() {
  if (!showStyleAll.value) styleAllGen.value++
  showStyleAll.value = !showStyleAll.value
}
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
/* One clip per row (Opus-style list); very wide screens get two columns. */
.clip-grid { display: grid; gap: 16px; grid-template-columns: 1fr; }
@media (min-width: 1500px) { .clip-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
