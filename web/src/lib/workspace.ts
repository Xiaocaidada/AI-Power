const STORAGE_KEY = 'ai_power_workspace'

let activeWorkspaceId: string | null = localStorage.getItem(STORAGE_KEY)

export function getActiveWorkspaceId(): string | null {
  return activeWorkspaceId
}

export function setActiveWorkspaceId(workspaceId: string | null): void {
  activeWorkspaceId = workspaceId
  if (workspaceId === null) localStorage.removeItem(STORAGE_KEY)
  else localStorage.setItem(STORAGE_KEY, workspaceId)
}