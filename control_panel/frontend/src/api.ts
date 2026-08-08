import type { StatusResponse } from './types'

const BASE = '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export function fetchStatus(): Promise<StatusResponse> {
  return req('/status')
}

export function addRepo(payload: {
  path: string
  debounce: number
  batch_size: number | null
  no_update: boolean
}) {
  return req('/repos', { method: 'POST', body: JSON.stringify(payload) })
}

export function removeRepo(path: string) {
  return req(`/repos/${encodeRepoPath(path)}`, { method: 'DELETE' })
}

export function startWatcher(path: string, fullScan = false) {
  return req(`/repos/${encodeRepoPath(path)}/watch/start`, {
    method: 'POST',
    body: JSON.stringify({ full_scan: fullScan }),
  })
}

export function stopWatcher(path: string) {
  return req(`/repos/${encodeRepoPath(path)}/watch/stop`, { method: 'POST' })
}

export function repoLogs(path: string, limit = 250): Promise<string[]> {
  return req(`/repos/${encodeRepoPath(path)}/logs?limit=${limit}`)
}

export function mcpStart(repoPath?: string) {
  return req('/mcp/start', {
    method: 'POST',
    body: JSON.stringify({ repo_path: repoPath ?? null }),
  })
}

export function mcpStop() {
  return req('/mcp/stop', { method: 'POST' })
}

export function mcpLogs(limit = 250): Promise<string[]> {
  return req(`/mcp/logs?limit=${limit}`)
}

function encodeRepoPath(path: string): string {
  return encodeURIComponent(path)
}
