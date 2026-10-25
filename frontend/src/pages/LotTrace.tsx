import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useLotTrace } from '../api/hooks'
import type { TraceDirection } from '../api/types'
import { LotTree } from '../components/LotTree'

export function LotTrace() {
  const [params, setParams] = useSearchParams()
  const lotNo = (params.get('lot_no') ?? '').trim()
  const direction: TraceDirection = params.get('direction') === 'backward' ? 'backward' : 'forward'
  const [input, setInput] = useState(lotNo)
  useEffect(() => setInput(lotNo), [lotNo])
  const q = useLotTrace(lotNo, direction)

  const go = (next: string, dir: TraceDirection) => {
    const p: Record<string, string> = {}
    if (next) p.lot_no = next
    if (dir === 'backward') p.direction = dir
    setParams(p)
  }

  return (
    <>
      <h1 className="page-title">LOT 추적</h1>
      <form
        className="card trace-form"
        aria-label="LOT 추적"
        onSubmit={(e) => { e.preventDefault(); go(input.trim(), direction) }}
      >
        <div className="trace-row">
          <label className="field trace-input">
            <span className="field-label">LOT 번호</span>
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="예: WO-62-ASM-M1" />
          </label>
          <button type="submit" className="btn btn-primary">추적</button>
        </div>
        <fieldset className="trace-dir">
          <legend className="field-label">추적 방향</legend>
          <label className="radio">
            <input type="radio" name="direction" checked={direction === 'forward'} onChange={() => go(lotNo || input.trim(), 'forward')} />
            정방향: 이 LOT로 만든 LOT
          </label>
          <label className="radio">
            <input type="radio" name="direction" checked={direction === 'backward'} onChange={() => go(lotNo || input.trim(), 'backward')} />
            역방향: 이 LOT의 원료 LOT
          </label>
        </fieldset>
        <p className="muted trace-help">LOT 번호 예시: WO-62-ASM-M1 (생산 LOT), RM-CAP-0012 (원료 LOT). 결과의 LOT 번호를 누르면 그 LOT 를 다시 추적합니다.</p>
      </form>

      <div className="card trace-result">
        <h2 className="card-title">추적 결과{lotNo && <span className="muted"> · {lotNo}</span>}</h2>
        {!lotNo ? (
          <p className="muted empty">LOT 번호를 입력하고 추적하세요</p>
        ) : q.isError ? (
          <div className="banner banner-error" role="alert">{q.error.message}</div>
        ) : q.data ? (
          <LotTree rows={q.data} onSelect={(l) => go(l, direction)} />
        ) : (
          <p className="muted">불러오는 중...</p>
        )}
      </div>
    </>
  )
}
