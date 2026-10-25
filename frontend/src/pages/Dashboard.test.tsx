import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Dashboard } from './Dashboard'

function mockApi(routes: Record<string, unknown>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const path = String(url).split('?')[0]
      if (!(path in routes)) return new Response('{}', { status: 404 })
      return new Response(JSON.stringify(routes[path]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

function renderDashboard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

// 실제 백엔드는 빈 DB 에서도 v_defect_rate(process LEFT JOIN) 때문에 공정 6개를 투입 0 으로 돌려준다
const ZERO_DEFECTS = ['MATIN', 'SMT', 'AOI', 'ASM', 'FCT', 'PACK'].map((process_code) => ({
  process_code, input_qty: 0, defect_qty: 0, scrap_qty: 0, rework_qty: 0, defect_rate: 0, fty: 1,
}))
const EMPTY_KPI = { avg_oee: null, defect_rate: null, running_equipment: 0, total_equipment: 12 }

describe('Dashboard', () => {
  it('빈 DB(공정 6개 투입 0 행)이면 안내 문구를 보여주고 차트를 숨긴다', async () => {
    mockApi({
      '/api/kpi': EMPTY_KPI,
      '/api/oee/equipment': [],
      '/api/defects': ZERO_DEFECTS,
      '/api/work-orders': [],
    })
    renderDashboard()
    expect(await screen.findByText(/데이터가 없습니다. 시뮬레이터를 실행하세요/)).toBeInTheDocument()
    expect(screen.queryByText('공정별 불량률 (%)')).not.toBeInTheDocument()
  })

  it('불량 집계에 투입이 하나라도 있으면 안내 문구를 보여주지 않는다', async () => {
    const defects = ZERO_DEFECTS.map((d) => (d.process_code === 'MATIN' ? { ...d, input_qty: 10 } : d))
    mockApi({
      '/api/kpi': { ...EMPTY_KPI, defect_rate: 0 },
      '/api/oee/equipment': [],
      '/api/defects': defects,
      '/api/work-orders': [],
    })
    renderDashboard()
    expect(await screen.findByText('공정별 불량률 (%)')).toBeInTheDocument()
    expect(screen.queryByText(/데이터가 없습니다/)).not.toBeInTheDocument()
  })

  it('값이 있으면 평균 OEE 카드에 퍼센트를 표시한다', async () => {
    mockApi({
      '/api/kpi': { avg_oee: 0.8123, defect_rate: 0.0215, running_equipment: 9, total_equipment: 12 },
      '/api/oee/equipment': [
        { equipment_name: 'SMT-1', oee: 0.8, availability: 0.9, performance: 0.9, quality: 0.99 },
      ],
      '/api/defects': [
        { process_code: 'SMT', input_qty: 100, defect_qty: 2, scrap_qty: 1, rework_qty: 1, defect_rate: 0.02, fty: 0.98 },
      ],
      '/api/work-orders': [
        { wo_id: 1, item_code: 'FG-1', item_name: '제품', line_name: 'L1', planned_qty: 100, good_qty: 40, progress_pct: 40, status: 'RUNNING', due_date: null },
      ],
    })
    renderDashboard()
    const card = (await screen.findByText('평균 OEE')).closest('.kpi-card') as HTMLElement
    await waitFor(() => expect(card).toHaveTextContent('81.2%'))
    expect(await screen.findByText('9 / 12')).toBeInTheDocument()
    expect(screen.queryByText(/데이터가 없습니다/)).not.toBeInTheDocument()
    expect(await screen.findByText(/WO-1/)).toBeInTheDocument()
  })
})
