import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWorkOrders } from '../api/hooks'
import { Progress, WoStatusPill } from '../components/WoStatus'
import { WorkOrderForm } from '../components/WorkOrderForm'

const TABS: { label: string; status?: string }[] = [
  { label: '전체' },
  { label: '진행중', status: 'RUNNING' },
  { label: '대기', status: 'PLANNED' },
  { label: '완료', status: 'DONE' },
]

export function WorkOrders() {
  const [status, setStatus] = useState<string | undefined>()
  const [showForm, setShowForm] = useState(false)
  const q = useWorkOrders(status)
  const nav = useNavigate()
  const rows = q.data ?? []

  return (
    <>
      <div className="page-head">
        <h1 className="page-title">작업지시</h1>
        <button type="button" className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>
          {showForm ? '닫기' : '신규 등록'}
        </button>
      </div>

      {showForm && (
        <WorkOrderForm
          onCancel={() => setShowForm(false)}
          onCreated={(id) => { setShowForm(false); nav(`/work-orders/${id}`) }}
        />
      )}

      {q.isError && (
        <div className="banner banner-error" role="alert">
          데이터를 불러오지 못했습니다: {q.error.message}
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="상태 필터">
        {TABS.map((t) => (
          <button
            key={t.label}
            type="button"
            role="tab"
            aria-selected={status === t.status}
            className={`tab${status === t.status ? ' active' : ''}`}
            onClick={() => setStatus(t.status)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="card table-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>작업지시</th><th>품목</th><th>라인</th><th className="num">계획</th>
              <th className="num">양품</th><th className="progress-col">진행률</th><th>납기일</th><th>상태</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((w) => (
              <tr
                key={w.wo_id}
                className="clickable"
                tabIndex={0}
                onClick={() => nav(`/work-orders/${w.wo_id}`)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); nav(`/work-orders/${w.wo_id}`) }
                }}
              >
                <td><strong>WO-{w.wo_id}</strong></td>
                <td>{w.item_name} <span className="muted">{w.item_code}</span></td>
                <td>{w.line_name}</td>
                <td className="num">{w.planned_qty.toLocaleString()}</td>
                <td className="num">{w.good_qty.toLocaleString()}</td>
                <td className="progress-col">
                  <div className="progress-cell">
                    <Progress pct={w.progress_pct} />
                    <span className="num">{w.progress_pct.toFixed(1)}%</span>
                  </div>
                </td>
                <td>{w.due_date ?? '-'}</td>
                <td><WoStatusPill status={w.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {q.data && rows.length === 0 && <p className="muted empty">해당하는 작업지시가 없습니다</p>}
        {!q.data && !q.isError && <p className="muted empty">불러오는 중...</p>}
      </div>
    </>
  )
}
