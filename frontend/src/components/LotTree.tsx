import type { TraceRow } from '../api/types'

const INDENT_PX = 24

export function LotTree({ rows, onSelect }: { rows: TraceRow[]; onSelect: (lotNo: string) => void }) {
  if (rows.length === 0) return <p className="muted empty">추적 결과가 없습니다</p>
  const base = Math.min(...rows.map((r) => r.depth))
  return (
    <ul className="lot-tree">
      {rows.map((r) => (
        <li
          key={`${r.depth}-${r.lot_no}`}
          className="lot-node"
          data-depth={r.depth}
          style={{ paddingLeft: 8 + (r.depth - base) * INDENT_PX }}
        >
          <span className="lot-branch" aria-hidden="true">{r.depth > base ? '└' : '●'}</span>
          <button type="button" className="lot-link" onClick={() => onSelect(r.lot_no)}>{r.lot_no}</button>
          <span className="lot-item">{r.item_code}</span>
          {r.supplier_lot_no && <span className="lot-supplier">공급사 LOT {r.supplier_lot_no}</span>}
          <span className="lot-depth muted">깊이 {r.depth}</span>
        </li>
      ))}
    </ul>
  )
}
