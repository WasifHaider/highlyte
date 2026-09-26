# Pages (dependency trees, local imports only)

## HomeView
Entry: frontend/src/views/HomeView.vue
Dependencies:
- ../components/ProjectCard.vue
- ../composables/useProjects

## JobView
Entry: frontend/src/views/JobView.vue
Dependencies:
- ../stores/jobStore
- ../components/VideoCard.vue
- ../components/ProcessingSteps.vue
- ../components/ClipList.vue
- ../components/ExportBar.vue

## ProjectsView
Entry: frontend/src/views/ProjectsView.vue
Dependencies:
- ../components/ProjectCard.vue
- ../composables/useProjects

## TeamView
Entry: frontend/src/views/TeamView.vue
Dependencies:
- ../stores/authStore
- ../services/highlyteApi
- ../utils/time

## LoginView
Entry: frontend/src/views/LoginView.vue
Dependencies:
- ../stores/authStore
- ../services/highlyteApi
- ../utils/authRedirect

## SignupView
Entry: frontend/src/views/SignupView.vue
Dependencies:
- ../stores/authStore
- ../services/highlyteApi

## Component imports
- src/components/CaptionEditor.vue:
  - ../stores/jobStore
- src/components/ClipCard.vue:
  - ../stores/jobStore
  - ../services/highlyteApi
  - ./RemotionPreview.vue
  - ./CaptionEditor.vue
  - ../utils/clipStyle
- src/components/ClipList.vue:
  - ../stores/jobStore
  - ./ClipCard.vue
  - ./StyleAllBar.vue
- src/components/ExportBar.vue:
  - ../stores/jobStore
  - ../services/highlyteApi
- src/components/ProcessingSteps.vue:
- src/components/ProjectCard.vue:
  - ../utils/time
  - ../utils/projects
- src/components/RemotionPreview.vue:
- src/components/StyleAllBar.vue:
  - ../stores/jobStore
  - ../utils/clipStyle
- src/components/TopBar.vue:
  - ../stores/jobStore
  - ../stores/authStore
- src/components/VideoCard.vue:
