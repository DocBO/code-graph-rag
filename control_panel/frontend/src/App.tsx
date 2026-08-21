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
  runEmbeddingOnly,
  runQuery,
  runSemantic,
  shutdownAll,
  startWatcher,
  stopWatcher,
} from './api'
import type { RepoInfo, SemanticResult, StatusResponse } from './types'
import Markdown from './Markdown'

type LampTone = 'off' | 'ok' | 'busy' | 'err'
type QueryDepth = 'shallow' | 'normal' | 'deep'

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
}interface RepoCardProps {
  repo: RepoInfo
  expanded: boolean
  logs: string[] | null
  loading: boolean
  onToggleLogs: () => void
  onStart: () => void
  onStartWithScan: () => void
  onEmbeddingOnly: () => void
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
  onEmbeddingOnly,
  onStop,
  onRemove,
}: RepoCardProps) {
  const { watcher } = repo
  const tone = lampTone(watcher.state)
  const busy = watcher.state === 'starting' || watcher.state === 'stopping' || loading
  const stopVisible =
    watcher.state === 'running' ||
    watcher.state === 'starting' ||
    watcher.state === 'stopping'
  const logRef = useRef<HTMLPreElement>(null)
  const stickToBottom = useRef(true)

  useEffect(() => {
    const el = logRef.current
    if (!expanded || !el) return
    if (stickToBottom.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [expanded, logs])

  const onLogScroll = () => {
    const el = logRef.current
    if (!el) return
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }

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
        {stopVisible ? (
          <button
            className="btn btn-stop"
            onClick={onStop}
            disabled={loading || watcher.state === 'stopping'}
          >
            Stop watcher
          </button>
        ) : (
          <button className="btn btn-start" onClick={onStart} disabled={busy}>
            Start watcher
          </button>
        )}
        {!stopVisible && (
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
          className="btn btn-ghost btn-embedding"
          onClick={onEmbeddingOnly}
          disabled={busy || watcher.embedding_in_progress}
          title="Regenerate all semantic embeddings from the graph (no file ingestion)"
        >
          {watcher.embedding_in_progress ? 'Embedding…' : 'Only embeddings'}
        </button>
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
        <pre className="logs" ref={logRef} onScroll={onLogScroll}>
          {logs && logs.length > 0 ? logs.join('\n') : '— no log lines yet —'}
        </pre>
      )}
    </article>
  )
}

function QueryPanel({
  repos,
  defaultRepo,
}: {
  repos: RepoInfo[]
  defaultRepo: string
}) {
  const [repoPath, setRepoPath] = useState(defaultRepo)
  const [question, setQuestion] = useState('')
  const [searchDepth, setSearchDepth] = useState<QueryDepth>('normal')
  const [resultDepth, setResultDepth] = useState<QueryDepth>('normal')
  const [result, setResult] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (repos.length > 0 && !repos.some((r) => r.path === repoPath)) {
      setRepoPath(repos[0].path)
    }
  }, [repos, repoPath])

  const submit = async () => {
    if (!repoPath || !question.trim()) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const res = await runQuery(repoPath, question.trim(), searchDepth)
      setResult(res.response)
      setResultDepth(res.search_depth)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const copy = async () => {
    if (!result) return
    try {
      await navigator.clipboard.writeText(result)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  return (
    <section className="card query-card">
      <header className="card-head">
        <div className="card-ident">
          <span className="query-glyph" aria-hidden>
            ◈
          </span>
          <div className="card-title">
            <h3>Query Codebase (RAG)</h3>
            <code className="card-path">ask the knowledge graph anything</code>
          </div>
        </div>
        <span className={`badge badge-${busy ? 'updating' : 'stopped'}`}>
          {busy ? 'THINKING…' : 'READY'}
        </span>
      </header>

      <div className="query-form">
        <select
          className="input mcp-select"
          value={repoPath}
          onChange={(e) => setRepoPath(e.target.value)}
          disabled={busy}
        >
          {repos.length === 0 && <option value="">no repos registered</option>}
          {repos.map((r) => (
            <option key={r.path} value={r.path}>
              {r.name} — {r.path}
            </option>
          ))}
        </select>
        <textarea
          className="input query-input"
          rows={3}
          placeholder="e.g. How does the watcher handle moved files?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit()
          }}
          disabled={busy}
        />
        <div className="query-controls">
          <label className="input-num">
            <span className="meta-k">DEPTH</span>
            <select
              className="input"
              value={searchDepth}
              onChange={(e) => setSearchDepth(e.target.value as QueryDepth)}
              disabled={busy}
            >
              <option value="shallow">shallow</option>
              <option value="normal">normal</option>
              <option value="deep">deep</option>
            </select>
          </label>
          <button
            className="btn btn-start query-submit"
            onClick={submit}
            disabled={busy || !repoPath || !question.trim()}
          >
            {busy ? 'Querying…' : 'Run query'}
          </button>
        </div>
      </div>

      {error && <div className="card-error">{error}</div>}

      {result && (
        <div className="query-result">
          <div className="query-result-head">
            <span className="meta-k">RESULT — {repoPath} — {resultDepth}</span>
            <button className="btn btn-ghost" onClick={copy}>
              {copied ? '✓ Copied' : 'Copy'}
            </button>
          </div>
          <div className="query-result-body">
            <Markdown text={result} />
          </div>
        </div>
      )}
    </section>
  )
}

