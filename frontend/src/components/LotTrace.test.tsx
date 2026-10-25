import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LotTree } from './LotTree'
import { Equipment } from '../pages/Equipment'
import { LotTrace } from '../pages/LotTrace'

type Handler = (init?: RequestInit) => Response | Promise<Response>
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function wrap(ui: React.ReactElement, entry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

const ROWS = [
  { lot_no: 'WO-1-ASM-M1', item_code: 'FG-1', depth: 1 },
  { lot_no: 'WO-1-PACK-M1', item_code: 'FG-1', depth: 2 },
  { lot_no: 'WO-1-PACK-M2', item_code: 'FG-1', depth: 2 },
]

describe('LotTree', () => {
  it('depth 별로 들여쓰기 레벨을 부여한다', () => {
    wrap(<LotTree rows={ROWS} onSelect={() => {}} />, '/')
    const items = screen.getAllByRole('listitem')
    expect(items.map((i) => i.getAttribute('data-depth'))).toEqual(['1', '2', '2'])
    expect(items[0].style.paddingLeft).not.toBe(items[1].style.paddingLeft)
    expect(items[1].style.paddingLeft).toBe(items[2].style.paddingLeft)
  })

  it('빈 배열이면 안내 문구를 보여준다', () => {
    wrap(<LotTree rows={[]} onSelect={() => {}} />, '/')
    expect(screen.getByText('추적 결과가 없습니다')).toBeInTheDocument()
  })

  it('LOT 번호를 누르면 해당 LOT 로 추적한다', () => {
    const onSelect = vi.fn()
    wrap(<LotTree rows={ROWS} onSelect={onSelect} />, '/')
    fireEvent.click(screen.getByRole('button', { name: 'WO-1-PACK-M2' }))
    expect(onSelect).toHaveBeenCalledWith('WO-1-PACK-M2')
  })

  it('원료 LOT 번호가 있으면 함께 보여준다', () => {
    wrap(<LotTree rows={[{ lot_no: 'RM-1', item_code: 'RM-A', depth: 1, supplier_lot_no: 'SUP-99' }]} onSelect={() => {}} />, '/')
    expect(screen.getByText(/SUP-99/)).toBeInTheDocument()
  })
})

describe('LotTrace 페이지', () => {
  function mockTrace(handler: (url: string) => Response = () => json(ROWS)) {
    const fn = vi.fn(async (url: string) => handler(String(url)))
    vi.stubGlobal('fetch', fn)
    return fn
  }
  const urls = (fn: ReturnType<typeof mockTrace>) => fn.mock.calls.map(([u]) => String(u))

  it('?lot_no= 로 진입하면 입력창을 채우고 즉시 조회한다', async () => {
    const fn = mockTrace()
    wrap(<LotTrace />, '/lots?lot_no=WO-1-SMT-M1')
    expect(screen.getByLabelText('LOT 번호')).toHaveValue('WO-1-SMT-M1')
    expect(await screen.findByRole('button', { name: 'WO-1-PACK-M1' })).toBeInTheDocument()
    expect(urls(fn)).toEqual(['/api/lots/WO-1-SMT-M1/trace?direction=forward'])
  })

  it('입력이 없으면 조회하지 않는다', () => {
    const fn = mockTrace()
    wrap(<LotTrace />, '/lots')
    expect(fn).not.toHaveBeenCalled()
  })

  it('방향을 바꾸면 요청 URL 의 direction 이 바뀐다', async () => {
    const fn = mockTrace()
    wrap(<LotTrace />, '/lots?lot_no=L1')
    await screen.findByRole('button', { name: 'WO-1-ASM-M1' })
    fireEvent.click(screen.getByRole('radio', { name: /역방향/ }))
    await waitFor(() => expect(urls(fn)).toContain('/api/lots/L1/trace?direction=backward'))
  })

  it('서버 오류 문구를 그대로 보여준다', async () => {
    mockTrace(() => json({ detail: 'LOT 를 찾을 수 없습니다' }, 404))
    wrap(<LotTrace />, '/lots?lot_no=NOPE')
    expect(await screen.findByRole('alert')).toHaveTextContent('LOT 를 찾을 수 없습니다')
  })

  it('결과가 비어 있으면 안내한다', async () => {
    mockTrace(() => json([]))
    wrap(<LotTrace />, '/lots?lot_no=L1')
    expect(await screen.findByText('추적 결과가 없습니다')).toBeInTheDocument()
  })

  it('폼 제출은 입력값으로 조회한다', async () => {
    const fn = mockTrace()
    wrap(<LotTrace />, '/lots')
    fireEvent.change(screen.getByLabelText('LOT 번호'), { target: { value: ' L7 ' } })
    fireEvent.click(screen.getByRole('button', { name: '추적' }))
    await waitFor(() => expect(urls(fn)).toEqual(['/api/lots/L7/trace?direction=forward']))
  })
})

describe('Equipment 페이지', () => {
  const EQ = [
    { equipment_id: 1, name: 'SMT-1', line_id: 1, line_name: '라인1', process_id: 10, process_code: 'SMT', process_name: '표면실장', process_seq: 1, status: 'RUN', since: '2026-10-25T09:00:00', reason: null },
    { equipment_id: 2, name: 'AOI-1', line_id: 1, line_name: '라인1', process_id: 20, process_code: 'AOI', process_name: '광학검사', process_seq: 2, status: 'IDLE', since: '2026-10-25T09:10:00', reason: null },
  ]
  const LOOKUPS = {
    items: [], lines: [], processes: [], defect_codes: [],
    reasons: [{ reason_id: 3, name: '고장', is_planned: false }, { reason_id: 4, name: '점검', is_planned: true }],
  }
  const LOG = [
    { status: 'IDLE', reason: '점검', started_at: '2026-10-25T09:10:00', ended_at: null },
    { status: 'RUN', reason: null, started_at: '2026-10-25T09:00:00', ended_at: '2026-10-25T09:10:00' },
  ]

  function mockApi(post: Handler = () => json({ ...EQ[0], status: 'DOWN', reason: '고장' })) {
    const fn = vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url).split('?')[0]
      if (init?.method === 'POST') return post(init)
      if (path === '/api/equipment') return json(EQ)
      if (path === '/api/lookups') return json(LOOKUPS)
      if (path === '/api/equipment/1/status-log') return json(LOG)
      if (path === '/api/equipment/2/status-log') return json([])
      return json({}, 404)
    })
    vi.stubGlobal('fetch', fn)
    return fn
  }
  const posts = (fn: ReturnType<typeof mockApi>) => fn.mock.calls.filter(([, init]) => init?.method === 'POST')
  const reasonsLoaded = () =>
    waitFor(() => expect(within(screen.getByLabelText('SMT-1 사유')).getAllByRole('option').length).toBeGreaterThan(2))

  it('DOWN 을 선택하고 사유가 없으면 제출이 비활성이다', async () => {
    mockApi()
    wrap(<Equipment />, '/equipment')
    fireEvent.change(await screen.findByLabelText('SMT-1 상태 선택'), { target: { value: 'DOWN' } })
    const submit = screen.getByRole('button', { name: 'SMT-1 상태 변경' })
    expect(submit).toBeDisabled()
    await reasonsLoaded()
    fireEvent.change(screen.getByLabelText('SMT-1 사유'), { target: { value: '3' } })
    expect(submit).toBeEnabled()
  })

  it('제출하면 status/reason_id 를 보내고 확인 문구를 보여준다', async () => {
    const fn = mockApi()
    wrap(<Equipment />, '/equipment')
    fireEvent.change(await screen.findByLabelText('SMT-1 상태 선택'), { target: { value: 'DOWN' } })
    await reasonsLoaded()
    fireEvent.change(screen.getByLabelText('SMT-1 사유'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: 'SMT-1 상태 변경' }))
    await waitFor(() => expect(posts(fn)).toHaveLength(1))
    expect(String(posts(fn)[0][0])).toBe('/api/equipment/1/status')
    expect(JSON.parse(String(posts(fn)[0][1]!.body))).toEqual({ status: 'DOWN', reason_id: 3 })
    expect(await screen.findByRole('status')).toHaveTextContent('SMT-1')
  })

  it('서버 오류는 alert 로 그대로 보여준다', async () => {
    mockApi(() => json({ detail: '정지 사유가 필요합니다' }, 422))
    wrap(<Equipment />, '/equipment')
    fireEvent.change(await screen.findByLabelText('AOI-1 상태 선택'), { target: { value: 'RUN' } })
    fireEvent.click(screen.getByRole('button', { name: 'AOI-1 상태 변경' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('정지 사유가 필요합니다')
  })

  it('설비를 선택하면 상태 이력을 보여준다', async () => {
    mockApi()
    wrap(<Equipment />, '/equipment')
    fireEvent.click(await screen.findByRole('button', { name: 'SMT-1 이력 보기' }))
    expect(await screen.findByRole('heading', { name: /SMT-1 상태 이력/ })).toBeInTheDocument()
    expect(await screen.findByText('점검')).toBeInTheDocument()
  })

  it('시뮬레이터 안내 문구를 보여준다', async () => {
    mockApi()
    wrap(<Equipment />, '/equipment')
    expect(await screen.findByText(/시뮬레이터가 실행 중이면 수동 변경이/)).toBeInTheDocument()
  })
})
