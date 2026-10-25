# ERD 와 지표 정의

가상의 전자부품 공장(SMT/조립 라인) 데이터 모델. 테이블 17개, 정의는 [`sql/01_schema.sql`](../sql/01_schema.sql).
모든 데이터는 가상이다.

## ERD

```mermaid
erDiagram
    item ||--o{ bom : "parent_item_id"
    item ||--o{ bom : "child_item_id"
    item ||--o{ routing : ""
    process ||--o{ routing : ""
    line ||--o{ equipment : ""
    process ||--o{ equipment : ""
    item ||--o{ work_order : ""
    line ||--o{ work_order : ""
    item ||--o{ lot : ""
    work_order |o--o{ lot : "wo_id (원자재 LOT 는 NULL)"
    process |o--o{ lot : "process_id (원자재 LOT 는 NULL)"
    lot ||--o{ lot_consumption : "parent_lot_id (투입 LOT)"
    lot ||--o{ lot_consumption : "child_lot_id (생성 LOT)"
    work_order ||--o{ production_result : ""
    process ||--o{ production_result : ""
    equipment ||--o{ production_result : ""
    shift ||--o{ production_result : ""
    lot ||--o{ production_result : ""
    production_result ||--o{ defect_record : ""
    defect_code ||--o{ defect_record : ""
    equipment ||--o{ equipment_status_log : ""
    downtime_reason |o--o{ equipment_status_log : "reason_id (NULL 가능)"
    item ||--|| inventory : "품목당 1행"
    item ||--o{ inventory_txn : ""
    production_result |o--o{ inventory_txn : "ref_result_id (기초 입고는 NULL)"

    item {
        int item_id PK
        text item_code UK
        text name
        text item_type "FG / SFG / RM"
        text unit
    }
    bom {
        int parent_item_id PK,FK
        int child_item_id PK,FK
        numeric qty_per
    }
    process {
        int process_id PK
        text code UK
        text name
        int seq UK
    }
    routing {
        int item_id PK,FK
        int process_id PK,FK
        int seq "UK(item_id, seq)"
        numeric ideal_cycle_sec
    }
    line {
        int line_id PK
        text name UK
    }
    equipment {
        int equipment_id PK
        int line_id FK
        int process_id FK
        text name UK
    }
    shift {
        int shift_id PK
        text name UK
        time start_time
        time end_time
    }
    downtime_reason {
        int reason_id PK
        text name UK
        boolean is_planned
    }
    defect_code {
        int defect_id PK
        text name UK
    }
    work_order {
        int wo_id PK
        int item_id FK
        int line_id FK
        numeric planned_qty
        text status "PLANNED / RUNNING / DONE"
        date due_date
        timestamptz created_at
    }
    lot {
        int lot_id PK
        text lot_no UK
        int item_id FK
        int wo_id FK
        int process_id FK
        text supplier_lot_no
        numeric qty
        timestamptz created_at
    }
    lot_consumption {
        int parent_lot_id PK,FK
        int child_lot_id PK,FK
        numeric qty
    }
    production_result {
        int result_id PK
        int wo_id FK
        int process_id FK
        int equipment_id FK
        int shift_id FK
        int lot_id FK
        timestamptz started_at
        timestamptz ended_at
        numeric good_qty
        numeric defect_qty
        numeric rework_qty
    }
    defect_record {
        int result_id PK,FK
        int defect_id PK,FK
        text kind PK "rework / scrap"
        numeric qty
    }
    equipment_status_log {
        int log_id PK
        int equipment_id FK
        text status "RUN / IDLE / DOWN"
        int reason_id FK
        timestamptz started_at
        timestamptz ended_at "NULL = 진행 중"
    }
    inventory {
        int item_id PK,FK
        numeric qty "CHECK qty >= 0"
    }
    inventory_txn {
        int txn_id PK
        int item_id FK
        numeric delta
        int ref_result_id FK
        timestamptz created_at
    }
```

