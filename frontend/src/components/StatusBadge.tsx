const LABELS: Record<string, { label: string; cls: string }> = {
  RUN: { label: '가동', cls: 'status-run' },
  IDLE: { label: '대기', cls: 'status-idle' },
  DOWN: { label: '정지', cls: 'status-down' },
}

export function StatusBadge({ status }: { status: 'RUN' | 'IDLE' | 'DOWN' | string }) {
  const known = LABELS[status]
  return (
    <span className={`status-badge ${known ? known.cls : 'status-unknown'}`}>
      <span className="status-dot" aria-hidden="true" />
      {known ? known.label : status}
    </span>
  )
}
