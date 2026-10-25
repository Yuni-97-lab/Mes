import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from './client'
import type {
  DefectRow, Equipment, EquipmentDetail, Kpi, Lookups, OeeEquipment, ResultCreated, ResultIn,
  StatusChangeIn, StatusLogRow, TraceDirection, TraceRow,
  WoOptions, WorkOrder, WorkOrderCreated, WorkOrderDetail, WorkOrderIn,
} from './types'

const POLL_MS = 5000

export const useKpi = () =>
  useQuery({ queryKey: ['kpi'], queryFn: () => apiGet<Kpi>('/api/kpi'), refetchInterval: POLL_MS })

export const useOeeByEquipment = () =>
  useQuery({
    queryKey: ['oee-equipment'],
    queryFn: () => apiGet<OeeEquipment[]>('/api/oee/equipment'),
    refetchInterval: POLL_MS,
  })

export const useDefects = () =>
  useQuery({
    queryKey: ['defects'],
    queryFn: () => apiGet<DefectRow[]>('/api/defects'),
    refetchInterval: POLL_MS,
  })

export const useEquipment = () =>
  useQuery({
    queryKey: ['equipment'],
    queryFn: () => apiGet<Equipment[]>('/api/equipment'),
    refetchInterval: POLL_MS,
  })

export const useWorkOrders = (status?: string) =>
  useQuery({
    queryKey: ['work-orders', status ?? 'all'],
    queryFn: () =>
      apiGet<WorkOrder[]>(status ? `/api/work-orders?status=${encodeURIComponent(status)}` : '/api/work-orders'),
    refetchInterval: POLL_MS,
  })

export const useLookups = () =>
  useQuery({
    queryKey: ['lookups'],
    queryFn: () => apiGet<Lookups>('/api/lookups'),
    refetchInterval: POLL_MS,
  })

export const useEquipmentDetail = (id: number | null) =>
  useQuery({
    queryKey: ['equipment', id],
    queryFn: () => apiGet<EquipmentDetail>(`/api/equipment/${id}`),
    enabled: id != null,
    refetchInterval: POLL_MS,
  })

export const useWorkOrderDetail = (id: number | null) =>
  useQuery({
    queryKey: ['work-order', id],
    queryFn: () => apiGet<WorkOrderDetail>(`/api/work-orders/${id}`),
    enabled: id != null,
    refetchInterval: POLL_MS,
  })

export const useWorkOrderOptions = (id: number | null) =>
  useQuery({
    queryKey: ['work-order-options', id],
    queryFn: () => apiGet<WoOptions>(`/api/work-orders/${id}/options`),
    enabled: id != null,
  })

export const useCreateWorkOrder = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: WorkOrderIn) => apiPost<WorkOrderCreated>('/api/work-orders', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['work-orders'] }),
  })
}

export const useCreateResult = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ResultIn) => apiPost<ResultCreated>('/api/results', body),
    onSuccess: () =>
      Promise.all(
        ['work-orders', 'work-order', 'work-order-options', 'equipment', 'kpi', 'oee-equipment', 'defects'].map(
          (k) => qc.invalidateQueries({ queryKey: [k] }),
        ),
      ),
  })
}

export const useStatusLog = (id: number | null) =>
  useQuery({
    queryKey: ['status-log', id],
    queryFn: () => apiGet<StatusLogRow[]>(`/api/equipment/${id}/status-log`),
    enabled: id != null,
    refetchInterval: POLL_MS,
  })

export const useChangeStatus = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & StatusChangeIn) =>
      apiPost<Equipment>(`/api/equipment/${id}/status`, body),
    onSuccess: () =>
      Promise.all(['equipment', 'status-log', 'kpi'].map((k) => qc.invalidateQueries({ queryKey: [k] }))),
  })
}

export const useLotTrace = (lotNo: string, direction: TraceDirection) =>
  useQuery({
    queryKey: ['lot-trace', lotNo, direction],
    queryFn: () =>
      apiGet<TraceRow[]>(`/api/lots/${encodeURIComponent(lotNo)}/trace?direction=${direction}`),
    enabled: lotNo !== '',
  })
