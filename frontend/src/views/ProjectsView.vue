<template>
  <div class="page">
    <div class="page-head">
      <h1 class="page-title">Projects</h1>
      <p class="muted sub">Every video you've processed. Open one to style and export its clips.</p>
    </div>

    <div class="controls">
      <input v-model="query" type="search" class="input search" placeholder="Search by title" />
      <div class="segmented" role="group" aria-label="Filter by status">
        <button
          v-for="tab in STATUS_TABS"
          :key="tab.value"
          type="button"
          :aria-pressed="status === tab.value"
          @click="status = tab.value"
        >{{ tab.label }}</button>
      </div>
    </div>

    <div v-if="error" class="muted state-msg">
      {{ error }} <button class="btn btn-ghost btn-sm" @click="reload">Retry</button>
    </div>
    <div v-else-if="loading" class="grid" aria-busy="true">
      <SkeletonCard v-for="i in PROJECTS_SKELETON_COUNT" :key="i" variant="project" />
    </div>
    <div v-else-if="projects.length === 0 && filtered" class="muted state-msg">No projects match.</div>
    <div v-else-if="projects.length === 0" class="empty-state">
      <p class="muted">No projects yet.</p>
      <router-link to="/" class="btn btn-primary">Paste a link</router-link>
    </div>
    <TransitionGroup v-else name="rise" tag="div" class="grid" appear>
      <ProjectCard v-for="p in projects" :key="p.id" :project="p" />
    </TransitionGroup>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import ProjectCard from '../components/ProjectCard.vue'
import SkeletonCard from '../components/ui/SkeletonCard.vue'
import { useProjects } from '../composables/useProjects'

const PROJECTS_SKELETON_COUNT = 6
const STATUS_TABS = [
  { value: '', label: 'All' },
  { value: 'processing', label: 'Processing' },
  { value: 'done', label: 'Done' },
  { value: 'error', label: 'Failed' },
]
const SEARCH_DEBOUNCE_MS = 300

const query = ref('')
const search = ref('')
const status = ref('')
let debounce = null
watch(query, (value) => {
  clearTimeout(debounce)
  debounce = setTimeout(() => { search.value = value.trim() }, SEARCH_DEBOUNCE_MS)
})
onUnmounted(() => clearTimeout(debounce))

const filtered = computed(() => !!(search.value || status.value))
const { projects, loading, error, reload } = useProjects(() => ({
  q: search.value || undefined,
  status: status.value || undefined,
}))
</script>

<style scoped>
.page-head { margin-bottom: 24px; }
.sub { margin: 6px 0 0; font-size: 13.5px; }
.controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 0 0 24px; }
.search { flex: 1; min-width: 220px; }
.state-msg { padding: 24px 0; }
.empty-state { text-align: center; padding: 64px 24px; display: flex; flex-direction: column; align-items: center; gap: 16px; }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }

@media (max-width: 900px) { .grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px) {
  .grid { grid-template-columns: 1fr; }
  .controls { flex-direction: column; align-items: stretch; }
}
</style>
