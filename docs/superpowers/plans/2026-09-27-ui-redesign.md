# UI Redesign (minimal teal) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the Vue app in `frontend/` to match the seven approved Superdesign pages without changing behaviour.

**Architecture:** Design tokens and a small set of shared primitives (buttons, inputs, chips, cards, segmented control) live in `frontend/src/style.css`. Each view and component then switches its scoped CSS and markup to those primitives, using the approved HTML page as the visual reference. The one structural change is on the clips page: per-clip style and caption editing moves from each card into a single right-side edit panel, driven by `editingClipId` in the job store.

**Tech Stack:** Vue 3 (`<script setup>`, scoped CSS), Pinia, Vite. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-27-ui-redesign-design.md` (approved pages in `docs/superpowers/specs/2026-09-27-ui-redesign/*.html`, tokens in `.superdesign/design-system.md`)

## Global Constraints

- Branch `hinglish-v1`. **Never push.** Never `git stash`, `git reset` or `git commit --amend`. Never stage `renderer/package-lock.json`. Never kill or stop processes, never start dev servers, never enter passwords.
- Every commit message ends with a blank line then exactly: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- Check after every task: `cd frontend && npm run build`. It must succeed with no new warnings besides the existing chunk-size notice. There is no frontend test harness; do not add one.
- Behaviour does not change. Keep every store call, prop, emit, `:disabled`/`:title` rule and user-facing message exactly as it is today, including all piece-3a pending/disabled rules and messages ("Another clip is being replaced. Wait for it to finish.", "No other moments left to swap in.", "Re-run the video to trim this clip.", "Swapping in another moment…", "Regenerating this clip…").
- No new npm dependencies. No Tailwind. No icon library: use inline SVG for the few icons the design shows.
- Tokens are verbatim from the design system: `--bg #FFFFFF`, `--bg-subtle #F7F6F2`, `--surface #FFFFFF`, `--border #E6E6E1`, `--ink #14201F`, `--ink-soft #5B6664`, `--ink-faint #9AA3A1`, `--accent #004741`, `--accent-hover #00362F`, `--accent-soft rgba(0,71,65,0.08)`, `--danger #B42318`, `--danger-soft #FEF3F2`, `--warning #B54708`, `--warning-soft #FFFAEB`.
- Type: Public Sans 400/500/600. Wordmark Sora 600. Scale: page title 22/28 600, section 15/22 600, body 14/20, meta 12.5/18. Times and scores use `font-variant-numeric: tabular-nums`.
- Radius 8px for inputs and buttons, 12px for cards, 999px for chips. Buttons and inputs are 36px high (the compact 28–32px ones in the design stay compact). No shadow heavier than `0 1px 2px rgba(0,0,0,.04)`, except the floating export pill and the edit sheet.
- Max content width 1120px, centred, 24px side padding (16px under 640px). Must work at 375px wide. Clip previews stay 9:16.
- Plain-language sentence-case labels, no emoji.
- The mock content in the design HTML (names, Unsplash photos, numbers) is illustration only. Render real data.

## File map

| File | Status | Responsibility |
|---|---|---|
| `frontend/index.html` | modify | fonts (drop Newsreader) |
| `frontend/src/style.css` | modify | tokens and shared primitives |
| `frontend/src/composables/useGenerate.js` | create | shared link → job submission (TopBar and Home hero) |
| `frontend/src/components/TopBar.vue` | modify | new top bar; hides the link input on Home |
| `frontend/src/stores/jobStore.js` | modify | `editingClipId`, `captionDrafts`, open/close editor |
| `frontend/src/components/ClipEditPanel.vue` | create | right-side edit panel / mobile sheet |
| `frontend/src/views/JobView.vue`, `components/ClipList.vue`, `ClipCard.vue`, `TrimControls.vue`, `CaptionEditor.vue`, `StyleAllBar.vue`, `ExportBar.vue` | modify | clips page |
| `frontend/src/components/VideoCard.vue`, `ProcessingSteps.vue` | modify | processing page |
| `frontend/src/views/HomeView.vue`, `ProjectsView.vue`, `components/ProjectCard.vue` | modify | home, projects |
| `frontend/src/views/TeamView.vue` | modify | team |
| `frontend/src/views/LoginView.vue`, `SignupView.vue`, `styles/auth.css` | modify | auth |

---

### Task 1: Tokens, fonts, shared primitives, top bar

**Files:**
- Modify: `frontend/index.html`, `frontend/src/style.css`, `frontend/src/components/TopBar.vue`
- Create: `frontend/src/composables/useGenerate.js`

**Interfaces:**
- Produces:
  - CSS classes `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.btn-sm`, `.input`, `.select`, `.chip`, `.chip-warning`, `.card`, `.segmented`, `.segmented button[aria-pressed="true"]`, `.page`, `.field-label`, `.muted`, `.faint`, `.tabular`, `.danger-note`, `.warning-note`, `.subtle-note`.
  - `useGenerate() → { url: Ref<string>, language: Ref<string>, submitting: Ref<boolean>, LANGUAGES, onGenerate(): Promise<void> }`.
  - `@keyframes softPulse` and `@keyframes spin` in style.css.

- [ ] **Step 1: Fonts.** In `frontend/index.html`, replace the Google Fonts link with:

```html
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600&family=Sora:wght@600&display=swap" rel="stylesheet" />
```

- [ ] **Step 2: Tokens and primitives.** Replace `frontend/src/style.css`. Keep the existing `dotPulse`, `wavePulse` and `toastIn` keyframes at the end, because components still use them.

```css
/* Highlyte design tokens: minimal teal (.superdesign/design-system.md). */
:root {
  --bg: #FFFFFF;
  --bg-subtle: #F7F6F2;
  --surface: #FFFFFF;
  --border: #E6E6E1;
  --ink: #14201F;
  --ink-soft: #5B6664;
  --ink-faint: #9AA3A1;
  --accent: #004741;
  --accent-hover: #00362F;
  --accent-soft: rgba(0,71,65,0.08);
  --accent-text: #004741;
  --danger: #B42318;
  --danger-soft: #FEF3F2;
  --warning: #B54708;
  --warning-soft: #FFFAEB;
  --font-sans: 'Public Sans', sans-serif;
  --font-brand: 'Sora', sans-serif;
  --radius: 8px;
  --radius-card: 12px;
  --ease: 140ms ease-out;
}

