import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout, Placeholder } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { Floor } from './pages/Floor'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="floor" element={<Floor />} />
            <Route path="work-orders" element={<Placeholder title="작업지시" />} />
            <Route path="results/new" element={<Placeholder title="실적 입력" />} />
            <Route path="equipment" element={<Placeholder title="설비 제어" />} />
            <Route path="lots" element={<Placeholder title="LOT 추적" />} />
            <Route path="*" element={<Placeholder title="페이지를 찾을 수 없습니다" />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
