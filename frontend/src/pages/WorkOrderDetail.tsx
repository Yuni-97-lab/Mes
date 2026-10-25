import { Link, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useWorkOrderDetail } from '../api/hooks'
import { Progress, WoStatusPill } from './WorkOrders'

const fmtTime = (s: string) => s.replace('T', ' ').slice(0, 19)

export function WorkOrderDetail() {
  const { id } = useParams()
  const woId = Number.isInteger(Number(id)) && Number(id) > 0 ? Number(id) : null
  const q = useWorkOrderDetail(woId)

  if (woId == null || (q.error instanceof ApiError && q.error.status === 404)) {
    return (
      <>
        <h1 className="page-title">작업지시</h1>
        <div className="card placeholder">
          작업지시를 찾을 수 없습니다. <Link to="/work-orders">목록으로 돌아가기</Link>
        </div>
      </>
    )
  }
  if (q.isError) {
    return (
      <>
        <h1 className="page-title">작업지시</h1>
        <div className="banner banner-error" role="alert">데이터를 불러오지 못했습니다: {q.error.message}</div>
      </>
    )
  }
  if (!q.data) return <p className="muted">불러오는 중...</p>

  const w = q.data
  return (
    <>
      <div className="page-head">
        <h1 className="page-title">WO-{w.wo_id} · {w.item_name}</h1>
        {w.status !== 'DONE' && (
          <Link className="btn btn-primary" to={`/results/new?wo=${w.wo_id}`}>실적 입력</Link>
        )}
      </div>
      <p className="crumb"><Link to="/work-orders">← 작업지시 목록</Link></p>

      <div className="card detail-summary">
        <dl className="eq-facts">
          <dt>상태</dt><dd><WoStatusPill status={w.status} /></dd>
          <dt>품목</dt><dd>{w.item_name} <span className="muted">{w.item_code}</span></dd>
          <dt>라인</dt><dd>{w.line_name}</dd>
          <dt>납기일</dt><dd>{w.due_date ?? '-'}</dd>
          <dt>수량</dt><dd>{w.good_qty.toLocaleString()} / {w.planned_qty.toLocaleString()}</dd>
        </dl>
        <div className="wo-head">
          <span className="wo-name">진행률</span>
          <span className="wo-pct">{w.progress_pct.toFixed(1)}%</span>
        </div>
        <Progress pct={w.progress_pct} />
      </div>

      <div className="detail-grid">
        <div className="card">
          <h2 className="card-title">공정별 실적</h2>
          <table className="data-table">
            <thead><tr><th>공정</th><th className="num">양품</th><th className="num">불량</th></tr></thead>
            <tbody>
              {w.processes.map((p) => (
                <tr key={p.process_code}>
                  <td>{p.process_seq}. {p.process_code}</td>
                  <td className="num">{p.good_qty.toLocaleString()}</td>
                  <td className="num">{p.defect_qty.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h2 className="card-title">생성된 LOT ({w.lots.length})</h2>
          {w.lots.length === 0 ? (
            <p className="muted">아직 생성된 LOT 가 없습니다</p>
          ) : (
            <div className="lot-scroll">
              <table className="data-table">
                <thead><tr><th>LOT 번호</th><th>공정</th><th className="num">수량</th><th>생성 시각</th></tr></thead>
                <tbody>
                  {w.lots.map((l) => (
                    <tr key={l.lot_no}>
                      <td><Link to={`/lots?lot_no=${encodeURIComponent(l.lot_no)}`}>{l.lot_no}</Link></td>
                      <td>{l.process_code ?? '-'}</td>
                      <td className="num">{l.qty.toLocaleString()}</td>
                      <td className="muted">{fmtTime(l.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
