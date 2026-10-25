// 백엔드(backend/app/schemas.py) 응답 형식과 1:1 로 대응한다.
export interface Kpi {
  avg_oee: number | null
  defect_rate: number | null
  running_equipment: number
  total_equipment: number
}

export interface OeeEquipment {
  equipment_name: string
  oee: number
  availability: number
  performance: number
  quality: number | null
}

export interface DefectRow {
  process_code: string
  input_qty: number
  defect_qty: number
  scrap_qty: number
  rework_qty: number
  defect_rate: number
  fty: number
}

export interface Equipment {
  equipment_id: number
  name: string
  line_id: number
  line_name: string
  process_id: number
  process_code: string
  process_name: string
  process_seq: number
  status: 'RUN' | 'IDLE' | 'DOWN' | string
  since: string | null
  reason: string | null
}

export interface WorkOrder {
  wo_id: number
  item_code: string
  item_name: string
  line_name: string
  planned_qty: number
  good_qty: number
  progress_pct: number
  status: 'PLANNED' | 'RUNNING' | 'DONE' | string
  due_date: string | null
}

export interface ItemRow { item_id: number; item_code: string; name: string; item_type: string }
export interface LineRow { line_id: number; name: string }
export interface ProcessRow { process_id: number; code: string; name: string; seq: number }
export interface ReasonRow { reason_id: number; name: string; is_planned: boolean }
export interface DefectCodeRow { defect_id: number; name: string }

export interface Lookups {
  items: ItemRow[]
  lines: LineRow[]
  processes: ProcessRow[]
  reasons: ReasonRow[]
  defect_codes: DefectCodeRow[]
}
