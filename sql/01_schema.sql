-- MES 포트폴리오 스키마 (PostgreSQL 16). 가상의 전자부품 공장 데이터 모델.

-- ===== 마스터 =====
CREATE TABLE item (
    item_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_code text NOT NULL UNIQUE,
    name      text NOT NULL,
    item_type text NOT NULL CHECK (item_type IN ('FG', 'SFG', 'RM')),
    unit      text NOT NULL DEFAULT 'EA'
);
COMMENT ON TABLE item IS '품목 마스터: FG 완제품, SFG 반제품, RM 원자재';

CREATE TABLE bom (
    parent_item_id integer NOT NULL REFERENCES item(item_id),
    child_item_id  integer NOT NULL REFERENCES item(item_id),
    qty_per        numeric NOT NULL CHECK (qty_per > 0),
    PRIMARY KEY (parent_item_id, child_item_id),
    CHECK (parent_item_id <> child_item_id)
);
COMMENT ON TABLE bom IS 'BOM: 부모 1단위 생산에 필요한 자식 품목 수량 (FG→SFG→RM 2단계)';

CREATE TABLE process (
    process_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code       text NOT NULL UNIQUE,
    name       text NOT NULL,
    seq        integer NOT NULL UNIQUE
);
COMMENT ON TABLE process IS '공정 마스터: 자재투입→SMT→AOI검사→조립→기능검사→포장';

CREATE TABLE routing (
    item_id         integer NOT NULL REFERENCES item(item_id),
    process_id      integer NOT NULL REFERENCES process(process_id),
    seq             integer NOT NULL,
    ideal_cycle_sec numeric NOT NULL CHECK (ideal_cycle_sec > 0),
    PRIMARY KEY (item_id, process_id),
    UNIQUE (item_id, seq)
);
COMMENT ON TABLE routing IS '품목별 공정 경로와 이상 사이클타임(초/개), 성능률 계산 기준';

CREATE TABLE line (
    line_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name    text NOT NULL UNIQUE
);
COMMENT ON TABLE line IS '생산 라인';

CREATE TABLE equipment (
    equipment_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    line_id      integer NOT NULL REFERENCES line(line_id),
    process_id   integer NOT NULL REFERENCES process(process_id),
    name         text NOT NULL UNIQUE
);
COMMENT ON TABLE equipment IS '설비: 라인·공정에 소속';

CREATE TABLE shift (
    shift_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text NOT NULL UNIQUE,
    start_time time NOT NULL,
    end_time   time NOT NULL
);
COMMENT ON TABLE shift IS '교대조: 야간은 end_time < start_time 으로 자정을 넘김';

CREATE TABLE downtime_reason (
    reason_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text NOT NULL UNIQUE,
    is_planned boolean NOT NULL
);
COMMENT ON TABLE downtime_reason IS '비가동 사유: 계획(점심·정기점검) / 비계획(설비고장·자재대기)';

CREATE TABLE defect_code (
    defect_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name      text NOT NULL UNIQUE
);
COMMENT ON TABLE defect_code IS '불량 유형 코드';

