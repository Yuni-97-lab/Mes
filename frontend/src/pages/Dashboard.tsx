import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useDefects, useKpi, useOeeByEquipment, useWorkOrders } from '../api/hooks'

const pct = (v: number | null | undefined, digits = 1) =>
  v == null ? '-' : `${(v * 100).toFixed(digits)}%`

function KpiCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card kpi-card">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </div>
  )
}

export function Dashboard() {
  const kpi = useKpi()
  const oee = useOeeByEquipment()
  const defects = useDefects()
  const wos = useWorkOrders('RUNNING')

  const failed = [kpi, oee, defects, wos].find((q) => q.isError)
  const loaded = kpi.data && oee.data && defects.data
  const empty =
    !!loaded && kpi.data!.avg_oee == null && oee.data!.length === 0 && defects.data!.length === 0

  // 서버가 준 정렬 순서를 그대로 유지한다 (재정렬 금지).
  const oeeData = (oee.data ?? []).map((r) => ({ name: r.equipment_name, value: +(r.oee * 100).toFixed(1) }))
  const defectData = (defects.data ?? []).map((r) => ({
    name: r.process_code,
    value: +(r.defect_rate * 100).toFixed(2),
  }))

  return (
    <>
      <h1 className="page-title">대시보드</h1>

      {failed && (
        <div className="banner banner-error" role="alert">
          데이터를 불러오지 못했습니다: {(failed.error as Error).message}
        </div>
      )}

      {empty && (
        <div className="banner banner-info" role="status">
          데이터가 없습니다. 시뮬레이터를 실행하세요
        </div>
      )}

      <section className="kpi-grid">
        <KpiCard label="평균 OEE" value={pct(kpi.data?.avg_oee)} hint="최근 24시간 설비 평균" />
        <KpiCard label="불량률" value={pct(kpi.data?.defect_rate, 2)} hint="공정 전체 누적" />
        <KpiCard
          label="가동 설비"
          value={kpi.data ? `${kpi.data.running_equipment} / ${kpi.data.total_equipment}` : '-'}
          hint="현재 가동 중 / 전체"
        />
      </section>

      {!empty && (
        <section className="chart-grid">
          <div className="card">
            <h2 className="card-title">설비별 OEE (%)</h2>
            <div className="chart-box">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={oeeData} margin={{ top: 18, right: 8, left: -12, bottom: 4 }}>
                  <CartesianGrid vertical={false} stroke="var(--grid)" />
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={0} angle={-30} textAnchor="end" height={64} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v) => [`${v}%`, 'OEE']} />
                  <Bar dataKey="value" fill="#2f6fed" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                    <LabelList dataKey="value" position="top" fontSize={10} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card">
            <h2 className="card-title">공정별 불량률 (%)</h2>
            <div className="chart-box">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={defectData} margin={{ top: 18, right: 8, left: -12, bottom: 4 }}>
                  <CartesianGrid vertical={false} stroke="var(--grid)" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v) => [`${v}%`, '불량률']} />
                  <Bar dataKey="value" fill="#e0773b" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                    <LabelList dataKey="value" position="top" fontSize={10} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>
      )}

      <section className="card">
        <h2 className="card-title">진행 중 작업지시</h2>
        {wos.data && wos.data.length === 0 && <p className="muted">진행 중인 작업지시가 없습니다</p>}
        <ul className="wo-list">
          {(wos.data ?? []).map((w) => {
            const p = Math.max(0, Math.min(100, w.progress_pct))
            return (
              <li key={w.wo_id} className="wo-row">
                <div className="wo-head">
                  <span className="wo-name">
                    WO-{w.wo_id} · {w.item_name}
                  </span>
                  <span className="muted">
                    {w.line_name} · {w.good_qty.toLocaleString()} / {w.planned_qty.toLocaleString()}
                  </span>
                  <span className="wo-pct">{w.progress_pct.toFixed(1)}%</span>
                </div>
                <div className="progress" role="progressbar" aria-valuenow={p} aria-valuemin={0} aria-valuemax={100}>
                  <div className="progress-fill" style={{ width: `${p}%` }} />
                </div>
              </li>
            )
          })}
        </ul>
      </section>
    </>
  )
}
