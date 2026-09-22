<template>
  <div class="page">
    <div class="empty-state">
      <div class="empty-title">Paste a YouTube podcast link above</div>
      <div class="empty-sub">
        Highlyte pulls the audio, transcribes it (Roman Urdu/Hindi + English friendly),
        and cuts out the meaningful moments.
      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  max-width: 760px;
  margin: 0 auto;
  padding: 40px 24px 160px;
}
.empty-state { text-align: center; padding: 80px 24px; }
.empty-title { font-family: var(--font-serif); font-size: 20px; font-weight: 500; }
.empty-sub { margin-top: 10px; font-size: 13.5px; color: var(--ink-soft); max-width: 420px; margin-left: auto; margin-right: auto; }
</style>
