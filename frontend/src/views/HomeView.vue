<template>
  <div class="page">
    <section class="hero">
      <h1 class="hero-title">Turn a podcast into vertical clips</h1>
      <p class="hero-sub">
        Paste a YouTube link. Highlyte transcribes it and cuts the best moments into captioned vertical clips.
      </p>

      <div class="hero-form">
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
      </div>
      <Transition name="fade">
        <p v-if="generateError" class="danger-note hero-error">{{ generateError }}</p>
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
      <TransitionGroup v-else name="rise" tag="div" class="grid">
        <ProjectCard v-for="p in projects" :key="p.id" :project="p" />
      </TransitionGroup>
    </section>
  </div>
</template>

<script setup>
import ProjectCard from '../components/ProjectCard.vue'
import SkeletonCard from '../components/ui/SkeletonCard.vue'
import BusyLabel from '../components/ui/BusyLabel.vue'
import { useProjects } from '../composables/useProjects'
import { useGenerate } from '../composables/useGenerate'

const RECENT_LIMIT = 6
const HOME_SKELETON_COUNT = 4
const { projects, loading, error, reload } = useProjects(() => ({ limit: RECENT_LIMIT }))
const { url, language, submitting, error: generateError, LANGUAGES, onGenerate } = useGenerate()
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
