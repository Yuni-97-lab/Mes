import { fireEvent, render, screen, within } from '@testing-library/react'
import { FloorMap } from './FloorMap'
import type { Equipment } from '../api/types'

const PROCS = [
  ['SMT', 'SMT 인쇄'], ['MNT', '마운트'], ['REF', '리플로우'],
  ['AOI', 'AOI 검사'], ['ASM', '조립'], ['PKG', '포장'],
]

function make(): Equipment[] {
  const out: Equipment[] = []
  let id = 1
  for (const line of [1, 2]) {
    PROCS.forEach(([code, name], i) => {
      out.push({
        equipment_id: id, name: `L${line}-${code}`, line_id: line, line_name: `${line}라인`,
        process_id: i + 1, process_code: code, process_name: name, process_seq: i + 1,
        status: id % 3 === 0 ? 'DOWN' : id % 3 === 1 ? 'RUN' : 'IDLE', since: null, reason: null,
      })
      id++
    })
  }
  return out
}

describe('FloorMap', () => {
  it('12대 설비와 6개 공정 헤더를 렌더한다', () => {
    const { container } = render(<FloorMap equipment={make()} selectedId={null} onSelect={() => {}} />)
    expect(container.querySelectorAll('[data-equipment-id]')).toHaveLength(12)
    expect(container.querySelectorAll('[data-process-header]')).toHaveLength(6)
  })

  it('입력 순서가 섞여도 공정 seq 순으로 배치한다', () => {
    const shuffled = [...make()].reverse()
    const { container } = render(<FloorMap equipment={shuffled} selectedId={null} onSelect={() => {}} />)
    const headers = Array.from(container.querySelectorAll('[data-process-header]')).map((h) => h.textContent)
    expect(headers).toEqual(PROCS.map((p) => p[1]))
    const row1 = Array.from(container.querySelectorAll('[data-equipment-id]'))
      .map((e) => e.getAttribute('data-equipment-name'))
      .filter((n) => n!.startsWith('L1'))
    expect(row1).toEqual(PROCS.map((p) => `L1-${p[0]}`))
  })

  it('한 셀에 2대면 둘 다 렌더한다', () => {
    const eq = make().slice(0, 6)
    eq.push({ ...eq[0], equipment_id: 99, name: 'L1-SMT-B' })
    const { container } = render(<FloorMap equipment={eq} selectedId={null} onSelect={() => {}} />)
    expect(container.querySelectorAll('[data-equipment-id]')).toHaveLength(7)
    expect(screen.getByText('L1-SMT-B')).toBeInTheDocument()
  })

  it('클릭과 Enter 로 onSelect(equipment_id) 를 호출한다', () => {
    const onSelect = vi.fn()
    const { container } = render(<FloorMap equipment={make()} selectedId={null} onSelect={onSelect} />)
    const el = container.querySelector('[data-equipment-id="2"]')!
    fireEvent.click(el)
    expect(onSelect).toHaveBeenCalledWith(2)
    fireEvent.keyDown(container.querySelector('[data-equipment-id="3"]')!, { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledWith(3)
  })

  it('상태별 data-status 와 한글 상태 라벨', () => {
    const { container } = render(<FloorMap equipment={make()} selectedId={1} onSelect={() => {}} />)
    expect(container.querySelector('[data-equipment-id="1"]')).toHaveAttribute('data-status', 'RUN')
    expect(container.querySelector('[data-equipment-id="2"]')).toHaveAttribute('data-status', 'IDLE')
    const down = container.querySelector('[data-equipment-id="3"]') as HTMLElement
    expect(down).toHaveAttribute('data-status', 'DOWN')
    expect(within(down as unknown as HTMLElement).getByText('정지')).toBeInTheDocument()
    expect(down.getAttribute('aria-label')).toContain('정지')
  })

  it('설비가 없으면 안내를 보여준다', () => {
    render(<FloorMap equipment={[]} selectedId={null} onSelect={() => {}} />)
    expect(screen.getByText('설비 데이터가 없습니다')).toBeInTheDocument()
  })
})
