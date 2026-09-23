<template>
  <div class="page">
    <div class="page-head">
      <h1>Library</h1>
      <p class="sub">Every clip you've generated, grouped by video.</p>
    </div>

    <div v-if="loading" class="state-msg">Loading…</div>
    <div v-else-if="error" class="state-msg error">{{ error }}</div>
    <div v-else-if="groups.length === 0" class="state-msg">
      No clips yet — generate one from the home page.
    </div>

    <div v-else class="job-groups">
      <section v-for="group in groups" :key="group.jobId" class="job-group">
        <div class="job-head">
          <div class="job-head-main">
            <router-link
              v-if="group.jobId"
              :to="{ name: 'job', params: { id: group.jobId } }"
              class="job-title"
            >
              {{ group.videoTitle || 'Untitled video' }}
            </router-link>
            <span v-else class="job-title">{{ group.videoTitle || 'Untitled video' }}</span>
            <span v-if="group.videoChannel" class="job-channel">{{ group.videoChannel }}</span>
          </div>
          <div class="job-head-meta">
            <span>{{ group.clips.length }} clip{{ group.clips.length === 1 ? '' : 's' }}</span>
            <span>·</span>
            <span>{{ relativeTime(group.clips[0]?.createdAt) }}</span>
          </div>
        </div>

        <div class="clip-grid">
          <div v-for="clip in group.clips" :key="clip.id" class="clip-card">
            <video
              class="preview"
              :src="clipDownloadUrl(clip.downloadUrl)"
              preload="metadata"
              controls
            ></video>

            <div class="card-body">
              <div class="meta-row">
                <span class="range">{{ clip.startLabel }} – {{ clip.endLabel }}</span>
                <span class="duration">{{ clip.durationLabel }}</span>
                <span class="tag">{{ clip.tag }}</span>
              </div>

              <div class="snippet">"{{ snippet(clip.text) }}"</div>

              <div class="card-foot">
                <span class="storage-badge" :class="clip.storageProvider">
                  {{ clip.storageProvider === 'r2' ? 'R2' : 'Local' }}
                </span>
                <span class="created">{{ relativeTime(clip.createdAt) }}</span>
                <a class="download-link" :href="clipDownloadUrl(clip.downloadUrl)" download>Download</a>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { listAllClips, clipDownloadUrl } from '../services/highlyteApi'

const clips = ref([])
const loading = ref(true)
const error = ref(null)

// Clips come back newest-first, flat, across every job. Group them by
// jobId so the Library reads as "one section per video" instead of one
// undifferentiated wall of clips — group order follows each group's
// most recent clip, since that's the order the flat list already
// arrives in.
const groups = computed(() => {
  const byJob = new Map()
  for (const clip of clips.value) {
    const key = clip.jobId || clip.id
    if (!byJob.has(key)) {
      byJob.set(key, {
        jobId: clip.jobId,
        videoTitle: clip.videoTitle,
        videoChannel: clip.videoChannel,
        clips: [],
      })
    }
    byJob.get(key).clips.push(clip)
  }
  return [...byJob.values()]
})

function snippet(text) {
  const t = text || ''
  return t.length > 160 ? t.slice(0, 157) + '…' : t
}

function relativeTime(iso) {
  if (!iso) return ''
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.round(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return `${days}d ago`
}

onMounted(async () => {
  try {
    clips.value = await listAllClips()
  } catch (e) {
    error.value = e?.response?.data?.detail || e?.message || 'Failed to load clips'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.page {
  max-width: 1080px;
  margin: 0 auto;
  padding: 40px 24px 160px;
}
.page-head { margin-bottom: 28px; }
.page-head h1 {
  font-family: var(--font-serif);
  font-size: 26px;
  font-weight: 600;
  margin: 0;
}
.sub { margin: 6px 0 0; font-size: 13.5px; color: var(--ink-soft); }

.state-msg {
  text-align: center;
  padding: 80px 24px;
  font-size: 14px;
  color: var(--ink-soft);
}
.state-msg.error { color: #B4432E; }

.job-groups { display: flex; flex-direction: column; gap: 36px; }

.job-group { padding-top: 4px; }
.job-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding-bottom: 12px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
.job-head-main { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; min-width: 0; }
.job-title {
  font-family: var(--font-serif);
  font-size: 18px;
  font-weight: 600;
  color: var(--ink);
  text-decoration: none;
}
a.job-title:hover { color: var(--accent-text); }
.job-channel { font-size: 12.5px; color: var(--ink-soft); }
.job-head-meta { display: flex; gap: 6px; font-size: 12px; color: var(--ink-faint); flex-shrink: 0; }

.clip-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.clip-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.preview {
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #000;
  display: block;
}
.card-body { padding: 14px 16px 16px; }

.meta-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.range { font-family: monospace; font-size: 11.5px; color: var(--ink-soft); }
.duration { font-size: 10.5px; color: var(--ink-faint); }
.tag {
  background: var(--accent-soft);
  color: var(--accent-text);
  font-size: 10.5px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}

.snippet {
  margin-top: 8px;
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13.5px;
  line-height: 1.45;
  color: var(--ink);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-foot {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  color: var(--ink-faint);
}
.storage-badge {
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 6px;
  background: var(--border);
  color: var(--ink-soft);
}
.storage-badge.r2 { background: rgba(0,71,65,0.12); color: var(--accent-text); }
.created { flex: 1; }
.download-link { color: var(--accent-text); text-decoration: none; font-weight: 600; }
.download-link:hover { text-decoration: underline; }
</style>
