<template>
  <div class="page">
    <div class="hero">
      <div class="hero-title">Paste a YouTube podcast link above</div>
      <div class="hero-sub">
        Highlyte pulls the audio, transcribes it (Roman Urdu/Hindi + English friendly),
        and turns the best moments into vertical clips with captions.
      </div>
    </div>

    <section v-if="loading || error || projects.length" class="recent">
      <div class="section-head">
        <h2>Recent videos</h2>
        <router-link to="/projects" class="see-all">See all projects</router-link>
      </div>
      <div v-if="loading" class="state-msg">Loading…</div>
      <div v-else-if="error" class="state-msg error">
        {{ error }} <button class="retry" @click="reload">Retry</button>
      </div>
      <div v-else class="grid">
        <ProjectCard v-for="p in projects" :key="p.id" :project="p" />
      </div>
    </section>
  </div>
</template>

<script setup>
import ProjectCard from '../components/ProjectCard.vue'
import { useProjects } from '../composables/useProjects'

const RECENT_LIMIT = 6
const { projects, loading, error, reload } = useProjects(() => ({ limit: RECENT_LIMIT }))
</script>

<style scoped>
.page { max-width: 1040px; margin: 0 auto; padding: 40px 24px 120px; }
.hero { text-align: center; padding: 40px 24px 48px; }
.hero-title { font-family: var(--font-serif); font-size: 22px; font-weight: 500; }
.hero-sub { margin: 10px auto 0; font-size: 13.5px; color: var(--ink-soft); max-width: 460px; }
.section-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 16px; }
.section-head h2 { font-family: var(--font-serif); font-size: 22px; font-weight: 500; margin: 0; }
.see-all { font-size: 13px; font-weight: 600; color: var(--accent); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px; }
.state-msg { font-size: 13.5px; color: var(--ink-soft); padding: 24px 0; }
.state-msg.error { color: #9C3B14; }
.retry { margin-left: 8px; border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 3px 10px; cursor: pointer; }
</style>
