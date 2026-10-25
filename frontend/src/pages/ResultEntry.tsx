import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useCreateResult, useLookups, useWorkOrderOptions, useWorkOrders } from '../api/hooks'
import { DefectRows, type DefectRowState } from '../components/DefectRows'
import { STATUS_LABEL } from './WorkOrders'

export function ResultEntry() {
  const [params, setParams] = useSearchParams()
  const woParam = Number(params.get('wo'))
  const woId = Number.isInteger(woParam) && woParam > 0 ? woParam : null

  const wos = useWorkOrders()
  const lookups = useLookups()
  const options = useWorkOrderOptions(woId)
  const create = useCreateResult()

  const [processId, setProcessId] = useState('')
  const [equipmentId, setEquipmentId] = useState('')
  const [good, setGood] = useState('0')
  const [minutes, setMinutes] = useState('1')
  const [defects, setDefects] = useState<DefectRowState[]>([])
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<string | null>(null)

  const processes = options.data?.processes ?? []
  const process = processes.find((p) => String(p.process_id) === processId)
  const isDone = options.data?.status === 'DONE'

  const selectWo = (value: string) => {
    setProcessId('')
    setEquipmentId('')
    setError(null)
    setCreated(null)
    setParams(value ? { wo: value } : {}, { replace: true })
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (create.isPending || woId == null) return
    setCreated(null)
    const goodQty = Number(good)
    const mins = Number(minutes)
    if (!processId) return setError('공정을 선택하세요')
    if (!equipmentId) return setError('설비를 선택하세요')
    if (good.trim() === '' || !Number.isInteger(goodQty) || goodQty < 0) return setError('양품 수량은 0 이상의 정수여야 합니다')
    if (minutes.trim() === '' || !(mins > 0 && mins <= 60)) return setError('소요 시간은 0보다 크고 60분 이하여야 합니다')
    const rows = []
    for (const r of defects) {
      const qty = Number(r.qty)
      if (!r.defect_id) return setError('불량코드를 선택하세요')
      if (r.qty.trim() === '' || !Number.isInteger(qty) || qty <= 0) return setError('불량 수량은 1 이상의 정수여야 합니다')
      rows.push({ defect_id: Number(r.defect_id), kind: r.kind, qty })
    }
    setError(null)
    create.mutate(
      {
        wo_id: woId,
        process_id: Number(processId),
        equipment_id: Number(equipmentId),
        minutes: mins,
        good_qty: goodQty,
        defects: rows,
      },
      {
        onSuccess: (res) => {
          setCreated(res.lot_no)
          setGood('0')
          setDefects([])
        },
        onError: (err) => setError(err.message),
      },
    )
  }

  return (
    <>
      <h1 className="page-title">실적 입력</h1>
      <form className="card result-form" onSubmit={submit} noValidate>
        <label className="field">
          <span className="field-label">작업지시</span>
          <select value={woId ?? ''} onChange={(e) => selectWo(e.target.value)}>
            <option value="">작업지시를 선택하세요</option>
            {(wos.data ?? []).map((w) => (
              <option key={w.wo_id} value={w.wo_id}>
                WO-{w.wo_id} · {w.item_name} · {w.line_name} ({STATUS_LABEL[w.status] ?? w.status})
              </option>
            ))}
          </select>
        </label>

        {options.isError && (
          <div className="banner banner-error" role="alert">
            작업지시 정보를 불러오지 못했습니다: {options.error.message}
          </div>
        )}
        {isDone && (
          <div className="banner banner-info" role="status">
            완료된 작업지시에는 실적을 입력할 수 없습니다.
          </div>
        )}

        {!isDone && (
          <>
            <div className="form-grid">
              <label className="field">
                <span className="field-label">공정</span>
                <select
                  value={processId}
                  disabled={woId == null || !options.data}
                  onChange={(e) => { setProcessId(e.target.value); setEquipmentId('') }}
                >
                  <option value="">{woId == null ? '작업지시를 먼저 선택하세요' : '공정 선택'}</option>
                  {processes.map((p) => (
                    <option key={p.process_id} value={p.process_id}>{p.seq}. {p.code} · {p.name}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field-label">설비</span>
                <select value={equipmentId} disabled={!process} onChange={(e) => setEquipmentId(e.target.value)}>
                  <option value="">{process ? '설비 선택' : '공정을 먼저 선택하세요'}</option>
                  {(process?.equipment ?? []).map((q) => (
                    <option key={q.equipment_id} value={q.equipment_id}>{q.name}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field-label">양품 수량</span>
                <input type="number" min={0} step={1} value={good} onChange={(e) => setGood(e.target.value)} />
              </label>
              <label className="field">
                <span className="field-label">소요 시간(분)</span>
                <input type="number" min={0} max={60} step="any" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
              </label>
            </div>

            <h2 className="card-title form-section">불량 내역</h2>
            <DefectRows rows={defects} codes={lookups.data?.defect_codes ?? []} onChange={setDefects} />

            {error && <div className="banner banner-error form-msg" role="alert">{error}</div>}
            {created && (
              <div className="banner banner-ok form-msg" role="status">
                실적이 등록되었습니다. 생성된 LOT:{' '}
                <Link to={`/lots?lot_no=${encodeURIComponent(created)}`}>{created}</Link>
              </div>
            )}

            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={create.isPending || woId == null}>
                {create.isPending ? '등록 중...' : '실적 등록'}
              </button>
            </div>
          </>
        )}
      </form>
    </>
  )
}
