import type { ModelOptions, SemanticResult, StatusResponse } from './types'

const BASE = '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    let message = body || `${res.status} ${res.statusText}`
    try {
      const parsed: unknown = JSON.parse(body)
      if (typeof parsed === 'object' && parsed !== null) {
        const detail = (parsed as { detail?: unknown }).detail
        if (typeof detail === 'string') {
          message = detail
        } else if (Array.isArray(detail)) {
          const parts = detail
            .map((d) =>
              typeof d === 'object' && d !== null
                ? (d as { msg?: unknown }).msg
                : undefined,
            )
            .filter((m): m is string => typeof m === 'string')
          if (parts.length > 0) message = parts.join('; ')
        }
      }
    } catch {
      // non-JSON body: keep the raw text
    }
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

export function fetchStatus(): Promise<StatusResponse> {
  return req('/status')
}

export function fetchModels(): Promise<ModelOptions> {
  return req('/models')
}

export function updateModels(payload: {
  orchestrator: { provider: string; model: string }
  cypher: { provider: string; model: string }
}): Promise<{ orchestrator: { provider: string; model: string }; cypher: { provider: string; model: string } }> {
  return req('/config/models', { method: 'PUT', body: JSON.stringify(payload) })
}

export function addRepo(payload: {
  path: string
  debounce: number
  batch_size: number | null
  no_update: boolean
}) {
  return req('/repos', { method: 'POST', body: JSON.stringify(payload) })
}

export async function removeRepo(path: string) {
  const res = await req<{
    deleted: string
    cleanup?: Record<string, string>
  }>(`/repos/${encodeRepoPath(path)}`, { method: 'DELETE' })
  const failures = Object.entries(res.cleanup ?? {})
    .filter(([, v]) => v.startsWith('error'))
    .map(([k, v]) => `${k}: ${v}`)
  if (failures.length > 0) {
    throw new Error(
      `Repo removed, but database cleanup failed — ${failures.join('; ')}`,
    )
  }
  return res
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

export function runEmbeddingOnly(path: string) {
  return req(`/repos/${encodeRepoPath(path)}/embedding`, { method: 'POST' })
}

export function shutdownAll() {
  return req('/shutdown', { method: 'POST' })
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

export interface QueryResult {
  repo_path: string
  question: string
  search_depth: 'shallow' | 'normal' | 'deep'
  response: string
}

export function runQuery(
  repoPath: string,
  question: string,
  searchDepth: 'shallow' | 'normal' | 'deep' = 'normal',
  signal?: AbortSignal,
): Promise<QueryResult> {
  return req('/query', {
    method: 'POST',
    signal,
    body: JSON.stringify({
      repo_path: repoPath,
      question,
      search_depth: searchDepth,
    }),
  })
}

export function runSemantic(
  repoPath: string,
  searchPhrase: string,
  topN: number,
): Promise<SemanticResult> {
  return req('/semantic', {
    method: 'POST',
    body: JSON.stringify({
      repo_path: repoPath,
      search_phrase: searchPhrase,
      top_n: topN,
    }),
  })
}

function encodeRepoPath(path: string): string {
  return encodeURIComponent(path)
}
