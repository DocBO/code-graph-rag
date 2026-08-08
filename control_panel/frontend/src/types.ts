export interface WatcherStatus {
  pid: number | null
  state: 'stopped' | 'starting' | 'running' | 'stopping' | 'error'
  update_in_progress: boolean
  last_update_at: number | null
  last_update_duration: number | null
  last_error: string | null
  log_count: number
}

export interface RepoInfo {
  path: string
  name: string
  debounce: number
  batch_size: number | null
  no_update: boolean
  watcher: WatcherStatus
}

export interface McpStatus {
  pid: number | null
  state: 'stopped' | 'starting' | 'running' | 'stopping' | 'error'
  repo_path: string | null
  url: string
  last_error: string | null
  log_count: number
}

export interface ControlConfig {
  project_root: string
  memgraph: { host: string; port: number }
  mcp: { host: string; port: number; path: string }
  default_debounce: number
  default_batch_size: number
}

export interface StatusResponse {
  repos: RepoInfo[]
  mcp: McpStatus
  config: ControlConfig
}
