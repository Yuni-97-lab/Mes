import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Equipment } from './Equipment'

const row = (status: string, reason: string | null = null) => ({
  equipment_id: 1, name: 'L1-SMT-01', line_id: 1, line_name: '라인1', process_id: 2, process_code: 'SMT',
  process_seq: 2, status, reason, since: '2026-10-26T09:00:00+09:00',
})
const LOOKUPS = {
  items: [], lines: [], processes: [], defect_codes: [],
  reasons: [{ reason_id: 3, name: '설비고장', is_planned: false }],
}

function mockApi(getStatus: () => string) {
  const fn = vi.fn(async (url: string) => {
    const path = String(url).split('?')[0]
    const body = path === '/api/equipment' ? [row(getStatus())] : path === '/api/lookups' ? LOOKUPS : {}
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => vi.unstubAllGlobals())

describe('Equipment', () => {
  it('서버 상태가 바뀌면(시뮬레이터 등) 행의 상태 선택도 따라간다', async () => {
    let status = 'IDLE'
    mockApi(() => status)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Equipment />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const select = await screen.findByLabelText('L1-SMT-01 상태 선택')
    expect(select).toHaveValue('IDLE')
    status = 'RUN'
    await act(() => client.refetchQueries({ queryKey: ['equipment'] }))
    await waitFor(() => expect(screen.getByLabelText('L1-SMT-01 상태 선택')).toHaveValue('RUN'))
    status = 'DOWN'
    await act(() => client.refetchQueries({ queryKey: ['equipment'] }))
    await waitFor(() => expect(screen.getByLabelText('L1-SMT-01 상태 선택')).toHaveValue('DOWN'))
  })

  it('상태 변경 후 서버 상태로 다시 맞춰져도 완료 안내가 남는다', async () => {
    let status = 'IDLE'
    const fn = vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url).split('?')[0]
      if (init?.method === 'POST') {
        const b = JSON.parse(String(init.body))
        status = b.status
        return new Response(JSON.stringify(row(status, '설비고장')), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      const body = path === '/api/equipment' ? [row(status, status === 'DOWN' ? '설비고장' : null)]
        : path === '/api/lookups' ? LOOKUPS : []
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fn)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Equipment />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const select = await screen.findByLabelText('L1-SMT-01 상태 선택')
    await screen.findByRole('option', { name: '설비고장' })   // 사유 목록(lookups) 로드 대기
    fireEvent.change(select, { target: { value: 'DOWN' } })
    fireEvent.change(await screen.findByLabelText('L1-SMT-01 사유'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: 'L1-SMT-01 상태 변경' }))
    expect(await screen.findByText('L1-SMT-01 상태를 정지(으)로 변경했습니다')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText('설비고장').length).toBeGreaterThan(0))
    expect(screen.getByLabelText('L1-SMT-01 상태 선택')).toHaveValue('DOWN')
    expect(screen.getByLabelText('L1-SMT-01 사유')).toHaveValue('3')
  })

  it('조회 데이터(lookups)는 주기적으로 다시 요청하지 않는다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const fn = mockApi(() => 'RUN')
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      render(
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <Equipment />
          </MemoryRouter>
        </QueryClientProvider>,
      )
      await screen.findByLabelText('L1-SMT-01 상태 선택')
      const lookupCalls = () => fn.mock.calls.filter(([u]) => String(u) === '/api/lookups').length
      const before = lookupCalls()
      await act(() => vi.advanceTimersByTimeAsync(16000))
      expect(fn.mock.calls.filter(([u]) => String(u) === '/api/equipment').length).toBeGreaterThan(1)
      expect(lookupCalls()).toBe(before)
    } finally {
      vi.useRealTimers()
    }
  })
})
