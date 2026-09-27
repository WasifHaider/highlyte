# UI redesign: minimal teal (design)

The user approved seven Superdesign pages on 2026-09-27 ("nothing to tweak").
This spec makes those pages the visual source of truth for restyling the Vue
app in `frontend/`. Behaviour does not change: the same data, endpoints, store
actions and messages.

## Sources

- Design system: `.superdesign/design-system.md`. It holds the tokens, type
  scale, spacing, components and the minimal, calm direction.
- Approved pages. These are static HTML exports; Tailwind classes show the
  exact sizes and colours.

| Page | File | Vue |
|---|---|---|
| Clips (job done) | `2026-09-27-ui-redesign/clips.html` | JobView, ClipList, ClipCard, TrimControls, CaptionEditor, StyleAllBar, ExportBar |
| Job processing | `2026-09-27-ui-redesign/processing.html` | JobView, VideoCard, ProcessingSteps |
| Home | `2026-09-27-ui-redesign/home.html` | HomeView, ProjectCard |
| Projects | `2026-09-27-ui-redesign/projects.html` | ProjectsView, ProjectCard |
| Team | `2026-09-27-ui-redesign/team.html` | TeamView |
| Log in / Sign up | `2026-09-27-ui-redesign/login.html`, `signup.html` | LoginView, SignupView, styles/auth.css |

The mock data in the HTML (names, images, numbers, Unsplash photos, icons) is
illustration only. The app keeps showing real data.

## Decisions

| Question | Decision |
|---|---|
| CSS approach | Plain CSS with the design-system tokens as CSS variables, plus a small shared set of primitives in `style.css`. No Tailwind or other new dependency, because the app has none today and the pages are small. |
| Fonts | Public Sans (400/500/600) and Sora 600 for the wordmark. Drop Newsreader. |
| Icons | No icon library. Use a few inline SVGs where the design shows one (check, chevron, download, close, spinner, alert). Plain text elsewhere. |
| Clip editing | Progressive disclosure, as in `clips.html`. A card shows the preview, the Trim row, meta, QA chips, the first caption line, the reason, an Edit button, and Swap scene / Regenerate / SRT. **Edit** opens a right-side panel holding the hook title, show-hook, layout, captions preset, caption position, accent and the caption editor for that clip. One clip is edited at a time, and the edited card gets the teal 2px border. Below 1024px the panel becomes a full-screen sheet. |
| Style all | Behind a quiet "Style all" button in the grid header; opens the existing StyleAllBar fields inline under the header. |
| Export bar | Floating pill at the bottom centre, as in the design: selected count, Download zip, "Render & export". |
| Top bar link input | Shown on every signed-in page except Home, whose hero carries the input. Both use one shared generate composable. |
| Processing page | Quiet video row, a four-step list and plain failure panels, as in `processing.html`. The existing states are kept: `failed`, `selection_failed` with Retry selection, language note and selection note. |
| Scope | Restyle only. The pending/disabled rules, messages and store behaviour from piece 3a stay exactly as they are. |

## Constraints

- Must work at 375px wide, in a single column.
- Clip previews stay 9:16.
- Keep the real logo (`/logo-mark.svg`) and the "Highlyte" wordmark.
- No dark mode.
- The user checks everything in the browser; the check here is `cd frontend && npm run build`.