* { box-sizing: border-box; }

html, body, #app {
  margin: 0;
  min-height: 100%;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 20px;
}

a { color: var(--accent); }
.tabular { font-variant-numeric: tabular-nums; }
.muted { color: var(--ink-soft); }
.faint { color: var(--ink-faint); }

.page { max-width: 1120px; margin: 0 auto; padding: 32px 24px 96px; }
@media (max-width: 640px) { .page { padding: 24px 16px 96px; } }
.page-title { font-size: 22px; line-height: 28px; font-weight: 600; margin: 0; }
.section-title { font-size: 15px; line-height: 22px; font-weight: 600; margin: 0; }
.field-label { font-size: 12.5px; font-weight: 500; color: var(--ink); }

.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  height: 36px; padding: 0 14px; border-radius: var(--radius); border: 1px solid transparent;
  font: 600 13.5px/1 var(--font-sans); cursor: pointer; text-decoration: none;
  transition: background var(--ease), border-color var(--ease), color var(--ease);
}
.btn:disabled { cursor: not-allowed; opacity: .55; }
.btn-primary { background: var(--accent); color: #fff; }
.btn-primary:hover:not(:disabled) { background: var(--accent-hover); }
.btn-secondary { background: var(--surface); color: var(--ink); border-color: var(--border); }
.btn-secondary:hover:not(:disabled) { background: var(--bg-subtle); }
.btn-ghost { background: transparent; color: var(--ink-soft); }
.btn-ghost:hover:not(:disabled) { color: var(--ink); background: var(--bg-subtle); }
.btn-sm { height: 28px; padding: 0 8px; font-size: 12px; font-weight: 500; border-radius: 6px; }

.input, .select {
  height: 36px; padding: 0 12px; border: 1px solid var(--border); border-radius: var(--radius);
  background: #fff; color: var(--ink); font: 400 14px var(--font-sans); outline: none;
  transition: border-color var(--ease), box-shadow var(--ease);
}
.select { padding: 0 8px; }
.input:focus, .select:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.input:disabled, .select:disabled { background: var(--bg-subtle); color: var(--ink-faint); }

.chip {
  display: inline-flex; align-items: center; height: 22px; padding: 0 8px; border-radius: 999px;
  background: var(--bg-subtle); color: var(--ink-soft); font-size: 12px; white-space: nowrap;
}
.chip-warning { background: var(--warning-soft); color: var(--warning); }
.chip-accent { background: var(--accent-soft); color: var(--accent); }

.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-card); transition: border-color var(--ease); }
.card:hover { border-color: var(--ink-faint); }

