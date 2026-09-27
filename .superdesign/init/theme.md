# Theme

## Part 1 — Token summary
Colors (`:root` in src/style.css, no dark mode):
- --bg #F0EDE4 (sand), --surface #FFFFFF, --border #D8DCD4
- --ink #004741 (deep teal "Cyprus"), --ink-soft rgba(0,71,65,.62), --ink-faint rgba(0,71,65,.4)
- --accent #004741, --accent-soft rgba(0,71,65,.1), --accent-text #004741
- error: bg #FBEAE3, border #E8B79E, text #9C3B14
Fonts: --font-serif 'Newsreader' (headings), --font-sans 'Public Sans' (body/UI), 'Sora' 600 (logo). Loaded from Google Fonts in index.html.
Type: headings 24px serif 500; body 14px; small 12.5–13px.
Radius: cards 14px, inputs/buttons 8px. Spacing: ad hoc px (gap 5–14, padding 9–32).
Shadows: none/minimal. Breakpoints: ad hoc in components.
Animations: dotPulse, wavePulse, toastIn.

## Part 2 — Raw sources

### `frontend/src/style.css`

```css
/* Highlyte design tokens — Cyprus (deep teal) / Sand theme */
:root {
  --bg: #F0EDE4;
  --surface: #FFFFFF;
  --border: #D8DCD4;
  --ink: #004741;
  --ink-soft: rgba(0,71,65,0.62);
  --ink-faint: rgba(0,71,65,0.4);
  --accent: #004741;
  --accent-soft: rgba(0,71,65,0.1);
  --accent-text: #004741;
  --font-serif: 'Newsreader', serif;
  --font-sans: 'Public Sans', sans-serif;
}

* { box-sizing: border-box; }

html, body, #app {
  margin: 0;
  min-height: 100%;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-sans);
}

@keyframes dotPulse { 0%,100%{transform:scale(1);opacity:1;} 50%{transform:scale(1.18);opacity:.65;} }
@keyframes wavePulse { 0%,100%{opacity:.55;} 50%{opacity:1;} }
@keyframes toastIn { from{opacity:0;transform:translate(-50%,8px);} to{opacity:1;transform:translate(-50%,0);} }

```

### `frontend/index.html`

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Public+Sans:wght@400;500;600;700&family=Sora:wght@600&display=swap" rel="stylesheet" />
    <title>Highlyte</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>

```
