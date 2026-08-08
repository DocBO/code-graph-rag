import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import {
  addRepo,
  fetchStatus,
  mcpLogs,
  mcpStart,
  mcpStop,
  removeRepo,
  repoLogs,
  startWatcher,
  stopWatcher,
} from './api'
import type { RepoInfo, StatusResponse } from './types'

type LampTone = 'off' | 'ok' | 'busy' | 'err'

function lampTone(state: string): LampTone {
  switch (state) {
    case 'running':
      return 'ok'
    case 'starting':
    case 'stopping':
      return 'busy'
    case 'error':
      return 'err'
    default:
      return 'off'
  }
}

function formatAgo(ts: number | null): string {
  if (!ts) return 'never'
  const secs = Math.max(0, Math.floor((Date.now() / 1000) - ts))
  if (secs < 5) return 'just now'
  if (secs < 60) return `${secs}s ago`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  return `${hrs}h ${mins % 60}m ago`
}

function StatusLamp({ tone, pulse = false }: { tone: LampTone; pulse?: boolean }) {
  return (
    <span
      className={`lamp lamp-${tone}${pulse ? ' lamp-pulse' : ''}`}
      aria-hidden
    />
  )
}

function WatcherBadge({ state, updating }: { state: string; updating: boolean }) {
  if (updating) {
    return (
      <span className="badge badge-updating">
        <span className="badge-spinner" /> UPDATING
      </span>
    )
  }
  return <span className={`badge badge-${state}`}>{state.toUpperCase()}</span>
}

interface RepoCardProps {
  repo: RepoInfo
  expanded: boolean
  logs: string[] | null
  loading: boolean
  onToggleLogs: () => void
  onStart: () => void
  onStartWithScan: () => void
  onStop: () => void
  onRemove: () => void
}

function RepoCard({
  repo,
  expanded,
  logs,
  loading,
  onToggleLogs,
  onStart,
  onStartWithScan,
  onStop,
  onRemove,
}: RepoCardProps) {
  const { watcher } = repo
  const tone = lampTone(watcher.state)
  const busy = watcher.state === 'starting' || watcher.state === 'stopping' || loading
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (expanded && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [expanded, logs])

  return (
    <article className="card" data-tone={tone}>
      <header className="card-head">
        <div className="card-ident">
          <StatusLamp tone={tone} pulse={watcher.update_in_progress} />
          <div className="card-title">
            <h3>{repo.name}</h3>
            <code className="card-path">{repo.path}</code>
          </div>
        </div>
        <div className="card-meta">
          <WatcherBadge state={watcher.state} updating={watcher.update_in_progress} />
          <span className="meta-item">
            <span className="meta-k">DEBOUNCE</span>
            {repo.debounce}s
          </span>
          <span className="meta-item">
            <span className="meta-k">BATCH</span>
            {repo.batch_size ?? 'default'}
          </span>
          <span className="meta-item">
            <span className="meta-k">INIT SCAN</span>
            {repo.no_update ? 'SKIP' : 'ON'}
          </span>
          <span className="meta-item">
            <span className="meta-k">LAST UPDATE</span>
            {formatAgo(watcher.last_update_at)}
            {watcher.last_update_duration
              ? ` (${watcher.last_update_duration.toFixed(1)}s)`
              : ''}
          </span>
        </div>
      </header>

      {watcher.last_error && (
        <div className="card-error">{watcher.last_error}</div>
      )}

      <footer className="card-actions">
        {watcher.state === 'running' || watcher.state === 'starting' ? (
          <button className="btn btn-stop" onClick={onStop} disabled={busy}>
            Stop watcher
          </button>
        ) : (
          <button className="btn btn-start" onClick={onStart} disabled={busy}>
            Start watcher
          </button>
        )}
        {watcher.state !== 'running' && watcher.state !== 'starting' && (
          <button
            className="btn btn-start btn-fullscan"
            onClick={onStartWithScan}
            disabled={busy}
            title="Start watcher with an initial full scan"
          >
            Start + full scan
          </button>
        )}
        <button
          className="btn btn-ghost"
          onClick={onToggleLogs}
          disabled={loading}
        >
          {expanded ? 'Hide logs' : `Logs${watcher.log_count ? ` (${watcher.log_count})` : ''}`}
        </button>
        <button className="btn btn-danger" onClick={onRemove} disabled={busy}>
          Remove
        </button>
      </footer>

      {expanded && (
        <pre className="logs" ref={logRef}>
          {logs && logs.length > 0 ? logs.join('\n') : '— no log lines yet —'}
        </pre>
      )}
    </article>
  )
}