### 읽는 법
- **마스터**: `item`, `bom`, `process`, `routing`, `line`, `equipment`, `shift`, `downtime_reason`, `defect_code`
- **트랜잭션**: `work_order`, `lot`, `lot_consumption`, `production_result`, `defect_record`, `equipment_status_log`, `inventory`, `inventory_txn`
- `bom`: FG → SFG → RM 2단계 (시드: 완제품 3, 반제품 2, 원자재 5).
- `routing`: 품목별 공정 순서와 `ideal_cycle_sec`(개당 이상 사이클타임). 시드에서 SFG 는 자재투입→SMT→AOI검사, FG 는 조립→기능검사→포장.
- `lot_consumption`: `parent_lot_id` 가 투입된 LOT, `child_lot_id` 가 만들어진 LOT 인 계보 테이블 (LOT 추적의 간선).
- `lot`: 원자재 입고 LOT 는 `wo_id`/`process_id` 가 NULL 이고 `supplier_lot_no` 를 가진다.
- 시드 규모: 설비 12대 (라인 2 x 공정 6), 교대 2개 ([`sql/02_seed.sql`](../sql/02_seed.sql)).
- 조회용 인덱스 5개: `production_result(equipment_id, started_at)`, `production_result(wo_id)`, `lot_consumption(parent_lot_id)`, `lot_consumption(child_lot_id)`, `equipment_status_log(equipment_id, started_at)`.

## 지표 정의

지표는 모두 SQL(뷰/함수/트리거)에서 계산한다. Python 대시보드는 결과를 읽기만 한다.
구현: [`sql/03_functions_triggers.sql`](../sql/03_functions_triggers.sql), [`sql/04_views.sql`](../sql/04_views.sql).

### OEE (`v_oee_daily`)
행 단위는 **설비 x 교대 x work_date**. 생산실적 또는 설비 상태 로그 활동이 있는 조합만 행으로 나온다.

| 요소 | 정의 |
|---|---|
| 가동률 (availability) | `가동시간 / 계획시간`, 최대 1로 캡 (`LEAST(1, ...)`) |
| 성능률 (performance) | `Σ(ideal_cycle_sec x (양품+불량)) / 가동시간(초)`, 상한 캡 없음 |
| 품질률 (quality) | `양품 / (양품+불량)` |
| OEE | `가동률 x 성능률 x 품질률` |

- **가동시간**: `RUN` 상태 로그가 교대 창과 겹치는 시간의 합. `ended_at IS NULL`(진행 중)은 `now()` 까지로 보되 교대 창 끝을 넘지 않는다. 교대 경계를 걸치는 로그는 교대별로 잘라 계산한다.
- **계획시간**: `교대길이 - 계획 비가동`. 계획 비가동은 `downtime_reason.is_planned = true` 사유가 붙은 비-RUN 로그의 교대 창 내 겹침 시간이다(점심, 정기점검). 비계획 정지(설비고장, 자재대기)와 사유 없는 IDLE 은 계획시간에서 빼지 않으므로 가동률을 낮춘다.
- **이상 사이클타임**: 작업지시 품목과 설비 공정의 `routing.ideal_cycle_sec`. 라우팅에 없으면 기여 0.
- **분모가 0이면** 해당 비율은 0 (`NULLIF`/`COALESCE`), 오류 없음.
- **교대와 work_date 규칙**: 시드의 주간 08:00–20:00, 야간 20:00–08:00. `work_date` 는 교대가 **시작한** 달력 날짜다. 야간조의 자정 이후 구간(00:00–08:00)은 전날 `work_date` 에 속한다. 교대 창은 `work_date + start_time` 부터 교대길이(12시간)이며 `end_time <= start_time` 이면 익일로 넘어간다.
- 날짜/시각 변환은 세션 `TimeZone` 기준이다.

### 불량률과 FTY (`v_defect_rate`)
- 공정별: `input_qty = 양품+불량`, `defect_rate = 불량 / 투입` (투입 0 이면 0).
- `scrap_qty`, `rework_qty` 는 `defect_record.kind` 별 합계.
- **FTY(First Time Yield)** = 투입이 있는 모든 공정의 `양품/(양품+불량)` 의 곱. 전체 공정에 대한 단일 값이라 각 행에 같은 값이 반복된다. 투입 없는 공정은 곱에서 제외하고, 투입이 있는 공정 중 양품 0 인 곳이 있으면 FTY 는 0.
- 시드의 공정은 6개이지만 공정별 합산 기준이라, SFG 와 FG 라우팅이 서로 다른 공정을 쓰는데도 FTY 는 6개 공정 전부의 곱이다. 즉 한 제품의 실제 경로 수율이 아니라 공장 전체 공정 수율의 곱이다.
- 대시보드의 "전체 불량률"은 `sum(defect_qty) / sum(input_qty)` (공정 합산 풀링 비율)이다.

