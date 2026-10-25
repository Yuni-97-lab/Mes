import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { WorkOrderForm } from './WorkOrderForm'

const LOOKUPS = {
  items: [{ item_id: 1, item_code: 'FG-1', name: '메인보드', item_type: 'FG' }],
  lines: [{ line_id: 1, name: '라인1' }],
  processes: [], reasons: [], defect_codes: [],
}

describe('WorkOrderForm 검증', () => {
  it.each(['0', '-5', '1.5', ''])('계획 수량 %j 이면 요청 없이 한국어 메시지를 보여준다', async (qty) => {
    const fn = vi.fn(async (..._a: unknown[]) => new Response(JSON.stringify(LOOKUPS), { status: 200 }))
    vi.stubGlobal('fetch', fn)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <WorkOrderForm onCreated={() => {}} onCancel={() => {}} />
      </QueryClientProvider>,
    )
    await screen.findByRole('option', { name: /FG-1/ })
    fireEvent.change(screen.getByLabelText('품목'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('라인'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('계획 수량'), { target: { value: qty } })
    fireEvent.change(screen.getByLabelText('납기일'), { target: { value: '2026-12-01' } })
    fireEvent.click(screen.getByRole('button', { name: '등록' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('계획 수량')
    expect(fn.mock.calls.filter(([, i]: unknown[]) => (i as RequestInit | undefined)?.method === 'POST')).toHaveLength(0)
    vi.unstubAllGlobals()
  })
})
