<template>
  <div class="page">
    <div v-if="jobStore.error" class="error-banner">{{ jobStore.error }}</div>

    <VideoCard
      v-if="jobStore.job?.videoMeta"
      :meta="jobStore.job.videoMeta"
      :status-note="statusNote"
    />

    <ProcessingSteps v-if="jobStore.isProcessing" :status="jobStore.job.status" :progress="jobStore.progress" />
    <p v-if="jobStore.job?.languageNote" class="lang-note">{{ jobStore.job.languageNote }}</p>

    <div v-if="jobStore.selectionFailed" class="selection-failed">
      <p class="sf-title">Clip selection didn't finish</p>
      <p class="sf-msg">{{ jobStore.job.error }}</p>
      <p class="sf-sub">The transcript is saved, so a retry skips the download and transcription.</p>
      <button class="sf-retry" :disabled="retrying" @click="onRetry">
        {{ retrying ? 'Retrying…' : 'Retry selection' }}
      </button>
    </div>

    <p v-if="jobStore.isDone && jobStore.job?.selectionNote" class="selection-note">{{ jobStore.job.selectionNote }}</p>

    <ClipList v-if="jobStore.isDone" />
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
  jobStore.startPolling()
}

onMounted(() => {
  jobStore.loadHealth()
  startForId(props.id)
})
onUnmounted(() => jobStore.stopPolling())
watch(() => props.id, (newId) => startForId(newId))
</script>

<style scoped>
.page {
  max-width: 760px;
  margin: 0 auto;
  padding: 40px 24px 160px;
}
.error-banner {
  background: #FBEAE3;
  border: 1px solid #E8B79E;
  color: #9C3B14;
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 24px;
  font-size: 13.5px;
}
.lang-note { margin: 12px 0 0; font-size: 13px; color: var(--ink-soft); }
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
.selection-note {
  margin: 16px 0 0; padding: 10px 14px; border-radius: 8px; font-size: 13px;
  color: var(--ink-soft); background: var(--accent-soft);
}
</style>
