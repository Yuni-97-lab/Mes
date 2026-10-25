import { useState } from 'react'
import { useChangeStatus, useEquipment, useLookups, useStatusLog } from '../api/hooks'
import type { Equipment as Eq, StatusChangeIn } from '../api/types'
import { StatusBadge } from '../components/StatusBadge'

const fmtTime = (s: string | null) => (s ? s.replace('T', ' ').slice(0, 19) : '-')
const STATUS_OPTIONS: { value: StatusChangeIn['status']; label: string }[] = [
  { value: 'RUN', label: '가동' },
  { value: 'IDLE', label: '대기' },
  { value: 'DOWN', label: '정지' },
]

function EquipmentRow({
  eq, selected, onSelect, onDone, onError,
}: {
  eq: Eq
  selected: boolean
  onSelect: () => void
  onDone: (msg: string) => void
  onError: (msg: string | null) => void
}) {
  const lookups = useLookups()
  const change = useChangeStatus()
  const serverStatus: StatusChangeIn['status'] = eq.status === 'RUN' || eq.status === 'DOWN' ? eq.status : 'IDLE'
  const serverReasonId = String(lookups.data?.reasons.find((r) => r.name === eq.reason)?.reason_id ?? '')
  const [status, setStatus] = useState<StatusChangeIn['status']>(serverStatus)
  const [reasonId, setReasonId] = useState(serverReasonId)
  // 서버 상태(시뮬레이터·다른 사용자의 변경 포함)가 바뀌면 선택값을 현재 상태로 다시 맞춘다.
  // (렌더 중 이전 값과 비교해 갱신하는 React 권장 패턴. key 로 행을 다시 만들면 진행 중 변경의 완료 안내가 사라진다)
  const serverKey = `${serverStatus}:${serverReasonId}`
  const [syncedKey, setSyncedKey] = useState(serverKey)
  if (syncedKey !== serverKey) {
    setSyncedKey(serverKey)
    setStatus(serverStatus)
    setReasonId(serverReasonId)
  }
  const needsReason = status === 'DOWN'
  const blocked = change.isPending || (needsReason && reasonId === '')

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (blocked) return
    onError(null)
    change.mutate(
      { id: eq.equipment_id, status, reason_id: status !== 'RUN' && reasonId !== '' ? Number(reasonId) : null },
      {
        onSuccess: (r) => onDone(`${eq.name} 상태를 ${STATUS_OPTIONS.find((o) => o.value === r.status)?.label ?? r.status}(으)로 변경했습니다`),
        onError: (err) => onError(err.message),
      },
    )
  }

  return (
    <tr className={selected ? 'row-selected' : undefined}>
      <td>{eq.name}</td>
      <td>{eq.line_name}</td>
      <td>{eq.process_seq}. {eq.process_code}</td>
      <td><StatusBadge status={eq.status} /></td>
      <td className="muted">{fmtTime(eq.since)}</td>
      <td>{eq.reason ?? '-'}</td>
      <td>
        <form className="eq-ctl" onSubmit={submit}>
          <select aria-label={`${eq.name} 상태 선택`} value={status} onChange={(e) => setStatus(e.target.value as StatusChangeIn['status'])}>
            {STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          {status !== 'RUN' && (
            <select aria-label={`${eq.name} 사유`} value={reasonId} onChange={(e) => setReasonId(e.target.value)}>
              <option value="">{needsReason ? '사유 선택 (필수)' : '사유 없음'}</option>
              {(lookups.data?.reasons ?? []).map((r) => (
                <option key={r.reason_id} value={r.reason_id}>{r.name}{r.is_planned ? ' (계획)' : ''}</option>
              ))}
            </select>
          )}
          <button type="submit" className="btn btn-primary btn-sm" disabled={blocked} aria-label={`${eq.name} 상태 변경`}>
            {change.isPending ? '변경 중...' : '변경'}
          </button>
        </form>
      </td>
      <td>
        <button type="button" className="btn btn-secondary btn-sm" aria-pressed={selected} aria-label={`${eq.name} 이력 보기`} onClick={onSelect}>
          이력
        </button>
      </td>
    </tr>
  )
}

function StatusHistory({ eq }: { eq: Eq }) {
  const q = useStatusLog(eq.equipment_id)
  return (
    <div className="card">
      <h2 className="card-title">{eq.name} 상태 이력 <span className="muted">(최신순)</span></h2>
      {q.isError ? (
        <div className="banner banner-error" role="alert">이력을 불러오지 못했습니다: {q.error.message}</div>
      ) : !q.data ? (
        <p className="muted">불러오는 중...</p>
      ) : q.data.length === 0 ? (
        <p className="muted empty">상태 이력이 없습니다</p>
      ) : (
        <div className="lot-scroll">
          <table className="data-table">
            <thead><tr><th>상태</th><th>사유</th><th>시작</th><th>종료</th></tr></thead>
            <tbody>
              {q.data.map((r, i) => (
                <tr key={`${r.started_at}-${i}`}>
                  <td><StatusBadge status={r.status} /></td>
                  <td>{r.reason ?? '-'}</td>
                  <td className="muted">{fmtTime(r.started_at)}</td>
                  <td className="muted">{r.ended_at ? fmtTime(r.ended_at) : '진행 중'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export function Equipment() {
  const q = useEquipment()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const list = q.data ?? []
  const selected = list.find((e) => e.equipment_id === selectedId) ?? null

  return (
    <>
      <h1 className="page-title">설비 제어</h1>
      <div className="banner banner-info">
        시뮬레이터가 실행 중이면 수동 변경이 시뮬레이터 규칙에 의해 덮일 수 있습니다. 시연 시 시뮬레이터를 멈추거나 낮은 속도로 실행하세요.
      </div>
      {q.isError && (
        <div className="banner banner-error" role="alert">데이터를 불러오지 못했습니다: {q.error.message}</div>
      )}
      {err && <div className="banner banner-error" role="alert">{err}</div>}
      {ok && <div className="banner banner-ok" role="status">{ok}</div>}
      <div className="card table-card">
        <table className="data-table">
          <thead>
            <tr><th>설비</th><th>라인</th><th>공정</th><th>상태</th><th>변경 시각</th><th>사유</th><th>상태 변경</th><th>이력</th></tr>
          </thead>
          <tbody>
            {list.map((e) => (
              <EquipmentRow
                key={e.equipment_id}
                eq={e}
                selected={e.equipment_id === selectedId}
                onSelect={() => setSelectedId(e.equipment_id === selectedId ? null : e.equipment_id)}
                onDone={(m) => { setOk(m); setErr(null) }}
                onError={(m) => { setErr(m); if (m) setOk(null) }}
              />
            ))}
          </tbody>
        </table>
        {!q.data && !q.isError && <p className="muted empty">불러오는 중...</p>}
      </div>
      {selected && <StatusHistory eq={selected} />}
    </>
  )
}
