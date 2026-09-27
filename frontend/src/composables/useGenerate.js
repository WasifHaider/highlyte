import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useJobStore } from '../stores/jobStore'

// The language spoken in the video; the server checks it against the audio.
export const LANGUAGES = [
  { value: 'hinglish', label: 'Hinglish' },
  { value: 'english', label: 'English' },
]

// Paste a link, pick a language, start a job: shared by the top bar and the
// Home hero so both behave identically.
export function useGenerate() {
  const url = ref('')
  const language = ref('hinglish')
  const submitting = ref(false)
  // Own error state so the Home hero never shows a stale jobStore.error left
  // behind by a different page (e.g. JobView never clears jobStore.error).
  const error = ref(null)
  const router = useRouter()
  const jobStore = useJobStore()

  async function onGenerate() {
    if (!url.value || submitting.value) return
    submitting.value = true
    error.value = null
    try {
      const jobId = await jobStore.submitUrl(url.value, language.value)
      router.push({ name: 'job', params: { id: jobId } })
    } catch (e) {
      const message = e?.message || 'Failed to start job'
      error.value = message
      jobStore.error = message
    } finally {
      submitting.value = false
    }
  }

  return { url, language, submitting, error, LANGUAGES, onGenerate }
}
