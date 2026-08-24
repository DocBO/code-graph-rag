export interface WatcherStatus {
  pid: number | null
  state: 'stopped' | 'starting' | 'running' | 'stopping' | 'error'
  update_in_progress: boolean
  last_update_at: number | null
  last_update_duration: number | null
  last_error: string | null
  log_count: number
  embedding_in_progress: boolean
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
  activity: 'stopped' | 'starting' | 'running' | 'stopping' | 'error' | 'idle' | 'busy' | 'stalled'
  active_requests: number
  last_request_at: number | null
  last_response_at: number | null
  last_activity_at: number | null
  repo_path: string | null
  url: string
  last_error: string | null
  log_count: number
}

export interface MemgraphHealth {
  at: number
  alive: boolean
  error: string | null
}

export interface ActiveModel {
  provider: string
  model: string
}

export interface ModelOption {
  provider: string
  models: string[]
}

export interface ModelOptions {
  providers: ModelOption[]
}

export interface ControlConfig {
  project_root: string
  memgraph: { host: string; port: number }
  mcp: { host: string; port: number; path: string }
  models: { orchestrator: ActiveModel; cypher: ActiveModel }
  default_debounce: number
  default_batch_size: number
}

export interface StatusResponse {
  repos: RepoInfo[]
  mcp: McpStatus
  memgraph: MemgraphHealth
  config: ControlConfig
}

export interface SemanticMatch {
  qualified_name: string | null
  type: string | null
  score: number | null
  filename: string | null
  start_line: number | null
  end_line: number | null
  snippet: string | null
}

export interface SemanticResult {
  repo_path: string
  search_phrase: string
  top_n: number
  matches: SemanticMatch[]
}
