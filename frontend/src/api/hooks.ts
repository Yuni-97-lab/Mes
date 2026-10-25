import { useQuery } from '@tanstack/react-query'
import { apiGet } from './client'
import type { DefectRow, Equipment, EquipmentDetail, Kpi, Lookups, OeeEquipment, WorkOrder } from './types'

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
