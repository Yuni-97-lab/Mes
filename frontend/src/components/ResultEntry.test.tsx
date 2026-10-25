import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ResultEntry } from '../pages/ResultEntry'

const WOS = [
  { wo_id: 1, item_code: 'FG-1', item_name: '메인보드', line_name: '라인1', planned_qty: 100, good_qty: 10, progress_pct: 10, status: 'RUNNING', due_date: '2026-11-01' },
  { wo_id: 2, item_code: 'FG-2', item_name: '센서', line_name: '라인2', planned_qty: 50, good_qty: 50, progress_pct: 100, status: 'DONE', due_date: null },
]
const OPTIONS = {
  wo_id: 1,
  status: 'RUNNING',
  processes: [
    { process_id: 10, code: 'SMT', name: '표면실장', seq: 1, equipment: [{ equipment_id: 100, name: 'SMT-1' }] },
    { process_id: 20, code: 'AOI', name: '광학검사', seq: 2, equipment: [{ equipment_id: 200, name: 'AOI-1' }, { equipment_id: 201, name: 'AOI-2' }] },
  ],
}
const LOOKUPS = {
  items: [], lines: [], processes: [], reasons: [],
  defect_codes: [{ defect_id: 5, name: '납땜 불량' }, { defect_id: 6, name: '부품 누락' }],
}

type Handler = (init?: RequestInit) => Response | Promise<Response>
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function mockApi(post: Handler = () => json({ result_id: 1, lot_no: 'WO-1-SMT-M1' }, 201)) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).split('?')[0]
    if (init?.method === 'POST' && path === '/api/results') return post(init)
    if (path === '/api/work-orders') return json(WOS)
    if (path === '/api/work-orders/1/options') return json(OPTIONS)
    if (path === '/api/work-orders/2/options') return json({ wo_id: 2, status: 'DONE', processes: [] })
    if (path === '/api/lookups') return json(LOOKUPS)
    return json({}, 404)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

function renderPage(search = '') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/results/new${search}`]}>
        <ResultEntry />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const posts = (fn: ReturnType<typeof mockApi>) => fn.mock.calls.filter(([, init]) => init?.method === 'POST')
const postBody = (fn: ReturnType<typeof mockApi>) => JSON.parse(String(posts(fn)[0][1]!.body))
const pick = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } })
const optionTexts = (el: HTMLElement) => within(el).getAllByRole('option').map((o) => o.textContent)

async function fillForm() {
  const proc = await screen.findByLabelText('공정')
  await waitFor(() => expect(proc).toBeEnabled())
  pick(proc, '10')
  pick(screen.getByLabelText('설비'), '100')
  pick(screen.getByLabelText('양품 수량'), '7')
}

afterEach(() => vi.unstubAllGlobals())

describe('ResultEntry', () => {
  it('작업지시 선택 전에는 공정 선택이 비활성이다', async () => {
    mockApi()
    renderPage()
    expect(await screen.findByLabelText('공정')).toBeDisabled()
    expect(screen.getByLabelText('설비')).toBeDisabled()
  })

  it('작업지시를 고르면 options 의 공정만 나열한다', async () => {
    mockApi()
    renderPage()
    await screen.findByRole('option', { name: /WO-1/ })
    pick(screen.getByLabelText('작업지시'), '1')
    const proc = screen.getByLabelText('공정')
    await waitFor(() => expect(proc).toBeEnabled())
    const names = optionTexts(proc)
    expect(names).toHaveLength(3) // 안내 + 2개 공정
    expect(names.join('|')).toContain('SMT')
    expect(names.join('|')).toContain('AOI')
  })

  it('공정을 고르면 해당 공정의 설비만 나열한다', async () => {
    mockApi()
    renderPage('?wo=1')
    const proc = await screen.findByLabelText('공정')
    await waitFor(() => expect(proc).toBeEnabled())
    pick(proc, '20')
    const names = optionTexts(screen.getByLabelText('설비'))
    expect(names).toEqual(expect.arrayContaining(['AOI-1', 'AOI-2']))
    expect(names).not.toContain('SMT-1')
  })

  it('제출 중에는 버튼이 비활성이고 한 번만 요청한다', async () => {
    let release: (r: Response) => void = () => {}
    const fn = mockApi(() => new Promise<Response>((res) => { release = res }))
    renderPage('?wo=1')
    await fillForm()
    const btn = screen.getByRole('button', { name: '실적 등록' })
    fireEvent.click(btn)
    await waitFor(() => expect(btn).toBeDisabled())
    fireEvent.click(btn)
    expect(posts(fn)).toHaveLength(1)
    release(json({ result_id: 1, lot_no: 'WO-1-SMT-M1' }, 201))
    await waitFor(() => expect(btn).toBeEnabled())
  })

  it('409 응답이면 서버 문구를 그대로 보여준다', async () => {
    mockApi(() => json({ detail: '작업지시 수량을 초과합니다' }, 409))
    renderPage('?wo=1')
    await fillForm()
    fireEvent.click(screen.getByRole('button', { name: '실적 등록' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('작업지시 수량을 초과합니다')
  })

  it('성공하면 lot_no 를 보여주고 수량을 초기화한다', async () => {
    mockApi()
    renderPage('?wo=1')
    await fillForm()
    fireEvent.click(screen.getByRole('button', { name: '실적 등록' }))
    const link = await screen.findByRole('link', { name: 'WO-1-SMT-M1' })
    expect(link).toHaveAttribute('href', '/lots?lot_no=WO-1-SMT-M1')
    expect(screen.getByLabelText('양품 수량')).toHaveValue(0)
  })

  it('불량 행 추가/삭제가 요청 본문 defects 에 반영된다', async () => {
    const fn = mockApi()
    renderPage('?wo=1')
    await fillForm()
    const add = screen.getByRole('button', { name: '불량 행 추가' })
    fireEvent.click(add)
    fireEvent.click(add)
    const codes = screen.getAllByLabelText('불량코드')
    pick(codes[0], '5')
    pick(screen.getAllByLabelText('구분')[0], 'scrap')
    pick(screen.getAllByLabelText('불량 수량')[0], '2')
    pick(codes[1], '6')
    pick(screen.getAllByLabelText('불량 수량')[1], '3')
    // 두 번째 행을 삭제하면 첫 행만 남는다
    fireEvent.click(screen.getAllByRole('button', { name: '불량 행 삭제' })[1])
    expect(screen.getAllByLabelText('불량코드')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: '실적 등록' }))
    await waitFor(() => expect(posts(fn)).toHaveLength(1))
    expect(postBody(fn)).toEqual({
      wo_id: 1, process_id: 10, equipment_id: 100, minutes: 1, good_qty: 7,
      defects: [{ defect_id: 5, kind: 'scrap', qty: 2 }],
    })
  })

  it('DONE 작업지시에는 입력 폼 대신 안내를 보여준다', async () => {
    mockApi()
    renderPage('?wo=2')
    expect(await screen.findByText(/완료된 작업지시/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '실적 등록' })).not.toBeInTheDocument()
  })
})