-- ===== 트랜잭션 =====
CREATE TABLE work_order (
    wo_id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id     integer NOT NULL REFERENCES item(item_id),
    line_id     integer NOT NULL REFERENCES line(line_id),
    planned_qty numeric NOT NULL CHECK (planned_qty > 0),
    status      text NOT NULL DEFAULT 'PLANNED' CHECK (status IN ('PLANNED', 'RUNNING', 'DONE')),
    due_date    date,
    created_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE work_order IS '작업지시';

CREATE TABLE lot (
    lot_id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lot_no          text NOT NULL UNIQUE,
    item_id         integer NOT NULL REFERENCES item(item_id),
    wo_id           integer REFERENCES work_order(wo_id),
    process_id      integer REFERENCES process(process_id),
    supplier_lot_no text,
    qty             numeric NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE lot IS 'LOT: 원자재 입고 LOT(wo_id 없음, supplier_lot_no 보유) 및 생산 LOT';

CREATE TABLE lot_consumption (
    parent_lot_id integer NOT NULL REFERENCES lot(lot_id),
    child_lot_id  integer NOT NULL REFERENCES lot(lot_id),
    qty           numeric NOT NULL CHECK (qty > 0),
    PRIMARY KEY (parent_lot_id, child_lot_id),
    CHECK (parent_lot_id <> child_lot_id)
);
COMMENT ON TABLE lot_consumption IS 'LOT 계보: parent=투입된 LOT, child=생성된 LOT';

CREATE TABLE production_result (
    result_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    wo_id        integer NOT NULL REFERENCES work_order(wo_id),
    process_id   integer NOT NULL REFERENCES process(process_id),
    equipment_id integer NOT NULL REFERENCES equipment(equipment_id),
    shift_id     integer NOT NULL REFERENCES shift(shift_id),
    lot_id       integer NOT NULL REFERENCES lot(lot_id),
    started_at   timestamptz NOT NULL,
    ended_at     timestamptz NOT NULL,
    good_qty     numeric NOT NULL DEFAULT 0 CHECK (good_qty >= 0),
    defect_qty   numeric NOT NULL DEFAULT 0 CHECK (defect_qty >= 0),
    rework_qty   numeric NOT NULL DEFAULT 0 CHECK (rework_qty >= 0),
    CHECK (ended_at >= started_at)
);
COMMENT ON TABLE production_result IS '생산실적: 설비·교대·LOT 단위 양품/불량/재작업 수량';

CREATE TABLE defect_record (
    result_id integer NOT NULL REFERENCES production_result(result_id),
    defect_id integer NOT NULL REFERENCES defect_code(defect_id),
    kind      text NOT NULL CHECK (kind IN ('rework', 'scrap')),
    qty       numeric NOT NULL CHECK (qty > 0),
    PRIMARY KEY (result_id, defect_id, kind)
);
COMMENT ON TABLE defect_record IS '불량 내역: 실적별 불량코드·구분(재작업/폐기)·수량';

CREATE TABLE equipment_status_log (
    log_id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    equipment_id integer NOT NULL REFERENCES equipment(equipment_id),
    status       text NOT NULL CHECK (status IN ('RUN', 'IDLE', 'DOWN')),
    reason_id    integer REFERENCES downtime_reason(reason_id),
    started_at   timestamptz NOT NULL,
    ended_at     timestamptz,
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);
COMMENT ON TABLE equipment_status_log IS '설비 상태 이력: ended_at NULL 이면 진행 중';

CREATE TABLE inventory (
    item_id integer PRIMARY KEY REFERENCES item(item_id),
    qty     numeric NOT NULL CHECK (qty >= 0)
);
COMMENT ON TABLE inventory IS '재고 잔량(품목별). 음수 불가';

CREATE TABLE inventory_txn (
    txn_id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id       integer NOT NULL REFERENCES item(item_id),
    delta         numeric NOT NULL,
    ref_result_id integer REFERENCES production_result(result_id),
    created_at    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE inventory_txn IS '재고 수불 원장: 증감(delta) 이력';

-- ===== 조회용 인덱스 =====
CREATE INDEX ix_production_result_equipment_started ON production_result (equipment_id, started_at);
CREATE INDEX ix_production_result_wo ON production_result (wo_id);
CREATE INDEX ix_lot_consumption_parent ON lot_consumption (parent_lot_id);
CREATE INDEX ix_lot_consumption_child ON lot_consumption (child_lot_id);
CREATE INDEX ix_equipment_status_log_equipment_started ON equipment_status_log (equipment_id, started_at);

-- ===== 무결성 =====
-- 설비당 진행 중(ended_at NULL) 상태 로그는 최대 1개
CREATE UNIQUE INDEX ux_equipment_status_log_one_open ON equipment_status_log (equipment_id)
    WHERE ended_at IS NULL;
