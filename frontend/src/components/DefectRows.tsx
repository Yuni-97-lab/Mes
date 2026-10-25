import type { DefectCodeRow } from '../api/types'

export interface DefectRowState {
  key: number
  defect_id: string
  kind: 'rework' | 'scrap'
  qty: string
}

interface Props {
  rows: DefectRowState[]
  codes: DefectCodeRow[]
  onChange: (rows: DefectRowState[]) => void
}

let nextKey = 1
export const newDefectRow = (): DefectRowState => ({ key: nextKey++, defect_id: '', kind: 'rework', qty: '1' })

export function DefectRows({ rows, codes, onChange }: Props) {
  const update = (key: number, patch: Partial<DefectRowState>) =>
    onChange(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)))

  return (
    <div className="defect-rows">
      {rows.length === 0 && <p className="muted defect-empty">불량이 없으면 비워 두세요</p>}
      {rows.map((r) => (
        <div className="defect-row" key={r.key}>
          <label className="field">
            <span className="field-label">불량코드</span>
            <select value={r.defect_id} onChange={(e) => update(r.key, { defect_id: e.target.value })}>
              <option value="">선택</option>
              {codes.map((c) => (
                <option key={c.defect_id} value={c.defect_id}>{c.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">구분</span>
            <select value={r.kind} onChange={(e) => update(r.key, { kind: e.target.value as 'rework' | 'scrap' })}>
              <option value="rework">재작업</option>
              <option value="scrap">폐기</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">불량 수량</span>
            <input
              type="number"
              min={1}
              step={1}
              value={r.qty}
              onChange={(e) => update(r.key, { qty: e.target.value })}
            />
          </label>
          <button
            type="button"
            className="btn btn-ghost"
            aria-label="불량 행 삭제"
            onClick={() => onChange(rows.filter((x) => x.key !== r.key))}
          >
            삭제
          </button>
        </div>
      ))}
      <button type="button" className="btn btn-secondary" onClick={() => onChange([...rows, newDefectRow()])}>
        불량 행 추가
      </button>
    </div>
  )
}
