"""API 응답 모델. Decimal 은 float 로 강제 변환된다."""
from datetime import date, datetime

from pydantic import BaseModel


class Kpi(BaseModel):
    avg_oee: float | None
    defect_rate: float | None
    running_equipment: int
    total_equipment: int


class OeeEquipment(BaseModel):
    equipment_name: str
    oee: float
    availability: float
    performance: float
    quality: float | None


class DefectRow(BaseModel):
    process_code: str
    input_qty: float
    defect_qty: float
    scrap_qty: float
    rework_qty: float
    defect_rate: float
    fty: float


class Equipment(BaseModel):
    equipment_id: int
    name: str
    line_id: int
    line_name: str
    process_id: int
    process_code: str
    process_name: str
    process_seq: int
    status: str
    since: datetime | None
    reason: str | None


class OeeShift(BaseModel):
    shift_name: str
    work_date: date
    availability: float
    performance: float
    quality: float | None
    oee: float
    shift_start: datetime
    shift_end: datetime


class ResultRow(BaseModel):
    result_id: int
    wo_id: int
    good_qty: float
    defect_qty: float
    ended_at: datetime


class EquipmentDetail(Equipment):
    recent_oee: list[OeeShift]
    recent_results: list[ResultRow]


class StatusLogRow(BaseModel):
    status: str
    reason: str | None
    started_at: datetime
    ended_at: datetime | None


class WorkOrder(BaseModel):
    wo_id: int
    item_code: str
    item_name: str
    line_name: str
    planned_qty: float
    good_qty: float
    progress_pct: float
    status: str
    due_date: date | None


class WoProcess(BaseModel):
    process_code: str
    process_seq: int
    good_qty: float
    defect_qty: float


class WoLot(BaseModel):
    lot_no: str
    process_code: str | None
    qty: float
    created_at: datetime


class WorkOrderDetail(WorkOrder):
    processes: list[WoProcess]
    lots: list[WoLot]


class ItemRow(BaseModel):
    item_id: int
    item_code: str
    name: str
    item_type: str


class LineRow(BaseModel):
    line_id: int
    name: str


class ProcessRow(BaseModel):
    process_id: int
    code: str
    name: str
    seq: int


class ReasonRow(BaseModel):
    reason_id: int
    name: str
    is_planned: bool


class DefectCodeRow(BaseModel):
    defect_id: int
    name: str


class Lookups(BaseModel):
    items: list[ItemRow]
    lines: list[LineRow]
    processes: list[ProcessRow]
    reasons: list[ReasonRow]
    defect_codes: list[DefectCodeRow]


class OptEquipment(BaseModel):
    equipment_id: int
    name: str


class OptProcess(BaseModel):
    process_id: int
    code: str
    name: str
    seq: int
    equipment: list[OptEquipment]


class WoOptions(BaseModel):
    wo_id: int
    status: str
    processes: list[OptProcess]


class TraceRow(BaseModel):
    lot_no: str
    item_code: str
    depth: int


class TraceBackRow(TraceRow):
    supplier_lot_no: str | None
