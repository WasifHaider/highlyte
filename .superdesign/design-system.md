# Highlyte design system (minimal redesign)

## Product
Highlyte turns a YouTube podcast link into 5–8 vertical 9:16 clips with animated
Roman-script captions, for Hinglish (Indian Hindi + English), Pakistani Urdu +
English and English podcasts. Users are small content teams.

Jobs to be done:
1. Paste a link, pick the spoken language (Hinglish / English), press Generate.
2. Watch progress (downloading → transcribing → analyzing → preparing).
3. Review the clips: live 9:16 preview, edit caption lines, tweak hook title,
   layout, caption style, accent colour; select clips; export / download.
4. Find past videos (Projects); admins manage the team (Team).

Pages: Home (`/`), Clips / job (`/jobs/:id`), Projects (`/projects`),
Team (`/team`, admin), Log in (`/login`), Sign up (`/signup`).

## Direction: minimal, simple, calm
- Content first: the 9:16 clip previews are the hero; chrome recedes.
- Few surfaces: a white page, content grouped by whitespace, not boxes.
  Use a border only where a boundary is functional (inputs, cards on the
  clip grid). No heavy shadows; at most `0 1px 2px rgba(0,0,0,.04)`.
- One accent (brand teal) used sparingly: primary buttons, active tab,
  focus rings, selected state. Everything else is neutral.
- Progressive disclosure: secondary controls (layout, caption position,
  accent colour, caption editor) sit behind a quiet "Edit" / "Style"
  toggle instead of all showing at once.
- Plain language labels, sentence case, no emoji, no decorative icons.
- Generous spacing, clear hierarchy by size and weight, not colour.

## Colour tokens (keep brand, simplify)
- `--bg` #FFFFFF (page)
- `--bg-subtle` #F7F6F2 (quiet panels, hover rows; a lighter nod to the old sand)
- `--surface` #FFFFFF
- `--border` #E6E6E1
- `--ink` #14201F (body text, near-black with a teal tint)
- `--ink-soft` #5B6664 (secondary text)
- `--ink-faint` #9AA3A1 (placeholders, meta)
- `--accent` #004741 (brand teal: primary button, active states)
- `--accent-hover` #00362F
- `--accent-soft` rgba(0,71,65,0.08) (selected chip / active tab background)
- `--danger` #B42318, `--danger-soft` #FEF3F2
- `--warning` #B54708, `--warning-soft` #FFFAEB (QA flags such as "Low confidence — check captions")
No dark mode in this round.

## Typography
- One family: 'Public Sans' (400/500/600). Drop the Newsreader serif.
- Logo wordmark: 'Sora' 600, as today.
- Scale: page title 22/28 600; section title 15/22 600; body 14/20 400;
  small/meta 12.5/18 400. Numbers (times, scores) use tabular figures.

## Spacing, radius, layout
- 4px base grid: 4, 8, 12, 16, 24, 32, 48.
- Radius: 8px inputs/buttons, 12px cards, 999px chips.
- Max content width 1120px, centred, 24px side padding (16px on mobile).
- Top bar: 56px, white, bottom hairline border.

## Components
- Primary button: teal fill, white text, 36px high, 8px radius.
  Secondary: white, 1px border, ink text. Ghost: text only, ink-soft.
- Input: 36px, 1px border, 8px radius, teal 2px focus ring (accent-soft halo).
- Segmented control (language, layout): neutral track `--bg-subtle`, selected
  segment white with hairline border.
- Chip: 999px radius, 12px text, neutral `--bg-subtle`; warning chips use
  `--warning-soft` / `--warning`.
- Card (clip, project): white, 1px border, 12px radius, no shadow; hover
  darkens the border only.

## Motion
Subtle only: 120–160ms ease-out on hover/focus/toggle; progress indicators may
pulse softly. No bouncing, no parallax.

## Constraints
- Keep the real logo mark (`/logo-mark.svg`) + "Highlyte" wordmark.
- Clip previews stay 9:16.
- Must work at 375px wide (single column).
