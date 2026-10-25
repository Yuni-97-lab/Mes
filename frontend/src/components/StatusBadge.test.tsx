import { render, screen } from '@testing-library/react'
import { StatusBadge } from './StatusBadge'

describe('StatusBadge', () => {
  it.each([
    ['RUN', '가동', 'status-run'],
    ['IDLE', '대기', 'status-idle'],
    ['DOWN', '정지', 'status-down'],
  ])('%s 는 %s 라벨과 %s 클래스', (status, label, cls) => {
    render(<StatusBadge status={status} />)
    const el = screen.getByText(label)
    expect(el).toHaveClass('status-badge', cls)
  })

  it('알 수 없는 상태는 원문을 표시한다', () => {
    render(<StatusBadge status="WEIRD" />)
    expect(screen.getByText('WEIRD')).toHaveClass('status-unknown')
  })
})
