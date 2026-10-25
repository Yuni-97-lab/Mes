import { useState } from 'react'
import { useEquipment } from '../api/hooks'
import { EquipmentPanel } from '../components/EquipmentPanel'
import { FloorMap } from '../components/FloorMap'

export function Floor() {
  const q = useEquipment()
  const [selected, setSelected] = useState<number | null>(null)
  const list = q.data ?? []
  const count = (s: string) => list.filter((e) => e.status === s).length

  return (
    <>
      <h1 className="page-title">공장 현황</h1>
      {q.isError && (
        <div className="banner banner-error" role="alert">
          데이터를 불러오지 못했습니다: {(q.error as Error).message}
        </div>
      )}
      <div className="chip-row" aria-label="상태 요약">
        <span className="chip status-run"><span className="status-dot" aria-hidden="true" />가동 <strong>{count('RUN')}</strong></span>
        <span className="chip status-idle"><span className="status-dot" aria-hidden="true" />대기 <strong>{count('IDLE')}</strong></span>
        <span className="chip status-down"><span className="status-dot" aria-hidden="true" />정지 <strong>{count('DOWN')}</strong></span>
        <span className="muted chip-note">5초마다 자동 갱신</span>
      </div>
      <div className="floor-layout">
        <div className="card floor-card">
          {q.data ? (
            <FloorMap equipment={list} selectedId={selected} onSelect={setSelected} />
          ) : (
            !q.isError && <p className="muted">불러오는 중...</p>
          )}
        </div>
        <EquipmentPanel id={selected} />
      </div>
    </>
  )
}
