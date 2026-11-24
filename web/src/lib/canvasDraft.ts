import { apiRequest } from './http'
import type { WorkflowDefinition } from './types'

const PREFIX = 'ai_power_canvas_draft:'

export function localDraftKey(scope: string): string {
  return `${PREFIX}${scope}`
}

export function readLocalDraft(key: string): WorkflowDefinition | null {
  try {
    const raw = window.localStorage.getItem(key)
    if (raw === null) return null
    const parsed = JSON.parse(raw) as WorkflowDefinition
    if (!Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges)) return null
    return parsed
  } catch {
    return null
  }
}

export function writeLocalDraft(key: string, definition: WorkflowDefinition): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(definition))
  } catch {
    // Storage may be unavailable (private mode/quota); autosave is best-effort.
  }
}

export function clearLocalDraft(key: string): void {
  try {
    window.localStorage.removeItem(key)
  } catch {
    // Ignore storage failures.
  }
}

export async function saveWorkflowDraft(
  workflowId: string,
  definition: WorkflowDefinition,
): Promise<void> {
  await apiRequest(`/workflows/${workflowId}/draft`, {
    method: 'PUT',
    body: { definition },
  })
}

export async function clearWorkflowDraft(workflowId: string): Promise<void> {
  await apiRequest(`/workflows/${workflowId}/draft`, { method: 'DELETE' })
}