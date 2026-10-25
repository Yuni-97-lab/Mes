import { useState } from 'react'
import { useCreateWorkOrder, useLookups } from '../api/hooks'

export function WorkOrderForm({ onCreated, onCancel }: { onCreated: (woId: number) => void; onCancel: () => void }) {
  const lookups = useLookups()
  const create = useCreateWorkOrder()
  const [itemId, setItemId] = useState('')
  const [lineId, setLineId] = useState('')
  const [qty, setQty] = useState('')
  const [due, setDue] = useState('')
  const [error, setError] = useState<string | null>(null)

  const items = lookups.data?.items ?? []
  const lines = lookups.data?.lines ?? []

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (create.isPending) return
    const planned = Number(qty)
    if (!itemId) return setError('품목을 선택하세요')
    if (!lineId) return setError('라인을 선택하세요')
    if (qty.trim() === '' || !Number.isInteger(planned) || planned <= 0) return setError('계획 수량은 1 이상의 정수여야 합니다')
    if (!due) return setError('납기일을 입력하세요')
    setError(null)
    create.mutate(
      { item_id: Number(itemId), line_id: Number(lineId), planned_qty: planned, due_date: due },
      { onSuccess: (res) => onCreated(res.wo_id), onError: (err) => setError(err.message) },
    )
  }

  const typeLabel = (t: string) => (t === 'FG' ? '완제품' : t === 'SFG' ? '반제품' : t)

  return (
    <form className="card wo-form" onSubmit={submit} noValidate aria-label="작업지시 신규 등록">
      <h2 className="card-title">작업지시 신규 등록</h2>
      <div className="form-grid">
        <label className="field">
          <span className="field-label">품목</span>
          <select value={itemId} onChange={(e) => setItemId(e.target.value)}>
            <option value="">품목 선택</option>
            {items.map((i) => (
              <option key={i.item_id} value={i.item_id}>
                {i.item_code} · {i.name} ({typeLabel(i.item_type)})
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">라인</span>
          <select value={lineId} onChange={(e) => setLineId(e.target.value)}>
            <option value="">라인 선택</option>
            {lines.map((l) => (
              <option key={l.line_id} value={l.line_id}>{l.name}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">계획 수량</span>
          <input type="number" min={1} step={1} value={qty} onChange={(e) => setQty(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">납기일</span>
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
      </div>
      {error && <div className="banner banner-error form-msg" role="alert">{error}</div>}
      <div className="form-actions">
        <button type="button" className="btn btn-secondary" onClick={onCancel}>취소</button>
        <button type="submit" className="btn btn-primary" disabled={create.isPending}>
          {create.isPending ? '등록 중...' : '등록'}
        </button>
      </div>
    </form>
  )
}
