<template>
  <div class="page">
    <div class="job-layout">
      <div class="job-main">
        <div v-if="jobStore.error" class="danger-note">{{ jobStore.error }}</div>

        <VideoCard
          v-if="jobStore.job?.videoMeta"
          :meta="jobStore.job.videoMeta"
          :status-note="statusNote"
        />

        <ProcessingSteps v-if="jobStore.isProcessing" :status="jobStore.job.status" :progress="jobStore.progress" />
        <p v-if="jobStore.job?.languageNote" class="subtle-note lang-note">{{ jobStore.job.languageNote }}</p>

        <div v-if="jobStore.selectionFailed" class="selection-failed">
          <p class="sf-title">Clip selection didn't finish</p>
          <p class="sf-msg">{{ jobStore.job.error }}</p>
          <p class="sf-sub">The transcript is saved, so a retry skips the download and transcription.</p>
          <button class="sf-retry" :disabled="retrying" @click="onRetry">
            {{ retrying ? 'Retrying…' : 'Retry selection' }}
          </button>
        </div>

        <p v-if="jobStore.isDone && jobStore.job?.selectionNote" class="subtle-note selection-note">{{ jobStore.job.selectionNote }}</p>

        <ClipList v-if="jobStore.isDone" />
      </div>

      <ClipEditPanel v-if="jobStore.isDone" />
    </div>
  </div>

  <ExportBar v-if="jobStore.isDone" />
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useJobStore } from '../stores/jobStore'
import VideoCard from '../components/VideoCard.vue'
import ProcessingSteps from '../components/ProcessingSteps.vue'
import ClipList from '../components/ClipList.vue'
import ExportBar from '../components/ExportBar.vue'
import ClipEditPanel from '../components/ClipEditPanel.vue'

const props = defineProps({ id: { type: String, required: true } })
const jobStore = useJobStore()

const STATUS_NOTES = {
  queued: 'Queued…',
  transcribing: 'Transcribing episode…',
  analyzing: 'Analyzing for highlights…',
  preparing: 'Preparing clips…',
  done: null,
  error: 'Something went wrong',
  selection_failed: 'Clip selection needs a retry',
}

const statusNote = computed(() => {
  const status = jobStore.job?.status
  if (status === 'done') return `Processed · ${jobStore.clips.length} highlights found`
  return STATUS_NOTES[status] || ''
})

const retrying = ref(false)
async function onRetry() {
  retrying.value = true
  try {
    await jobStore.retrySelection()
  } finally {
    retrying.value = false
  }
}

function startForId(id) {
  jobStore.currentJobId = id
  jobStore.job = null
  // Matches submitUrl's reset so switching projects doesn't carry over the
  // previous project's error banner, clip selection, or render state.
  jobStore.error = null
  jobStore.selected = {}
  jobStore.renders = {}
  jobStore.editingClipId = null
  jobStore.captionDrafts = {}
  jobStore.startPolling()
}

onMounted(() => {
  jobStore.loadHealth()
  startForId(props.id)
})
onUnmounted(() => {
  jobStore.stopPolling()
  jobStore.closeEditor()
})
watch(() => props.id, (newId) => startForId(newId))
</script>

<style scoped>
.lang-note { margin: 12px 0 0; display: inline-block; }
.selection-failed {
  margin-top: 24px; padding: 20px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--surface); display: flex; flex-direction: column; gap: 6px; align-items: flex-start;
}
.sf-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--ink); }
.sf-msg { margin: 0; font-size: 14px; color: var(--ink); }
.sf-sub { margin: 0 0 8px; font-size: 13px; color: var(--ink-soft); }
.sf-retry {
  border: none; border-radius: 8px; padding: 9px 16px; font-size: 14px; font-weight: 600;
  font-family: var(--font-sans); color: #fff; background: var(--accent); cursor: pointer;
}
.sf-retry:disabled { opacity: .6; cursor: default; }
.selection-note { margin: 0 0 32px; display: inline-block; }
.job-layout { display: flex; }
.job-main { flex: 1; min-width: 0; }
</style>
