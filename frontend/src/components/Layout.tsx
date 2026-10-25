import { NavLink, Outlet } from 'react-router-dom'

const NAV = [
  { to: '/', label: '대시보드', end: true },
  { to: '/floor', label: '공장 현황' },
  { to: '/work-orders', label: '작업지시' },
  { to: '/results/new', label: '실적 입력' },
  { to: '/equipment', label: '설비 제어' },
  { to: '/lots', label: 'LOT 추적' },
]

export function Layout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">M</span>
          <div>
            <div className="brand-title">MES 스마트팩토리</div>
            <div className="brand-sub">전자부품 생산 관제</div>
          </div>
        </div>
        <nav className="nav" aria-label="주 메뉴">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className="nav-link">
              {n.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}

export function Placeholder({ title }: { title: string }) {
  return (
    <>
      <h1 className="page-title">{title}</h1>
      <div className="card placeholder">준비 중</div>
    </>
  )
}