.segmented { display: inline-flex; background: var(--bg-subtle); border: 1px solid var(--border); border-radius: var(--radius); padding: 2px; gap: 2px; }
.segmented button {
  border: 1px solid transparent; background: transparent; color: var(--ink-soft);
  font: 600 12.5px var(--font-sans); padding: 0 10px; height: 30px; border-radius: 6px; cursor: pointer;
}
.segmented button[aria-pressed="true"] { background: #fff; border-color: var(--border); color: var(--accent); }

.danger-note { background: var(--danger-soft); color: var(--danger); border-radius: var(--radius); padding: 8px 12px; font-size: 13px; }
.warning-note { background: var(--warning-soft); color: var(--warning); border-radius: var(--radius); padding: 8px 12px; font-size: 13px; }
.subtle-note { background: var(--bg-subtle); color: var(--ink-soft); border-radius: var(--radius); padding: 8px 12px; font-size: 12.5px; }

@keyframes softPulse { 0%,100% { opacity: 1; } 50% { opacity: .6; } }
@keyframes spin { to { transform: rotate(360deg); } }
```

- [ ] **Step 3: Shared generate composable.** Create `frontend/src/composables/useGenerate.js` by moving the generate logic out of TopBar.vue unchanged:

```js
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
```

- [ ] **Step 4: TopBar.** Restyle `frontend/src/components/TopBar.vue` to match the header in `docs/superpowers/specs/2026-09-27-ui-redesign/clips.html` (the `<!-- Top Bar -->` block):
  - 56px high, white, bottom hairline, sticky, inner row max 1120px.
  - Brand: the logo at 28px plus "Highlyte" in Sora 600 20px, ink colour.
  - Nav tabs: 13.5px/600, ink-soft; active tab accent text on the `--accent-soft` background, 8px radius. Keep the current active rules, including Projects staying active on `/jobs/*` and Team only for admins.
  - Link group: `input.input` with the right corners squared, then `.segmented` for the language (buttons with `aria-pressed`), then `.btn .btn-primary` "Generate" with the left corners squared. Hide the whole group when `route.name === 'home'`, and hide it below 1024px (as in the design, `hidden lg:flex`).
  - Account: `.btn .btn-secondary` showing the team name and an inline chevron SVG. The menu is a white card with the border, the email in `.faint` and a "Log out" ghost button.
  - Use `useGenerate()` for url, language, submitting and onGenerate. Keep `onLogout` exactly as it is.
  - Inline chevron SVG: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>`.

- [ ] **Step 5: Build.** Run `cd frontend && npm run build`. Expected: success.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html frontend/src/style.css frontend/src/composables/useGenerate.js frontend/src/components/TopBar.vue
git commit -m "Redesign tokens, shared primitives and top bar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Clips page: cards, grid header, notes, export pill

**Files:**
- Modify: `frontend/src/views/JobView.vue` (done state only), `frontend/src/components/ClipList.vue`, `ClipCard.vue`, `TrimControls.vue`, `StyleAllBar.vue`, `ExportBar.vue`, `frontend/src/stores/jobStore.js`

**Interfaces:**
- Consumes: Task 1 primitives.
- Produces (jobStore, used by Task 3):
  - state `editingClipId: null` and `captionDrafts: {}` (clipId → words array or absent)
  - actions `openEditor(clipId)`, `closeEditor()`, `setCaptionDraft(clipId, words)`; `words === null` deletes the entry.

- [ ] **Step 1: Store.** In `frontend/src/stores/jobStore.js`, add `editingClipId: null,` and `captionDrafts: {},` to `state`. Add these actions next to `toggleClip`:

```js
    openEditor(clipId) {
      this.editingClipId = clipId
    },
    closeEditor() {
      if (this.editingClipId) delete this.captionDrafts[this.editingClipId]
      this.editingClipId = null
    },
    // The caption editor's unsaved text, so the clip's card preview can
    // show it live while the editor sits in the side panel.
    setCaptionDraft(clipId, words) {
      if (words) this.captionDrafts[clipId] = words
      else delete this.captionDrafts[clipId]
    },
```

  In `refresh()`, when the job being loaded has a different id from the current one (look for where `currentJobId` changes), also reset `editingClipId = null` and `captionDrafts = {}`.

- [ ] **Step 2: ClipCard.** Rework `frontend/src/components/ClipCard.vue` to the card in `clips.html` (`<!-- Clip 1 -->` to `<!-- Clip 3 -->`):
  - Outer element `.card` with no padding and overflow hidden. It gets a 2px `--accent` border when `jobStore.editingClipId === clip.id`.
  - Preview: 9:16 black box. `previewSpec` now uses `jobStore.captionDrafts[clip.id]` in place of the local `draftWords`; remove `draftWords`. The existing "No vertical preview…" message sits centred on a `--bg-subtle` fill, 12px faint text. While `clip.pendingAction` is set, draw an overlay: a white 40% wash, `animation: softPulse 1.6s infinite`, a 22px accent spinner SVG with `animation: spin 1s linear infinite`, and the existing pending text in a white pill. The text stays "Swapping in another moment…" / "Regenerating this clip…" exactly.
  - Body padding 14px, gap 10px, in this order:
    1. TrimControls, if `clip.spec`.
    2. The meta row: the checkbox (16px, 4px radius; checked is accent-filled with a white check SVG), the range `startLabel–endLabel` at 12.5px ink-soft tabular, and the duration at 11px faint tabular.
    3. The quoted first caption line at 13px ink-soft, one line with ellipsis, then the reason at 12px faint.
    4. Chips: QA flags as `.chip .chip-warning`, the tag as `.chip`, and the virality score right-aligned at 12px/600 ink-soft tabular, formatted as today.
    5. `clip-snippet`: drop it from the card. The first caption line replaces it, as in the design.
    6. Edit button: full-width `.btn .btn-secondary .btn-sm`, labelled "Edit". While this card is being edited it reads "Editing" on the accent-soft background with accent text. Click → `jobStore.editingClipId === clip.id ? jobStore.closeEditor() : jobStore.openEditor(clip.id)`. Disabled while `clip.pendingAction`. Hidden when `!clip.spec`.
    7. Actions row: Swap scene and Regenerate as `.btn .btn-secondary .btn-sm` with the existing `:disabled`/`:title`/`@click`, and "SRT" as a ghost link on the right with a download SVG, keeping `:href="clipSrtUrl(clip.id)" download`.
    8. `actionError` in `.danger-note` with an alert SVG.
    9. The render status block. Keep its logic and restyle it: 12.5px, a 4px progress bar on `--bg-subtle` with an accent fill; "Download mp4" is an accent link; the failed state uses `.danger-note` plus a `.btn-ghost .btn-sm` "Retry".
  - Move the hook title, show-hook, layout, captions, caption position, accent, the `wordsApprox` note and CaptionEditor OUT of the card. Task 3 puts them in the panel. Remove the now-unused imports and functions (`LAYOUTS`, `PRESETS`, `layoutAllowed`, `CaptionEditor`, `set`, `snippet`) only if nothing in the card still uses them.
  - Keep QA_LABELS, firstCaptionLine, anyPending, swap/regenerate computed and the `toggle` emit exactly as they are.
  - SVGs to use:
    - check: `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>`
    - download: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3v12m0 0 5-5m-5 5-5-5M5 21h14"/></svg>`
    - spinner: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>`
    - alert: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>`

- [ ] **Step 3: TrimControls.** Restyle `frontend/src/components/TrimControls.vue` to the Trim block in `clips.html`. Keep all logic.
  - Header row: a "TRIM" label (11px/500, uppercase, 0.05em tracking, ink-soft). On the right, the length at 12px tabular ink, then a "Reset" accent text link when `clip.boundsEdited`.
  - Two rows, Start and End: a 36px-wide faint label, then four `.btn .btn-secondary .btn-sm` buttons (◀ Sentence, −0.5 s, +0.5 s, Sentence ▶) with the existing disabled/title logic.
  - A bottom hairline under the block.
  - The v1 message "Re-run the video to trim this clip." shows as 12px faint text with the same bottom hairline.
  - At 375px the four buttons may wrap. They must not overflow the card.

- [ ] **Step 4: ClipList and StyleAllBar.**
  - Grid header as in `clips.html`: the select-all checkbox (same look as the card checkbox) + "Highlights" (14px/600) on the left. On the right, a `.btn-ghost .btn-sm` "Style all" that toggles a local `showStyleAll` ref, rendered only when `hasVerticalClips`.
  - When `showStyleAll` is on, render `<StyleAllBar />` under the header. Restyle it as a `--bg-subtle` panel, 12px radius, 16px padding. The fields use `.field-label`, `.select`, a colour input in a bordered 36px box, and the checkbox; "Apply to all" is `.btn .btn-primary .btn-sm`; the hint is 12.5px faint. Keep its logic.
  - Grid: `display: grid; gap: 24px; grid-template-columns: repeat(3, minmax(0, 1fr));` with 2 columns under 1024px and 1 under 640px.

- [ ] **Step 5: JobView done state.** In `frontend/src/views/JobView.vue`:
  - Use the `.page` container.
  - `error-banner` becomes `.danger-note`, `selection-note` becomes `.subtle-note` (inline-block, 32px bottom margin) and `lang-note` becomes `.subtle-note`.
  - Wrap the main column and a slot for the panel in a flex row, so Task 3 can add `<ClipEditPanel />` beside it: `<div class="job-layout"><div class="job-main">…existing content…</div></div>`, where `.job-layout { display: flex; }` and `.job-main { flex: 1; min-width: 0; }`.
  - VideoCard's look is restyled in Task 4. Do not touch it here.

- [ ] **Step 6: ExportBar.** Restyle `frontend/src/components/ExportBar.vue` as the floating pill in `clips.html`: fixed, bottom 24px, horizontally centred, white, border, `box-shadow: 0 4px 12px rgba(0,0,0,.08)`, 999px radius, 10px/16px padding.
  - Contents: the selection label (13.5px/500), a 1×16px border divider, "Download zip" as a ghost text button (only when `zipUrl`), and "Render & export" as an accent pill button (32px high, 999px radius).
  - Keep the label, `canExport`, the title and the "Rendering not configured" text logic.
  - At 375px the pill fits within 16px side margins, and the zip text may shorten to "Zip".

- [ ] **Step 7: Build.** `cd frontend && npm run build`. Expected: success.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/stores/jobStore.js frontend/src/views/JobView.vue frontend/src/components/ClipList.vue frontend/src/components/ClipCard.vue frontend/src/components/TrimControls.vue frontend/src/components/StyleAllBar.vue frontend/src/components/ExportBar.vue
git commit -m "Redesign the clips grid, cards and export bar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Clips page: edit side panel

**Files:**
- Create: `frontend/src/components/ClipEditPanel.vue`
- Modify: `frontend/src/views/JobView.vue`, `frontend/src/components/CaptionEditor.vue`

**Interfaces:**
- Consumes: `jobStore.editingClipId`, `openEditor`, `closeEditor`, `setCaptionDraft`, `updateStyle` (Task 2); `LAYOUTS`, `PRESETS`, `layoutAllowed` from `../utils/clipStyle`; `toClipTime` from `@renderer/lib/timeline`.

- [ ] **Step 1: ClipEditPanel.** Create `frontend/src/components/ClipEditPanel.vue` from the `<!-- Right Side Edit Panel -->` block in `clips.html`.
  - `const clip = computed(() => jobStore.clips.find(c => c.id === jobStore.editingClipId))`. Render nothing when there is no clip or when the clip has no `spec`.
  - Desktop (≥1024px): `aside` 320px wide, left hairline, white, `position: sticky; top: 56px; height: calc(100vh - 56px); overflow-y: auto`, 24px padding.
  - Under 1024px: a fixed full-screen sheet (`inset: 0`, white, z-index above the export pill, `overflow-y: auto`) with the same content.
  - Header: "Edit clip" (15px/600) plus the clip's range as a faint tabular subtitle, and a close button (x SVG) → `jobStore.closeEditor()`. Escape also closes it.
  - Content, moved from the old card with the same bindings, `set()` → `jobStore.updateStyle(clip.id, patch)` and the same `:disabled="!!clip.pendingAction"` rules:
    - Hook title input (`.input`, maxlength 80) and the Show hook title checkbox.
    - A 2×2 grid: Layout select, including the `layoutAllowed(l.value, clipTime.reframe)` option disabling and the " (auto)" suffix; Captions select; Position select (disabled when layout is split); Accent colour input in a bordered 36px box with the hex shown in 12px mono ink-soft.
    - The `wordsApprox` note "Approximate caption sync" in 12px faint.
    - A hairline.
    - CaptionEditor with the same props as before (`clip-id`, `words`, `edited`, `start`/`end` for v2, `revision`, `pending`), wrapped in the `controls-disabled` div while pending (keep its comment), and `@draft="w => jobStore.setCaptionDraft(clip.id, w)"`.
  - When the edited clip's `revision` changes or it gets a `pendingAction`, clear its draft: `jobStore.setCaptionDraft(id, null)`. CaptionEditor closes itself in those cases already.
  - x SVG: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>`

- [ ] **Step 2: CaptionEditor restyle.** Restyle `frontend/src/components/CaptionEditor.vue` to the `<!-- Caption Editor -->` block in `clips.html`. Change styling only; the logic is untouched.
  - A "Captions" label (12.5px/500) with the edited/approx status on the right in 11px faint.
  - Line rows: the time at 11.5px faint tabular, 40px wide, then a 28px `.input`-styled text field at 13px.
  - Scroll area max 240px.
  - "Save changes" as an accent-soft button (accent text, 32px), "Reset" as a ghost button, and errors in `.danger-note`.
  - The closed state keeps its current "Edit captions" affordance, styled as `.btn .btn-secondary .btn-sm`.

- [ ] **Step 3: Mount the panel.** In `JobView.vue`, render `<ClipEditPanel v-if="jobStore.isDone" />` inside `.job-layout` after `.job-main`. Call `jobStore.closeEditor()` in `onBeforeUnmount`, and when the route's job id changes if JobView already watches it.

- [ ] **Step 4: Build.** `cd frontend && npm run build`. Expected: success.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ClipEditPanel.vue frontend/src/views/JobView.vue frontend/src/components/CaptionEditor.vue
git commit -m "Move clip style and caption editing into a side panel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Job processing page

**Files:**
- Modify: `frontend/src/components/VideoCard.vue`, `frontend/src/components/ProcessingSteps.vue`, `frontend/src/views/JobView.vue` (failure panels only)

- [ ] **Step 1: VideoCard.** Restyle to the quiet video row in `clips.html` (`<!-- Video Header -->`) and the compact card in `processing.html`.
  - An 80×45 thumbnail, 4px radius, hairline border. Keep the no-image fallback, but make it a `--bg-subtle` box with a faint play triangle.
  - Title 15px/600 with ellipsis. Meta at 12.5px ink-soft: `channel · durationLabel`.
  - `statusNote` at 12.5px ink-soft, with an accent-coloured clip count if the note already contains it. Otherwise show it plainly. Do not change how `statusNote` is built.
- [ ] **Step 2: ProcessingSteps.** Restyle to the step list in `processing.html`. Keep the same statuses and progress logic.
  - Rows are 44px high with 12px gaps.
  - A 20px state marker: done is an accent circle with a white check; active is an accent ring with `softPulse`; pending is a faint ring.
  - Labels are 14px: ink when active or done, faint when pending. Progress text sits on the right at 12.5px ink-soft tabular.
  - Under the list, the line "You can leave this page; we will keep working." in 12.5px faint. Add it only if ProcessingSteps has no equivalent line already.
  - Map the labels to the existing step keys, keeping the existing label texts.
- [ ] **Step 3: Failure panels.** In `JobView.vue`, restyle the `selection-failed` block as in `processing.html`: `.card` with 20px padding; the title at 15px/600; the message at 14px ink-soft; the sub line at 12.5px faint; "Retry selection" as `.btn .btn-primary`. Keep its logic and texts. Restyle the job `failed` error display the same way with `.danger-note`, if JobView shows one.
- [ ] **Step 4: Build**, then **Step 5: Commit** with message "Redesign the processing state" and the trailer. Stage only the three files.

---

### Task 5: Home, Projects, ProjectCard

**Files:**
- Modify: `frontend/src/views/HomeView.vue`, `frontend/src/views/ProjectsView.vue`, `frontend/src/components/ProjectCard.vue`

**Interfaces:**
- Consumes: `useGenerate()` and `LANGUAGES` (Task 1).

- [ ] **Step 1: Home hero.** Restyle `HomeView.vue` to `home.html`.
  - A centred hero with generous whitespace: title "Turn a podcast into vertical clips" (28px/600 desktop, 22px mobile) and a one-line ink-soft subtitle, taken from the existing hero-sub text shortened to one sentence: "Paste a YouTube link. Highlyte transcribes it and cuts the best moments into captioned vertical clips."
  - The generate form, max 560px: a wide `.input` "Paste a YouTube link", the `.segmented` language control and the `.btn-primary` "Generate" (label "Starting…" while submitting), all wired to `useGenerate()`. Enter submits.
  - Show `jobStore.error` in `.danger-note` under the form if it is set.
  - Stacked at 375px.
  - "Recent projects" section: the section title plus a "View all" ghost link to `/projects`, and the existing loading/error/retry states restyled as muted text and `.btn-ghost`. The grid of ProjectCards uses 4 columns desktop, 2 tablet, 1 mobile. Keep the `useProjects` logic.
- [ ] **Step 2: ProjectCard.** Restyle to the cards in `home.html` / `projects.html`.
  - `.card` with overflow hidden.
  - A 16:9 thumbnail with a `--bg-subtle` fallback.
  - 12px body: title 14px/600 clamped to 2 lines, channel at 12.5px ink-soft, then relative date and clip count in 12px faint tabular. The status chip is `.chip`, or `.chip-warning` for failed.
  - Hover darkens the border only. Keep the link target and the data helpers.
- [ ] **Step 3: Projects.** Restyle `ProjectsView.vue` to `projects.html`.
  - `.page`, a "Projects" page title, the grid as on Home (3 columns desktop).
  - The empty state: centred "No projects yet" plus a `.btn-primary` "Paste a link" going to `/`.
  - Add the search input from the design ONLY if ProjectsView already has search or filter logic. Otherwise leave it out: no new behaviour.
  - Keep the loading and error states, restyled.
- [ ] **Step 4: Build**, **Step 5: Commit** "Redesign home and projects" with the trailer. Stage only the three files.

---

### Task 6: Team page

**Files:**
- Modify: `frontend/src/views/TeamView.vue`

- [ ] **Step 1:** Restyle to `team.html`. Keep all logic, API calls and texts.
  - `.page`, a "Team" page title.
  - The members list as a table with hairline row separators and no outer box: name 14px/500, email ink-soft, role `.chip` (accent chip for Admin), joined date faint tabular. Keep the existing per-row actions, restyled as ghost buttons.
  - The "Invite someone" form row: email `.input`, role `.select`, `.btn-primary` send button, and the existing success/error messages as `.subtle-note` / `.danger-note`.
  - "Pending invites" as the same kind of list, with revoke as `.btn-ghost .btn-sm`.
  - Keep the existing labels where they differ from the mock.
  - At 375px the table becomes stacked rows: name and email on one line, role and date on the next.
- [ ] **Step 2: Build**, **Step 3: Commit** "Redesign the team page" with the trailer.

---

### Task 7: Log in and Sign up

**Files:**
- Modify: `frontend/src/styles/auth.css`, `frontend/src/views/LoginView.vue`, `frontend/src/views/SignupView.vue`

- [ ] **Step 1:** Restyle to `login.html` / `signup.html`. Keep all logic, fields and texts.
  - A white page with a centred card, max 360px, 1px border, 12px radius, 32px/28px padding.
  - The logo (32px) and the Sora "Highlyte" wordmark centred on top.
  - Title 22px/600 centred, in Public Sans, not serif.
  - Fields with `.field-label` and `.input` at full width.
  - A full-width `.btn-primary` submit button.
  - Errors in `.danger-note`, notes at 12.5px faint, and the switch line at 13px ink-soft with an accent 600 link.
  - Remove `--font-serif` usage.
- [ ] **Step 2: Build**, then check that no file under `frontend/src` still uses `--font-serif` or `Newsreader`: `grep -rn "font-serif\|Newsreader" frontend/src frontend/index.html` should print nothing.
- [ ] **Step 3: Commit** "Redesign log in and sign up" with the trailer.

---

## After all tasks

- Final whole-branch review over this plan's range.
- Ask the user to check in the browser: every page at desktop width and at 375px; the clips page edit panel (open, switch clips, close, Escape, mobile sheet); trim, swap and regenerate states; export pill; the processing and failed states.
