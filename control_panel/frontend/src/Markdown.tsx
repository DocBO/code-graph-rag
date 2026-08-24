import { Fragment, useMemo, type ReactNode } from 'react'

function renderInline(line: string): ReactNode[] {
  const out: ReactNode[] = []
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g
  let last = 0
  let m: RegExpExecArray | null
  let key = 0
  while ((m = regex.exec(line)) !== null) {
    if (m.index > last) out.push(line.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('**')) {
      out.push(<strong key={key++}>{tok.slice(2, -2)}</strong>)
    } else if (tok.startsWith('`')) {
      out.push(
        <code key={key++} className="md-code">
          {tok.slice(1, -1)}
        </code>,
      )
    } else if (tok.startsWith('*')) {
      out.push(<em key={key++}>{tok.slice(1, -1)}</em>)
    } else {
      const linkMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok)
      if (linkMatch) {
        out.push(
          <a key={key++} href={linkMatch[2]} target="_blank" rel="noreferrer">
            {linkMatch[1]}
          </a>,
        )
      } else {
        out.push(tok)
      }
    }
    last = m.index + tok.length
  }
  if (last < line.length) out.push(line.slice(last))
  return out
}

interface ListItem {
  marker: string
  lines: string[]
}

interface Block {
  type: string
  content?: string
  lang?: string
  items?: ListItem[]
  rows?: string[][]
}

const OL_RE = /^\s*(\d+)\.\s+(.*)$/
const UL_RE = /^\s*([-*+])\s+(.*)$/
const HEADING_RE = /^\s*(#{1,6})\s+(.*)$/
const TABLE_RE = /^\s*\|.+\|$/

function parseList(lines: string[], start: number, re: RegExp): { items: ListItem[]; next: number } {
  const items: ListItem[] = []
  let i = start
  while (i < lines.length) {
    const m = re.exec(lines[i])
    if (!m) break
    const item: ListItem = { marker: m[1], lines: [m[2]] }
    i++
    // Consume continuation lines (including indented ones after blank lines)
    // until a heading, code fence, or the next item of the same list type.
    while (i < lines.length) {
      const cur = lines[i]
      if (re.test(cur)) break
      if (HEADING_RE.test(cur)) break
      if (/^\s*```/.test(cur)) break
      if (cur.trim() === '') {
        // A blank line only separates items when the next non-blank line is a
        // new item of the same type; an indented continuation stays in this
        // item, while unindented content ends it.
        let j = i
        while (j < lines.length && lines[j].trim() === '') j++
        if (j >= lines.length) break
        if (re.test(lines[j])) break
        if (!/^\s/.test(lines[j])) break
        i = j
        continue
      }
      item.lines.push(cur)
      i++
    }
    items.push(item)
    // Skip blank lines; continue the list if the next non-blank line is
    // another item of the same type.
    let j = i
    while (j < lines.length && lines[j].trim() === '') j++
    if (j < lines.length && re.test(lines[j])) {
      i = j
      continue
    }
    break
  }
  return { items, next: i }
}

function splitBlocks(lines: string[]): Block[] {
  const blocks: Block[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (/^```/.test(line)) {
      const lang = line.slice(3).trim()
      const buf: string[] = []
      i++
      while (i < lines.length && !/^```/.test(lines[i])) {
        buf.push(lines[i])
        i++
      }
      i++ // skip closing fence
      blocks.push({ type: 'code', content: buf.join('\n'), lang })
      continue
    }
    const heading = HEADING_RE.exec(line)
    if (heading) {
      blocks.push({ type: `h${heading[1].length}`, content: heading[2] })
      i++
      continue
    }
    if (OL_RE.test(line)) {
      const { items, next } = parseList(lines, i, OL_RE)
      blocks.push({ type: 'ol', items })
      i = next
      continue
    }
    if (UL_RE.test(line)) {
      const { items, next } = parseList(lines, i, UL_RE)
      blocks.push({ type: 'ul', items })
      i = next
      continue
    }
    if (TABLE_RE.test(line)) {
      const rows: string[][] = []
      while (i < lines.length && TABLE_RE.test(lines[i])) {
        const cells = lines[i]
          .split('|')
          .slice(1, -1)
          .map((c) => c.trim())
        // Skip separator rows (e.g. |---|---|)
        if (!/^-{2,}$/.test(cells[0] ?? '')) {
          rows.push(cells)
        }
        i++
      }
      if (rows.length > 0) {
        blocks.push({ type: 'table', rows })
      }
      continue
    }
    if (line.trim() === '') {
      i++
      continue
    }
    const para: string[] = [line]
    i++
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !HEADING_RE.test(lines[i]) &&
      !/^```/.test(lines[i]) &&
      !UL_RE.test(lines[i]) &&
      !OL_RE.test(lines[i])
    ) {
      para.push(lines[i])
      i++
    }
    blocks.push({ type: 'p', content: para.join(' ') })
  }
  return blocks
}

function renderListItem(item: ListItem): ReactNode {
  const [first, ...rest] = item.lines
  return (
    <li>
      {renderInline(first)}
      {rest.length > 0 && <div className="md-li-cont">{renderBlocks(splitBlocks(rest))}</div>}
    </li>
  )
}

function renderBlocks(blocks: Block[]): ReactNode[] {
  return blocks.map((b, idx) => {
    if (b.type === 'code') {
      return (
        <pre key={idx} className="md-pre">
          {b.lang && <div className="md-lang">{b.lang}</div>}
          <code>{b.content}</code>
        </pre>
      )
    }
    if (b.type.startsWith('h')) {
      const level = Number(b.type.slice(1))
      const Tag = `h${Math.min(level, 4)}` as 'h1' | 'h2' | 'h3' | 'h4'
      return <Tag key={idx}>{renderInline(b.content ?? '')}</Tag>
    }
    if (b.type === 'ul') {
      return (
        <ul key={idx}>
          {(b.items ?? []).map((item, j) => (
            <Fragment key={j}>{renderListItem(item)}</Fragment>
          ))}
        </ul>
      )
    }
    if (b.type === 'ol') {
      const start = Number((b.items?.[0]?.marker as string) || '1') || 1
      return (
        <ol key={idx} start={start}>
          {(b.items ?? []).map((item, j) => (
            <Fragment key={j}>{renderListItem(item)}</Fragment>
          ))}
        </ol>
      )
    }
    if (b.type === 'table') {
      const [head, ...body] = b.rows ?? []
      return (
        <table key={idx} className="md-table">
          {head && (
            <thead>
              <tr>{head.map((c, ci) => <th key={ci}>{renderInline(c)}</th>)}</tr>
            </thead>
          )}
          <tbody>
            {(body.length ? body : head ? [head] : []).map((row, ri) => (
              <tr key={ri}>{row.map((c, ci) => <td key={ci}>{renderInline(c)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      )
    }
    return <p key={idx}>{renderInline(b.content ?? '')}</p>
  })
}

export default function Markdown({ text }: { text: string }) {
  const blocks = useMemo(() => splitBlocks(text.split('\n')), [text])
  return <div className="md">{renderBlocks(blocks)}</div>
}
