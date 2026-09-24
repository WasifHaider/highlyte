<template>
  <div class="page">
    <div class="page-head">
      <h1>Projects</h1>
      <p class="sub">Every video you've processed. Open one to style and export its clips.</p>
    </div>

    <div class="controls">
      <input v-model="query" type="search" class="search" placeholder="Search by title" />
      <div class="status-tabs" role="group" aria-label="Filter by status">
        <button
          v-for="tab in STATUS_TABS"
          :key="tab.value"
          :aria-pressed="status === tab.value"
          :class="{ active: status === tab.value }"
          @click="status = tab.value"
        >{{ tab.label }}</button>
      </div>
    </div>

    <div v-if="loading" class="state-msg">Loading…</div>
    <div v-else-if="error" class="state-msg error">
      {{ error }} <button class="retry" @click="reload">Retry</button>
    </div>
    <div v-else-if="projects.length === 0" class="state-msg">
      {{ filtered ? 'No projects match.' : 'No projects yet. Paste a YouTube link above to start one.' }}
    </div>
    <div v-else class="grid">
      <ProjectCard v-for="p in projects" :key="p.id" :project="p" />
    </div>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import ProjectCard from '../components/ProjectCard.vue'
import { useProjects } from '../composables/useProjects'

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
.page { max-width: 1040px; margin: 0 auto; padding: 40px 24px 120px; }
.page-head h1 { font-family: var(--font-serif); font-size: 28px; font-weight: 500; margin: 0; }
.sub { font-size: 13.5px; color: var(--ink-soft); margin: 6px 0 0; }
.controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 24px 0 20px; }
.search {
  flex: 1; min-width: 220px; font-family: var(--font-sans); font-size: 14px; color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px; background: #fff;
}
.status-tabs { display: flex; gap: 4px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 3px; }
.status-tabs button {
  border: none; background: none; font-family: var(--font-sans); font-size: 13px; color: var(--ink-soft);
  padding: 6px 12px; border-radius: 6px; cursor: pointer;
}
.status-tabs button.active { background: var(--accent); color: #fff; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px; }
.state-msg { font-size: 13.5px; color: var(--ink-soft); padding: 24px 0; }
.state-msg.error { color: #9C3B14; }
.retry { margin-left: 8px; border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 3px 10px; cursor: pointer; }
</style>
