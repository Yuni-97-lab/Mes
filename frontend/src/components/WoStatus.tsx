export const STATUS_LABEL: Record<string, string> = { PLANNED: '대기', RUNNING: '진행중', DONE: '완료' }

export function WoStatusPill({ status }: { status: string }) {
  const cls = status === 'RUNNING' ? 'status-run' : status === 'PLANNED' ? 'status-idle' : status === 'DONE' ? 'status-done' : 'status-unknown'
  return (
    <span className={`status-badge ${cls}`}>
      <span className="status-dot" aria-hidden="true" />
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

export function Progress({ pct }: { pct: number }) {
  const p = Math.max(0, Math.min(100, pct))
  return (
    <div className="progress" role="progressbar" aria-valuenow={p} aria-valuemin={0} aria-valuemax={100} aria-label="진행률">
      <div className="progress-fill" style={{ width: `${p}%` }} />
    </div>
  )
}
