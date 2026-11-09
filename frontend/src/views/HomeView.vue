<template>
  <div class="page">
    <section class="hero">
      <h1 class="hero-title">Turn a podcast into vertical clips</h1>
      <p class="hero-sub">
        Paste a YouTube link or upload a video. Highlyte transcribes it and cuts the best moments into captioned vertical clips.
      </p>

      <div
        class="hero-form"
        :class="{ 'drop-target': dragging }"
        @dragover.prevent="onDragOver"
        @dragleave="dragging = false"
        @drop.prevent="onDrop"
      >
        <input
          v-model="url"
          type="text"
          placeholder="Paste a YouTube link"
          class="input hero-input"
          @keyup.enter="onGenerate"
        />
        <div class="hero-controls">
          <div class="segmented" role="group" aria-label="Spoken language">
            <button
              v-for="opt in LANGUAGES"
              :key="opt.value"
              type="button"
              :aria-pressed="language === opt.value"
              @click="language = opt.value"
            >{{ opt.label }}</button>
          </div>
          <button class="btn btn-primary" :disabled="submitting || !url" @click="onGenerate">
            <BusyLabel :busy="submitting" idle="Generate" busy-text="Starting…" />
          </button>
        </div>
        <template v-if="upload.enabled">
          <div v-if="upload.active" class="upload-row" aria-live="polite">
            <div class="upload-head">
              <span class="upload-name">{{ upload.name }}</span>
              <span class="upload-stats tabular">{{ uploadStats }}</span>
              <button class="btn btn-ghost btn-sm" @click="upload.cancel()">Cancel</button>
            </div>
            <div class="progress-bar" role="progressbar" :aria-valuenow="Math.round(upload.percent)" aria-valuemin="0" aria-valuemax="100">
              <div class="progress-bar-fill" :style="{ width: upload.percent + '%' }"></div>
            </div>
          </div>
          <div v-else class="upload-cta">
            <span class="faint">or</span>
            <button class="btn btn-secondary btn-sm" :disabled="submitting" @click="fileInput.click()">Upload a video</button>
            <span class="faint upload-hint">MP4, MOV, MKV, WebM, up to 5 GB. You can drop it here too.</span>
          </div>
          <input ref="fileInput" type="file" :accept="UPLOAD_ACCEPT" class="visually-hidden" tabindex="-1" @change="onPick" />
        </template>
      </div>
      <Transition name="fade">
        <p v-if="generateError || upload.error" class="danger-note hero-error">{{ generateError || upload.error }}</p>
      </Transition>
    </section>

    <section v-if="loading || error || projects.length" class="recent">
      <div class="section-head">
        <h2 class="section-title">Recent projects</h2>
        <router-link to="/projects" class="btn btn-ghost btn-sm">View all</router-link>
      </div>
      <p v-if="error" class="muted state-msg">
        {{ error }} <button class="btn btn-ghost btn-sm" @click="reload">Retry</button>
      </p>
      <div v-else-if="loading" class="grid" aria-busy="true">
        <SkeletonCard v-for="i in HOME_SKELETON_COUNT" :key="i" variant="project" />
      </div>
      <TransitionGroup v-else name="rise" tag="div" class="grid" appear>
        <ProjectCard v-for="p in projects" :key="p.id" :project="p" @deleted="reload" @retried="reload" />
      </TransitionGroup>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import ProjectCard from '../components/ProjectCard.vue'
import SkeletonCard from '../components/ui/SkeletonCard.vue'
import BusyLabel from '../components/ui/BusyLabel.vue'
import { useProjects } from '../composables/useProjects'
import { useGenerate } from '../composables/useGenerate'
import { useUploadStore } from '../stores/uploadStore'
import { UPLOAD_ACCEPT } from '../services/uploader'

const RECENT_LIMIT = 6
const HOME_SKELETON_COUNT = 4
const { projects, loading, error, reload } = useProjects(() => ({ limit: RECENT_LIMIT }))
const { url, language, submitting, error: generateError, LANGUAGES, onGenerate } = useGenerate()

const router = useRouter()
const upload = useUploadStore()
const fileInput = ref(null)
const dragging = ref(false)
onMounted(() => upload.loadEnabled())

function formatBytes(n) {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`
  return `${(n / 1024 ** 2).toFixed(1)} MB`
}

const uploadStats = computed(() => {
  const pct = `${Math.floor(upload.percent)}%`
  return upload.bytesPerSecond ? `${pct} · ${formatBytes(upload.bytesPerSecond)}/s` : pct
})

async function startUpload(file) {
  if (!file || upload.active) return
  generateError.value = null
  const jobId = await upload.upload(file, language.value)
  if (jobId) router.push({ name: 'job', params: { id: jobId } })
}

function onPick(e) {
  const file = e.target.files?.[0]
  e.target.value = '' // so picking the same file again still fires change
  startUpload(file)
}

function onDragOver(e) {
  if (!upload.enabled || upload.active) return
  if (e.dataTransfer?.types?.includes('Files')) dragging.value = true
}

function onDrop(e) {
  dragging.value = false
  if (!upload.enabled) return
  startUpload(e.dataTransfer?.files?.[0])
}
</script>

<style scoped>
.hero { text-align: center; max-width: 720px; margin: 0 auto; padding: 40px 0 48px; }
.hero-title { font-size: 28px; font-weight: 600; letter-spacing: -0.01em; line-height: 1.25; margin: 0; }
.hero-sub { font-size: 14.5px; color: var(--ink-soft); margin: 12px auto 0; max-width: 480px; line-height: 1.5; }

.hero-form {
  margin: 32px auto 0; max-width: 560px; text-align: left;
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 16px; display: flex; flex-direction: column; gap: 14px;
}
.hero-input { width: 100%; }
.hero-controls { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.hero-error { max-width: 560px; margin: 12px auto 0; text-align: left; }
.hero-form { transition: border-color var(--ease), background var(--ease); }
.drop-target { border-color: var(--accent); border-style: dashed; background: var(--accent-soft); }
.upload-cta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding-top: 12px; border-top: 1px solid var(--border); }
.upload-hint { font-size: 12.5px; }
.upload-row { display: flex; flex-direction: column; gap: 8px; padding-top: 12px; border-top: 1px solid var(--border); }
.upload-head { display: flex; align-items: center; gap: 10px; min-width: 0; }
.upload-name { flex: 1; min-width: 0; font-size: 13.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.upload-stats { font-size: 12.5px; color: var(--ink-soft); flex-shrink: 0; }
.progress-bar { height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--accent); transition: width 300ms ease-out; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

.recent { margin-top: 56px; padding-top: 32px; border-top: 1px solid var(--border); }
.section-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 16px; }
.state-msg { padding: 24px 0; }
.grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }

@media (max-width: 1024px) { .grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
@media (max-width: 480px) {
  .hero-title { font-size: 22px; }
  .hero-controls { flex-direction: column; align-items: stretch; }
  .hero-controls .segmented { justify-content: center; }
}
</style>
