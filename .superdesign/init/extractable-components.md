# Extractable components

## Layout Components

## TopBar
- Source: `frontend/src/components/TopBar.vue`
- Category: layout
- Description: Sticky top bar: logo mark + "Highlyte", tabs (Home / Projects / Team for admins), inline YouTube URL input, language toggle (Hinglish / English), Generate button, account menu (team name, email, log out)
- Extractable props: activeTab (string: "home" | "projects" | "team", default "home"), showTeamTab (boolean, default true)
- Hardcoded: logo `/logo-mark.svg`, tab labels, placeholder "Paste a YouTube link", language labels, all CSS

## AuthCard
- Source: `frontend/src/views/LoginView.vue` + `frontend/src/styles/auth.css`
- Category: layout
- Description: Centered 380px card with logo, serif title, email/password fields, submit, switch link
- Extractable props: mode ("login" | "signup")
- Hardcoded: copy, CSS

## Basic Components

## ProjectCard
- Source: `frontend/src/components/ProjectCard.vue`
- Category: basic
- Description: Past-video card: YouTube thumbnail, title, channel, duration, clip count, relative time, status
- Extractable props: status (string), clipCount (number)
- Hardcoded: layout, CSS

## VideoCard
- Source: `frontend/src/components/VideoCard.vue`
- Category: basic
- Description: Job header: thumbnail + title + channel + duration + status note
- Extractable props: statusNote (string)

## ProcessingSteps
- Source: `frontend/src/components/ProcessingSteps.vue`
- Category: basic
- Description: Vertical stepper: downloading → transcribing → analyzing → preparing, with percent + live note
- Extractable props: activeStep (string), percent (number)

## ClipCard
- Source: `frontend/src/components/ClipCard.vue`
- Category: basic
- Description: 9:16 Remotion preview + details: select checkbox, time range, duration, tag chip, virality x/10, hook title input, layout/caption/position/accent controls, caption editor, render/download
- Extractable props: selected (boolean), captionsEdited (boolean)

## ExportBar
- Source: `frontend/src/components/ExportBar.vue`
- Category: basic
- Description: Fixed bottom bar: selected count, export/download selected
- Extractable props: selectedCount (number)