function SemanticPanel({
  repos,
  defaultRepo,
}: {
  repos: RepoInfo[]
  defaultRepo: string
}) {
  const [repoPath, setRepoPath] = useState(defaultRepo)
  const [phrase, setPhrase] = useState('')
  const [topN, setTopN] = useState('5')
  const [result, setResult] = useState<SemanticResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})

  useEffect(() => {
    if (repos.length > 0 && !repos.some((r) => r.path === repoPath)) {
      setRepoPath(repos[0].path)
    }
  }, [repos, repoPath])

  const submit = async () => {
    if (!repoPath || !phrase.trim()) return
    setBusy(true)
    setError(null)
    setResult(null)
    setExpanded({})
    try {
      const n = Math.max(1, Math.min(50, parseInt(topN, 10) || 5))
      const res = await runSemantic(repoPath, phrase.trim(), n)
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const toggleMatch = (idx: number) => {
    setExpanded((s) => ({ ...s, [idx]: !s[idx] }))
  }

  return (
    <section className="card query-card semantic-card">
      <header className="card-head">
        <div className="card-ident">
          <span className="query-glyph" aria-hidden>
            ⌕
          </span>
          <div className="card-title">
            <h3>Quick Semantic Retrieval</h3>
            <code className="card-path">debug: raw vector matches + scores</code>
          </div>
        </div>
        <span className={`badge badge-${busy ? 'updating' : 'stopped'}`}>
          {busy ? 'SEARCHING…' : result ? `${result.matches.length} MATCHES` : 'READY'}
        </span>
      </header>

      <div className="query-form">
        <select
          className="input mcp-select"
          value={repoPath}
          onChange={(e) => setRepoPath(e.target.value)}
          disabled={busy}
        >
          {repos.length === 0 && <option value="">no repos registered</option>}
          {repos.map((r) => (
            <option key={r.path} value={r.path}>
              {r.name} — {r.path}
            </option>
          ))}
        </select>
        <textarea
          className="input query-input"
          rows={2}
          placeholder="e.g. SkillExecutor definition"
          value={phrase}
          onChange={(e) => setPhrase(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit()
          }}
          disabled={busy}
        />
        <div className="semantic-controls">
          <label className="input-num">
            <span className="meta-k">TOP N</span>
            <input
              type="number"
              min={1}
              max={50}
              value={topN}
              onChange={(e) => setTopN(e.target.value)}
              disabled={busy}
            />
          </label>
          <button
            className="btn btn-start query-submit"
            onClick={submit}
            disabled={busy || !repoPath || !phrase.trim()}
          >
            {busy ? 'Searching…' : 'Search'}
          </button>
        </div>
      </div>

      {error && <div className="card-error">{error}</div>}

      {result && (
        <div className="semantic-result">
          <div className="query-result-head">
            <span className="meta-k">
              {result.matches.length} MATCHES — {result.repo_path}
            </span>
          </div>
          {result.matches.length === 0 && (
            <p className="empty">No semantic matches for this phrase.</p>
          )}
          {result.matches.map((m, idx) => (
            <article key={idx} className="match" data-tone={m.score !== null && m.score >= 0.4 ? 'ok' : 'off'}>
              <header className="match-head" onClick={() => toggleMatch(idx)}>
                <span className="match-score">{m.score !== null ? m.score.toFixed(3) : '—'}</span>
                <span className="match-name">
                  <code>{m.qualified_name ?? 'unknown'}</code>
                  <span className="meta-k"> · {m.type ?? 'Code'}</span>
                </span>
                <span className="match-loc">
                  {m.filename ? `${m.filename}${m.start_line ? `:${m.start_line}` : ''}` : '—'}
                </span>
                <span className="match-toggle">{expanded[idx] ? '▾' : '▸'}</span>
              </header>
              {expanded[idx] && (
                <pre className="match-snippet">{m.snippet ?? '— no snippet —'}</pre>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

function AddRepoForm({ onAdd }: { onAdd: () => void }) {  const [path, setPath] = useState('')
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
  const stopVisible =
    status.state === 'running' ||
    status.state === 'starting' ||
    status.state === 'stopping'
  const [selected, setSelected] = useState<string>('')
  const logRef = useRef<HTMLPreElement>(null)
  const stickToBottom = useRef(true)

  useEffect(() => {
    const el = logRef.current
    if (!logs || !el) return
    if (stickToBottom.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [logs])

  const onLogScroll = () => {
    const el = logRef.current
    if (!el) return
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }

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
        {stopVisible ? (
          <button
            className="btn btn-stop"
            onClick={onStop}
            disabled={status.state === 'stopping'}
          >
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

      {logs && (
        <pre className="logs" ref={logRef} onScroll={onLogScroll}>
          {logs.join('\n')}
        </pre>
      )}
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
  const [shuttingDown, setShuttingDown] = useState(false)

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

  const refreshOpenLogs = useCallback(async () => {
    const openRepos = Object.entries(expanded)
      .filter(([, open]) => open)
      .map(([path]) => path)
    const fetchAll: Promise<void>[] = []
    for (const path of openRepos) {
      fetchAll.push(
        repoLogs(path)
          .then((lines) => setLogs((s) => ({ ...s, [path]: lines })))
          .catch(() => {
            // Transient log-fetch failures must not spam the error banner.
          }),
      )
    }
    if (mcpLogsVisible) {
      fetchAll.push(
        mcpLogs()
          .then((lines) => setLogs((s) => ({ ...s, __mcp__: lines })))
          .catch(() => {
            // Transient log-fetch failures must not spam the error banner.
          }),
      )
    }
    await Promise.all(fetchAll)
  }, [expanded, mcpLogsVisible])

  useEffect(() => {
    if (Object.keys(expanded).some((k) => expanded[k]) || mcpLogsVisible) {
      const id = setInterval(refreshOpenLogs, 2000)
      return () => clearInterval(id)
    }
  }, [expanded, mcpLogsVisible, refreshOpenLogs])

  const stopAll = async () => {
    if (
      !window.confirm(
        'Stop all processes?\n\nThis stops every watcher, the MCP server, and the control panel API server itself.',
      )
    ) {
      return
    }
    setShuttingDown(true)
    setError(null)
    try {
      await shutdownAll()
    } catch (e) {
      // The API server exits itself right after responding, so a failed
      // request here usually means it is already going down — treat that as
      // expected rather than an error.
      setError(e instanceof Error ? e.message : String(e))
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
          <span
            className={`sys chip chip-mg${!status?.memgraph?.alive ? ' chip-mg-err' : ''}`}
          >
            <StatusLamp tone={status?.memgraph?.alive ? 'ok' : 'err'} pulse={!status?.memgraph} />
            <span className="meta-k">MEMGRAPH</span>
            {cfg ? `${cfg.memgraph.host}:${cfg.memgraph.port}` : '…'}
            <span className="chip-state">
              {!status?.memgraph
                ? '…'
                : status.memgraph.alive
                  ? 'ALIVE'
                  : 'DOWN'}
            </span>
          </span>
          <span className="sys chip">
            <span className="meta-k">PROJECT</span>
            <span className="meta-ellipsis">{cfg?.project_root ?? '…'}</span>
          </span>
          <button
            className="btn btn-stopall"
            onClick={stopAll}
            disabled={shuttingDown}
            title="Stop all watchers, the MCP server, and the control panel API"
          >
            {shuttingDown ? 'Stopping…' : 'Stop all'}
          </button>
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

        <QueryPanel repos={repos} defaultRepo={repos[0]?.path ?? ''} />

        <SemanticPanel repos={repos} defaultRepo={repos[0]?.path ?? ''} />

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
                onEmbeddingOnly={() =>
                  withLoading(repo.path, () => runEmbeddingOnly(repo.path))
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