### 작업지시 진행률 (`v_wo_progress`)
`progress_pct = 100 x 마지막 공정 누적 양품 / planned_qty` (소수 1자리). "마지막 공정"은 해당 품목 `routing` 에서 `seq` 가 가장 큰 공정이다.

### 재고 backflush (트리거 `trg_production_result_ai`)
`production_result` INSERT 시 실행된다. 규칙은 단순화되어 있다.
- **첫 공정**(품목 라우팅의 최소 `seq`, `routing_position` 이 FIRST/BOTH)의 실적에서만 BOM **직계 자식**을 `qty_per x (양품+불량)` 만큼 차감한다 (`inventory_txn.delta` 음수).
- **마지막 공정**(LAST/BOTH)의 실적에서만 생산 품목 재고를 `양품` 만큼 증가시킨다 (delta 양수).
- 중간 공정은 재고 이동 없이 실적만 기록한다.
- 재고 부족은 `inventory.qty >= 0` CHECK 위반으로 드러나 해당 INSERT 전체가 롤백된다.
- 작업지시 상태: 첫 실적에서 `PLANNED → RUNNING`, 마지막 공정 누적 양품이 계획 이상이면 `DONE`.
- 초과생산 방지(`trg_production_result_bi`, BEFORE INSERT): 마지막 공정의 누적 양품 + 신규 양품이 `planned_qty` 를 넘으면 예외. 같은 작업지시 행을 `FOR UPDATE` 로 잠가 동시 입력의 경쟁 상태를 막는다.

### LOT 추적 (`trace_forward`, `trace_backward`)
`lot_consumption` 을 `WITH RECURSIVE` 로 따라간다.
- `trace_forward(lot_no)`: 해당 LOT 를 투입해 만들어진 모든 하위 LOT. 반환 `(lot_no, item_code, depth)`.
- `trace_backward(lot_no)`: 해당 LOT 를 만들 때 투입된 상위 LOT (원자재 LOT 포함). 반환 `(lot_no, item_code, supplier_lot_no, depth)`.
- 시작 LOT 는 결과에서 제외, `depth` 는 1부터.
- 여러 경로로 도달하는 LOT 는 **최소 depth** 로 한 번만 반환 (`DISTINCT ON (lot_id) ... ORDER BY lot_id, depth`).
- **순환 방지**: 방문 경로를 배열(`path`)로 들고 다니며 이미 방문한 LOT 는 재방문하지 않는다 (`child_lot_id <> ALL(path)`). 순환 데이터가 있어도 종료한다 (`tests/test_lot_trace.py::test_cycle_does_not_hang`).
- 없는 `lot_no` 는 0행.

### 시뮬레이터가 만드는 계보의 단순화
시뮬레이터는 첫 공정 LOT 의 부모로 BOM 자식(원자재는 작업지시당 1개 LOT 재사용, 반제품은 해당 품목의 최신 LOT)을, 이후 공정 LOT 의 부모로 같은 작업지시의 직전 공정 최신 LOT 를 연결한다. 실제 물리적 투입 LOT 를 추적한 것이 아니라 "최신 LOT" 휴리스틱이므로 추적 결과는 데모용 계보다.

### 그 외 규칙
- 설비 12대 모두 라인 x 공정 조합으로 하나씩 존재 (`tests/test_schema.py` 로 검증).
- 재고는 단일 창고, 품목당 1행. 원자재 초기 재고 1,000,000 은 수불 원장에 기초 입고로 기록된다.
- 시뮬레이터의 원자재 보충(`replenish`)은 재고가 20,000 미만이면 500,000 입고 (트리거와 별개의 시뮬레이터 동작).
