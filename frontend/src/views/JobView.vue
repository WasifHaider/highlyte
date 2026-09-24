<template>
  <div class="page">
    <div v-if="jobStore.error" class="error-banner">{{ jobStore.error }}</div>

    <VideoCard
      v-if="jobStore.job?.videoMeta"
      :meta="jobStore.job.videoMeta"
      :status-note="statusNote"
    />

    <ProcessingSteps v-if="jobStore.isProcessing" :status="jobStore.job.status" :progress="jobStore.progress" />

    <ClipList v-if="jobStore.isDone" />
  </div>

  <ExportBar v-if="jobStore.isDone" />
</template>

<script setup>
import { computed, onMounted, onUnmounted, watch } from 'vue'
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
}

const statusNote = computed(() => {
  const status = jobStore.job?.status
  if (status === 'done') return `Processed · ${jobStore.clips.length} highlights found`
  return STATUS_NOTES[status] || ''
})

function startForId(id) {
  jobStore.currentJobId = id
  jobStore.job = null
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
</style>
