<template>
  <router-link :to="{ name: 'job', params: { id: project.id } }" class="project-card">
    <div class="thumb">
      <img v-if="project.thumbnailUrl && !imgFailed" :src="project.thumbnailUrl" alt="" loading="lazy" @error="imgFailed = true" />
      <div v-else class="thumb-placeholder" aria-hidden="true"><span class="play"></span></div>
      <span v-if="project.durationLabel" class="duration">{{ project.durationLabel }}</span>
    </div>
    <div class="body">
      <div class="title">{{ project.videoTitle || 'Untitled video' }}</div>
      <div v-if="project.videoChannel" class="channel">{{ project.videoChannel }}</div>
      <div class="status-row">
        <template v-if="processing">
          <span class="badge processing">Processing</span>
          <span class="note">{{ project.progress?.note || '' }}</span>
        </template>
        <span v-else-if="project.status === 'done'" class="badge done">
          Done · {{ project.clipCount }} clip{{ project.clipCount === 1 ? '' : 's' }}
        </span>
        <span v-else class="badge failed" :title="project.error || ''">Failed</span>
        <span class="time">{{ relativeTime(project.createdAt) }}</span>
      </div>
      <div v-if="processing && project.progress?.percent != null" class="progress-bar">
        <div class="progress-bar-fill" :style="{ width: Math.min(100, project.progress.percent) + '%' }"></div>
      </div>
    </div>
  </router-link>
</template>

<script setup>
import { computed, ref } from 'vue'
import { relativeTime } from '../utils/time'
import { isProcessing } from '../utils/projects'

const props = defineProps({ project: { type: Object, required: true } })
const imgFailed = ref(false)
const processing = computed(() => isProcessing(props.project))
</script>

<style scoped>
.project-card {
  display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden; text-decoration: none; color: var(--ink);
  transition: border-color .15s ease, transform .15s ease;
}
.project-card:hover { border-color: var(--accent); transform: translateY(-1px); }
.thumb { position: relative; aspect-ratio: 16 / 9; background: var(--accent-soft); }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb-placeholder { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
.play { width: 0; height: 0; border-top: 12px solid transparent; border-bottom: 12px solid transparent; border-left: 18px solid var(--ink-faint); }
.duration {
  position: absolute; right: 8px; bottom: 8px; background: rgba(0,0,0,.75); color: #fff;
  font-size: 11.5px; padding: 2px 6px; border-radius: 4px;
}
.body { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 4px; }
.title { font-weight: 600; font-size: 14.5px; line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.channel { font-size: 12.5px; color: var(--ink-soft); }
.status-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; font-size: 12px; }
.badge { font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.badge.processing { background: #FFF4D6; color: #8A5A00; }
.badge.done { background: var(--accent-soft); color: var(--accent-text); }
.badge.failed { background: #FBEAE3; color: #9C3B14; }
.note { color: var(--ink-soft); }
.time { color: var(--ink-faint); margin-left: auto; }
.progress-bar { height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; margin-top: 6px; }
.progress-bar-fill { height: 100%; background: var(--accent); transition: width .3s ease; }
</style>
