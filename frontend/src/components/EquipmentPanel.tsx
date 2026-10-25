import { useEquipmentDetail } from '../api/hooks'
import { StatusBadge } from './StatusBadge'

const pct = (v: number | null | undefined) => (v == null ? '-' : `${(v * 100).toFixed(1)}%`)
const fmtTime = (s: string | null | undefined) => (s ? s.replace('T', ' ').slice(0, 19) : '-')

export function EquipmentPanel({ id }: { id: number | null }) {
  const q = useEquipmentDetail(id)
  if (id == null) {
    return <aside className="card eq-panel"><p className="muted">설비를 선택하세요</p></aside>
  }
  if (q.isError) {
    return (
      <aside className="card eq-panel">
        <div className="banner banner-error" role="alert">설비 정보를 불러오지 못했습니다</div>
      </aside>
    )
  }
  if (!q.data) {
    return <aside className="card eq-panel"><p className="muted">불러오는 중...</p></aside>
  }
  const d = q.data
  return (
    <aside className="card eq-panel" aria-label="설비 상세">
      <h2 className="card-title">{d.name}</h2>
      <dl className="eq-facts">
        <dt>상태</dt><dd><StatusBadge status={d.status} /></dd>
        <dt>사유</dt><dd>{d.reason ?? '-'}</dd>
        <dt>시작 시각</dt><dd>{fmtTime(d.since)}</dd>
        <dt>라인 / 공정</dt><dd>{d.line_name} / {d.process_name}</dd>
      </dl>

      <h3 className="eq-sub">최근 OEE</h3>
      {d.recent_oee.length === 0 ? (
        <p className="muted">OEE 데이터가 없습니다</p>
      ) : (
        <table className="eq-table">
          <thead>
            <tr><th>교대</th><th>가용</th><th>성능</th><th>양품</th><th>OEE</th></tr>
          </thead>
          <tbody>
            {d.recent_oee.map((o) => (
              <tr key={`${o.work_date}-${o.shift_name}-${o.shift_start}`}>
                <td>{o.work_date.slice(5)} {o.shift_name}</td>
                <td>{pct(o.availability)}</td>
                <td>{pct(o.performance)}</td>
                <td>{pct(o.quality)}</td>
                <td><strong>{pct(o.oee)}</strong></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3 className="eq-sub">최근 실적 (10건)</h3>
      {d.recent_results.length === 0 ? (
        <p className="muted">실적이 없습니다</p>
      ) : (
        <table className="eq-table">
          <thead><tr><th>종료</th><th>양품</th><th>불량</th></tr></thead>
          <tbody>
            {d.recent_results.slice(0, 10).map((r) => (
              <tr key={r.result_id}>
                <td>{fmtTime(r.ended_at).slice(5, 16)}</td>
                <td>{r.good_qty}</td>
                <td>{r.defect_qty}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </aside>
  )
}
