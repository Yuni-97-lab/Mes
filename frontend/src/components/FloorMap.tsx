import type { KeyboardEvent } from 'react'
import type { Equipment } from '../api/types'

export const STATUS_LABEL: Record<string, string> = { RUN: '가동', IDLE: '대기', DOWN: '정지' }
const STATUS_COLOR: Record<string, { fill: string; stroke: string; dot: string }> = {
  RUN: { fill: 'var(--run-bg)', stroke: 'var(--run)', dot: 'var(--run)' },
  IDLE: { fill: 'var(--idle-bg)', stroke: 'var(--idle)', dot: 'var(--idle)' },
  DOWN: { fill: 'var(--down-bg)', stroke: 'var(--down)', dot: 'var(--down)' },
}
const UNKNOWN = { fill: 'var(--grid)', stroke: 'var(--muted)', dot: 'var(--muted)' }

const LABEL_W = 84
const HEADER_H = 52
const EQ_W = 140
const EQ_H = 64
const GAP = 8
const ARROW_W = 34
const ROW_H = 104

interface Props {
  equipment: Equipment[]
  selectedId: number | null
  onSelect: (id: number) => void
}

export function FloorMap({ equipment, selectedId, onSelect }: Props) {
  if (equipment.length === 0) {
    return <div className="placeholder">설비 데이터가 없습니다</div>
  }

  // 열: process_seq 순, 행: line_id 순. 입력 순서와 무관하게 정렬한다.
  const procMap = new Map<number, { seq: number; name: string }>()
  const lineMap = new Map<number, string>()
  const cells = new Map<string, Equipment[]>()
  for (const e of equipment) {
    procMap.set(e.process_seq, { seq: e.process_seq, name: e.process_name })
    lineMap.set(e.line_id, e.line_name)
    const key = `${e.line_id}:${e.process_seq}`
    cells.set(key, [...(cells.get(key) ?? []), e])
  }
  const procs = [...procMap.values()].sort((a, b) => a.seq - b.seq)
  const lines = [...lineMap.entries()].sort((a, b) => a[0] - b[0])
  for (const list of cells.values()) list.sort((a, b) => a.equipment_id - b.equipment_id)

  const maxN = Math.max(...[...cells.values()].map((l) => l.length))
  const colW = maxN * EQ_W + (maxN + 1) * GAP
  const colStep = colW + ARROW_W
  const width = LABEL_W + procs.length * colStep - ARROW_W + 8
  const height = HEADER_H + lines.length * ROW_H + 4

  const keyHandler = (id: number) => (ev: KeyboardEvent) => {
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault()
      onSelect(id)
    }
  }

  return (
    <svg className="floor-svg" viewBox={`0 0 ${width} ${height}`} role="group" aria-label="공장 설비 배치도">
      <defs>
        <marker id="flow-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="var(--muted)" />
        </marker>
      </defs>

      {procs.map((p, ci) => {
        const x = LABEL_W + ci * colStep
        return (
          <g key={p.seq}>
            <rect x={x} y={4} width={colW} height={HEADER_H - 14} rx={8} className="floor-header-bg" />
            <text
              x={x + colW / 2}
              y={4 + (HEADER_H - 14) / 2 + 5}
              textAnchor="middle"
              className="floor-header"
              data-process-header={p.seq}
            >
              {p.name}
            </text>
          </g>
        )
      })}

      {lines.map(([lineId, lineName], ri) => {
        const y = HEADER_H + ri * ROW_H
        const cy = y + ROW_H / 2
        return (
          <g key={lineId}>
            <rect x={0} y={y + 4} width={width} height={ROW_H - 8} rx={10} className="floor-row-bg" />
            <text x={14} y={cy + 5} className="floor-line-label" data-line-label={lineId}>
              {lineName}
            </text>
            {procs.map((p, ci) => {
              const x = LABEL_W + ci * colStep
              const list = cells.get(`${lineId}:${p.seq}`) ?? []
              return (
                <g key={p.seq}>
                  {ci < procs.length - 1 && (
                    <line
                      x1={x + colW + 4}
                      y1={cy}
                      x2={x + colW + ARROW_W - 4}
                      y2={cy}
                      className="floor-flow"
                      markerEnd="url(#flow-arrow)"
                      aria-hidden="true"
                    />
                  )}
                  {list.map((e, i) => {
                    const ex = x + GAP + i * (EQ_W + GAP) + ((maxN - list.length) * (EQ_W + GAP)) / 2
                    const ey = cy - EQ_H / 2
                    const c = STATUS_COLOR[e.status] ?? UNKNOWN
                    const label = STATUS_LABEL[e.status] ?? e.status
                    const selected = e.equipment_id === selectedId
                    return (
                      <g
                        key={e.equipment_id}
                        className={`floor-eq${selected ? ' selected' : ''}${e.status === 'DOWN' ? ' down' : ''}`}
                        data-equipment-id={e.equipment_id}
                        data-equipment-name={e.name}
                        data-status={e.status}
                        role="button"
                        tabIndex={0}
                        aria-pressed={selected}
                        aria-label={`${e.name} ${label}`}
                        onClick={() => onSelect(e.equipment_id)}
                        onKeyDown={keyHandler(e.equipment_id)}
                      >
                        {selected && (
                          <rect x={ex - 4} y={ey - 4} width={EQ_W + 8} height={EQ_H + 8} rx={14} className="floor-select-ring" />
                        )}
                        <rect
                          x={ex}
                          y={ey}
                          width={EQ_W}
                          height={EQ_H}
                          rx={10}
                          fill={c.fill}
                          stroke={c.stroke}
                          strokeWidth={e.status === 'DOWN' ? 3 : 1.5}
                          className="floor-eq-body"
                        />
                        <text x={ex + 12} y={ey + 28} className="floor-eq-name">{e.name}</text>
                        <circle cx={ex + 17} cy={ey + 46} r={5} fill={c.dot} className="floor-eq-dot" />
                        <text x={ex + 28} y={ey + 52} className="floor-eq-status" fill={c.stroke}>{label}</text>
                      </g>
                    )
                  })}
                </g>
              )
            })}
          </g>
        )
      })}
    </svg>
  )
}
