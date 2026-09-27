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
  const router = useRouter()
  const jobStore = useJobStore()

  async function onGenerate() {
    if (!url.value || submitting.value) return
    submitting.value = true
    try {
      const jobId = await jobStore.submitUrl(url.value, language.value)
      router.push({ name: 'job', params: { id: jobId } })
    } catch (e) {
      jobStore.error = e?.message || 'Failed to start job'
    } finally {
      submitting.value = false
    }
  }

  return { url, language, submitting, LANGUAGES, onGenerate }
}
