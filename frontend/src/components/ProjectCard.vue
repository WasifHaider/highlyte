<template>
  <div class="project-wrap">
  <router-link :to="{ name: 'job', params: { id: project.id } }" class="card card-interactive project-card">
    <div class="thumb">
      <img v-if="project.thumbnailUrl && !imgFailed" :src="project.thumbnailUrl" alt="" loading="lazy" @error="imgFailed = true" />
      <div v-else class="thumb-placeholder" aria-hidden="true"><span class="play"></span></div>
      <span v-if="project.durationLabel" class="duration tabular">{{ project.durationLabel }}</span>
    </div>
    <div class="body">
      <div class="title">{{ project.videoTitle || 'Untitled video' }}</div>
      <div v-if="project.videoChannel" class="channel muted">{{ project.videoChannel }}</div>
      <div class="status-row">
        <template v-if="processing">
          <span class="chip">Processing</span>
          <span class="note muted">{{ project.progress?.note || '' }}</span>
        </template>
        <span v-else-if="project.status === 'done'" class="chip chip-accent">
          Done · {{ project.clipCount }} clip{{ project.clipCount === 1 ? '' : 's' }}
        </span>
        <span
          v-else
          class="chip"
          :class="project.status === 'selection_failed' ? 'chip-warning' : 'chip-danger'"
          :title="project.error || ''"
        >{{ project.status === 'selection_failed' ? 'Needs retry' : 'Failed' }}</span>
        <button
          v-if="!processing && project.status !== 'done'"
          type="button"
          class="btn btn-secondary btn-sm retry-btn"
          :disabled="retrying"
          @click.prevent.stop="retry"
        ><BusyLabel :busy="retrying" idle="Retry" busy-text="Retrying" spinner-size="12" /></button>
        <span class="time faint tabular">{{ relativeTime(project.createdAt) }}</span>
      </div>
      <div v-if="retryError" class="danger-note retry-error" role="alert">{{ retryError }}</div>
      <div v-if="processing && project.progress?.percent != null" class="progress-bar">
        <div class="progress-bar-fill" :style="{ width: Math.min(100, project.progress.percent) + '%' }"></div>
      </div>
    </div>
  </router-link>
  <button
    type="button"
    class="delete-btn"
    :disabled="processing"
    :title="processing ? 'Wait for processing to finish to delete' : 'Delete project'"
    aria-label="Delete project"
    @click="askDelete"
  >
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14M10 11v6m4-6v6"/></svg>
  </button>
  <ConfirmDialog
    :open="confirming"
    title="Delete this project?"
    confirm-label="Delete project"
    busy-label="Deleting…"
    danger
    :busy="deleting"
    :error="deleteError"
    @confirm="confirmDelete"
    @cancel="confirming = false"
  >
    “{{ project.videoTitle || 'Untitled video' }}” and its {{ project.clipCount }} clip{{ project.clipCount === 1 ? '' : 's' }} will be permanently deleted, including any exports. This can't be undone.
  </ConfirmDialog>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { relativeTime } from '../utils/time'
import { isProcessing } from '../utils/projects'
import { deleteProject, retryProject, retrySelection } from '../services/highlyteApi'
import ConfirmDialog from './ui/ConfirmDialog.vue'
import BusyLabel from './ui/BusyLabel.vue'

const props = defineProps({ project: { type: Object, required: true } })
const emit = defineEmits(['deleted', 'retried'])

const retrying = ref(false)
const retryError = ref('')

// A failed run starts over as a new video; a failed clip selection just
// re-picks clips from the saved transcript. Either way the list reloads and
// the card shows progress again.
async function retry() {
  retrying.value = true
  retryError.value = ''
  try {
    if (props.project.status === 'selection_failed') await retrySelection(props.project.id)
    else await retryProject(props.project.id)
    emit('retried', props.project.id)
  } catch (e) {
    retryError.value = e?.response?.data?.detail || "Couldn't retry. Try again."
  } finally {
    retrying.value = false
  }
}

const confirming = ref(false)
const deleting = ref(false)
const deleteError = ref('')

function askDelete() {
  deleteError.value = ''
  confirming.value = true
}
async function confirmDelete() {
  deleting.value = true
  deleteError.value = ''
  try {
    await deleteProject(props.project.id)
    confirming.value = false
    emit('deleted', props.project.id)
  } catch (e) {
    deleteError.value = e?.response?.data?.detail || "Couldn't delete the project. Try again."
  } finally {
    deleting.value = false
  }
}
const imgFailed = ref(false)
const processing = computed(() => isProcessing(props.project))
</script>

<style scoped>
.project-wrap { position: relative; }
.delete-btn {
  position: absolute; top: 8px; right: 8px; width: 30px; height: 30px; border-radius: 8px; border: 0;
  display: flex; align-items: center; justify-content: center; cursor: pointer;
  background: rgba(0,0,0,.6); color: #fff; opacity: 0; transition: opacity var(--ease), background var(--ease);
}
.project-wrap:hover .delete-btn, .delete-btn:focus-visible { opacity: 1; }
.delete-btn:hover:not(:disabled) { background: var(--danger); }
.delete-btn:disabled { cursor: not-allowed; }
@media (hover: none) { .delete-btn { opacity: 1; } }
.project-card { display: flex; flex-direction: column; overflow: hidden; text-decoration: none; color: var(--ink); }
.project-card:hover { border-color: var(--accent); }
.thumb { position: relative; aspect-ratio: 16 / 9; background: var(--bg-subtle); }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb-placeholder { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
.play { width: 0; height: 0; border-top: 12px solid transparent; border-bottom: 12px solid transparent; border-left: 18px solid var(--ink-faint); }
.duration {
  position: absolute; right: 8px; bottom: 8px; background: rgba(0,0,0,.75); color: #fff;
  font-size: 11.5px; padding: 2px 6px; border-radius: 4px;
}
.body { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 4px; }
.title { font-weight: 600; font-size: 14px; line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.channel { font-size: 12.5px; }
.status-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; font-size: 12px; }
.time { margin-left: auto; }
.retry-btn { height: 24px; padding: 0 10px; font-size: 12px; }
.retry-error { margin-top: 6px; font-size: 12px; padding: 6px 10px; }
.progress-bar { height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; margin-top: 6px; }
.progress-bar-fill { height: 100%; background: var(--accent); transition: width .3s ease; }
</style>
