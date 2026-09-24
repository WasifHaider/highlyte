import { onUnmounted, ref, watch } from 'vue'
import { listProjects } from '../services/highlyteApi'
import { isProcessing } from '../utils/projects'

const REFRESH_MS = 3000

// Loads the project list for the given query params and keeps refreshing it
// every few seconds while any listed video is still processing, so progress
// bars move without a page reload. `params` is a getter; the list reloads
// whenever what it returns changes.
export function useProjects(params) {
  const projects = ref([])
  const loading = ref(true)
  const error = ref(null)
  let timer = null
  let latest = 0

  async function load() {
    const request = ++latest
    clearTimeout(timer)
    try {
      const data = await listProjects(params())
      if (request !== latest) return // a newer search replaced this one
      projects.value = data
      error.value = null
      if (data.some(isProcessing)) timer = setTimeout(load, REFRESH_MS)
    } catch {
      if (request === latest) error.value = "Couldn't load projects"
    } finally {
      if (request === latest) loading.value = false
    }
  }

  watch(params, load, { immediate: true, deep: true })
  onUnmounted(() => {
    latest++
    clearTimeout(timer)
  })

  return { projects, loading, error, reload: load }
}
