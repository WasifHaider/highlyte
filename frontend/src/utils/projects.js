// Mirrors backend/projects.py PROCESSING_STATUSES.
export const PROCESSING_STATUSES = ['queued', 'transcribing', 'analyzing', 'preparing']

export const isProcessing = (project) => PROCESSING_STATUSES.includes(project?.status)