function AddRepoForm({ onAdd }: { onAdd: () => void }) {
  const [path, setPath] = useState('')
  const [debounce, setDebounce] = useState('30')
  const [batchSize, setBatchSize] = useState('2000')
  const [noUpdate, setNoUpdate] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!path.trim()) return
    setBusy(true)
    setError(null)
    try {
      await addRepo({
        path: path.trim(),
        debounce: parseInt(debounce, 10) || 30,
        batch_size: batchSize.trim() ? parseInt(batchSize, 10) || null : null,
        no_update: noUpdate,
      })
      setPath('')
      onAdd()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card add-card">
      <header className="card-head">
        <div className="card-ident">
          <StatusLamp tone="off" />
          <div className="card-title">
            <h3>Register repository</h3>
            <code className="card-path">absolute path on this machine</code>
          </div>
        </div>
      </header>
      <div className="add-form">
        <input
          className="input input-path"
          placeholder="/home/you/code/my-repo"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
        />
        <label className="input-num">
          <span className="meta-k">DEBOUNCE (s)</span>
          <input
            type="number"
            min={1}
            value={debounce}
            onChange={(e) => setDebounce(e.target.value)}
          />
        </label>
        <label className="input-num">
          <span className="meta-k">BATCH SIZE</span>
          <input
            type="number"
            min={1}
            value={batchSize}
            onChange={(e) => setBatchSize(e.target.value)}
          />
        </label>
        <label className="input-check">
          <input
            type="checkbox"
            checked={noUpdate}
            onChange={(e) => setNoUpdate(e.target.checked)}
          />
          <span>Skip initial full scan</span>
        </label>
        <button className="btn btn-start" onClick={submit} disabled={busy || !path.trim()}>
          {busy ? 'Adding…' : 'Add repo'}
        </button>
      </div>
      {error && <div className="card-error">{error}</div>}
    </section>
  )
}

function McpPanel({
  status,
  repos,
  logs,
  onStart,
  onStop,
  onLogs,
}: {
  status: StatusResponse['mcp']
  repos: RepoInfo[]
  logs: string[] | null
  onStart: (repoPath: string | null) => void
  onStop: () => void
  onLogs: () => void
}) {
  const tone = lampTone(status.state)
  const [selected, setSelected] = useState<string>('')
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (logs && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs])

  const defaultRepo = repos[0]?.path ?? ''
  const effective = selected || defaultRepo

  return (
    <section className="card mcp-card" data-tone={tone}>
      <header className="card-head">
        <div className="card-ident">
          <StatusLamp tone={tone} pulse={status.state === 'starting'} />
          <div className="card-title">
            <h3>Unified MCP Server</h3>
            <code className="card-path">{status.url}</code>
          </div>
        </div>
        <div className="card-meta">
          <span className={`badge badge-${status.state}`}>{status.state.toUpperCase()}</span>
          <span className="meta-item">
            <span className="meta-k">PID</span>
            {status.pid ?? '—'}
          </span>
          <span className="meta-item">
            <span className="meta-k">DEFAULT REPO</span>
            <span className="meta-ellipsis">{status.repo_path ?? '—'}</span>
          </span>
        </div>
      </header>

      {status.last_error && <div className="card-error">{status.last_error}</div>}

      <footer className="card-actions">
        {status.state === 'running' || status.state === 'starting' ? (
          <button className="btn btn-stop" onClick={onStop} disabled={status.state === 'starting'}>
            Stop MCP
          </button>
        ) : (
          <>
            <select
              className="input mcp-select"
              value={effective}
              onChange={(e) => setSelected(e.target.value)}
            >
              {repos.length === 0 && <option value="">no repos registered</option>}
              {repos.map((r) => (
                <option key={r.path} value={r.path}>
                  {r.name} — {r.path}
                </option>
              ))}
            </select>
            <button
              className="btn btn-start"
              onClick={() => onStart(effective)}
              disabled={repos.length === 0}
            >
              Start MCP
            </button>
          </>
        )}
        <button className="btn btn-ghost" onClick={onLogs}>
          {logs ? 'Hide MCP logs' : 'MCP logs'}
        </button>
      </footer>

      {logs && <pre className="logs" ref={logRef}>{logs.join('\n')}</pre>}
    </section>
  )
}

