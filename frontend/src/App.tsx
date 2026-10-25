import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout, Placeholder } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { Equipment } from './pages/Equipment'
import { Floor } from './pages/Floor'
import { LotTrace } from './pages/LotTrace'
import { ResultEntry } from './pages/ResultEntry'
import { WorkOrderDetail } from './pages/WorkOrderDetail'
import { WorkOrders } from './pages/WorkOrders'

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
            <Route path="work-orders" element={<WorkOrders />} />
            <Route path="work-orders/:id" element={<WorkOrderDetail />} />
            <Route path="results/new" element={<ResultEntry />} />
            <Route path="equipment" element={<Equipment />} />
            <Route path="lots" element={<LotTrace />} />
            <Route path="*" element={<Placeholder title="페이지를 찾을 수 없습니다" />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