export default function App() {
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [logs, setLogs] = useState<Record<string, string[] | null>>({})
  const [mcpLogsVisible, setMcpLogsVisible] = useState(false)
  const [loading, setLoading] = useState<Record<string, boolean>>({})

  const refresh = useCallback(async () => {
    try {
      setStatus(await fetchStatus())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 2500)
    return () => clearInterval(id)
  }, [refresh])

  const withLoading = async (key: string, fn: () => Promise<unknown>) => {
    setLoading((s) => ({ ...s, [key]: true }))
    try {
      await fn()
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading((s) => ({ ...s, [key]: false }))
    }
  }

  const toggleLogs = async (path: string) => {
    const isOpen = expanded[path]
    setExpanded((s) => ({ ...s, [path]: !isOpen }))
    if (!isOpen) {
      try {
        const lines = await repoLogs(path)
        setLogs((s) => ({ ...s, [path]: lines }))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    }
  }

  const toggleMcpLogs = async () => {
    const isOpen = !mcpLogsVisible
    setMcpLogsVisible(isOpen)
    if (isOpen) {
      try {
        const lines = await mcpLogs()
        setLogs((s) => ({ ...s, __mcp__: lines }))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    }
  }

  const repos = status?.repos ?? []
  const cfg = status?.config

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            ⌖
          </span>
          <h1>
            GRAPH-CODE<span className="brand-sub">/WATCHER CONTROL</span>
          </h1>
        </div>
        <div className="topbar-right">
          <span className="sys chip">
            <span className="meta-k">MEMGRAPH</span>
            {cfg ? `${cfg.memgraph.host}:${cfg.memgraph.port}` : '…'}
          </span>
          <span className="sys chip">
            <span className="meta-k">PROJECT</span>
            <span className="meta-ellipsis">{cfg?.project_root ?? '…'}</span>
          </span>
          <span className={`conn${error ? ' conn-err' : ''}`}>
            <StatusLamp tone={error ? 'err' : 'ok'} pulse={!status} />
            {error ? 'API ERROR' : status ? 'LINKED' : 'CONNECTING…'}
          </span>
        </div>
      </header>

      {error && <div className="banner">{error}</div>}

      <main className="layout">
        <McpPanel
          status={status?.mcp ?? { state: 'stopped', pid: null, repo_path: null, url: 'http://127.0.0.1:8765/mcp', last_error: null, log_count: 0 }}
          repos={repos}
          logs={mcpLogsVisible ? (logs.__mcp__ ?? null) : null}
          onStart={(p) => withLoading('mcp', () => mcpStart(p || undefined))}
          onStop={() => withLoading('mcp', () => mcpStop())}
          onLogs={toggleMcpLogs}
        />

        <AddRepoForm onAdd={refresh} />

        <section className="repo-section">
          <header className="section-head">
            <h2>REPOSITORIES</h2>
            <span className="section-count">{repos.length} REGISTERED</span>
          </header>
          {repos.length === 0 && (
            <p className="empty">
              No repositories registered. Add one above to start watching and
              ingesting a codebase.
            </p>
          )}
          <div className="repo-list">
            {repos.map((repo) => (
              <RepoCard
                key={repo.path}
                repo={repo}
                expanded={!!expanded[repo.path]}
                logs={expanded[repo.path] ? (logs[repo.path] ?? null) : null}
                loading={!!loading[repo.path]}
                onToggleLogs={() => toggleLogs(repo.path)}
                onStart={() => withLoading(repo.path, () => startWatcher(repo.path))}
                onStartWithScan={() =>
                  withLoading(repo.path, () => startWatcher(repo.path, true))
                }
                onStop={() => withLoading(repo.path, () => stopWatcher(repo.path))}
                onRemove={() => withLoading(repo.path, () => removeRepo(repo.path))}
              />
            ))}
          </div>
        </section>
      </main>
    </div>
  )
}
