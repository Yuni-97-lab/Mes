# MES 포트폴리오: PostgreSQL 기반 스마트팩토리 데이터 모델

> **가상 데이터 고지**: 이 프로젝트의 공장, 품목, 설비, LOT, 수량, 불량 등 모든 데이터는 시드 SQL 과 시뮬레이터가 만든 **가상 데이터**입니다. 실제 기업·공장의 데이터가 아닙니다.

## 목적

스마트팩토리 직무 지원용 포트폴리오입니다. 가상의 전자부품 공장(SMT/조립 라인 2개)을 대상으로 MES 업무 흐름을 PostgreSQL 데이터 모델과 SQL 로 구현하고, 설비 데이터 적재(시뮬레이터)부터 모니터링(대시보드)까지 연결합니다. 1순위는 DB 설계와 SQL 이고, 대시보드는 그 결과를 보여주는 용도입니다. 모든 KPI 는 SQL 뷰/함수/트리거에서 계산하며 Python 은 읽기만 합니다.

## 무엇을 보여주는가

| MES 개념 | 구현 |
|---|---|
| 작업지시 | `work_order` 와 상태 전이(PLANNED → RUNNING → DONE) 트리거, 진행률 뷰 `v_wo_progress` |
| LOT 추적 | `lot` / `lot_consumption` 계보, `WITH RECURSIVE` 정방향·역방향 함수 `trace_forward` / `trace_backward` (순환 방지) |
| 설비 가동 | `equipment_status_log`(RUN/IDLE/DOWN, 계획/비계획 비가동 사유), OEE 뷰 `v_oee_daily`, 현재 상태 뷰 `v_equipment_current` |
| 생산실적 | `production_result`(설비·교대·LOT 단위), 초과생산 방지 BEFORE 트리거 |
| 품질/불량 | `defect_record`(재작업/폐기 구분), 공정별 불량률과 FTY 뷰 `v_defect_rate` |
| 재고 | 첫 공정 투입 시 BOM 소요량 차감(backflush), 마지막 공정에서 양품 가산, 수불 원장 `inventory_txn`, 음수 재고 CHECK 로 차단 |

지표의 정확한 정의(OEE 3요소 공식, 교대/work_date 규칙 등)는 [`docs/erd.md`](docs/erd.md) 에 있습니다.

## 아키텍처

시뮬레이터가 설비 상태 로그와 생산실적을 PostgreSQL 에 INSERT 하면, 트리거가 재고와 작업지시 상태를 갱신하고 뷰/함수가 KPI 를 계산합니다. Streamlit 대시보드는 5초마다 뷰를 조회해 화면을 갱신합니다. 지표 계산 로직은 DB 안에 있고 Python 코드는 조회·표시만 합니다.

```mermaid
flowchart LR
    SIM["simulator/simulate.py<br/>설비 상태, 생산실적, 불량, LOT 적재"] -->|INSERT| DB[("PostgreSQL 16<br/>테이블 / 트리거 / 뷰 / 함수")]
    DB -->|"SELECT (v_oee_daily, v_defect_rate, v_wo_progress, v_equipment_current, trace_*)"| DASH["dashboard/app.py<br/>Streamlit, 5초 갱신"]
```

## 스크린샷

![MES 대시보드](docs/screenshots/dashboard.png)

시뮬레이터(`--once 300`, 속도 600배)로 채운 뒤 캡처한 실제 화면입니다(가상 데이터). 설비 상태, 작업지시 진행률, 공정별 불량률, 설비별 OEE 와 상단 KPI 카드가 보입니다. 화면 하단에 LOT 추적 입력란이 더 있습니다.

## 프로젝트 구조

```
.
├── sql/
│   ├── 01_schema.sql              # 테이블 17개, 제약, 인덱스
│   ├── 02_seed.sql                # 마스터 시드 (품목 10, 공정 6, 설비 12, 교대 2 ...)
│   ├── 03_functions_triggers.sql  # 실적 트리거(재고 backflush, 초과생산 방지), LOT 추적 함수
│   └── 04_views.sql               # v_oee_daily, v_defect_rate, v_wo_progress, v_equipment_current
├── simulator/simulate.py          # 공장 시뮬레이터 (CLI)
├── dashboard/                     # Streamlit 앱(app.py)과 조회 함수(queries.py)
├── mes/db.py                      # DATABASE_URL 연결 헬퍼
├── scripts/                       # init_db.py, create_dbs.sql, docker_init_test_db.sh
├── tests/                         # pytest 44개 (mes_test DB 사용)
├── docs/                          # erd.md, performance.md, screenshots/
├── docker-compose.yml             # PostgreSQL 16 (Docker 경로)
├── requirements.txt
└── .env.example
```

## 빠른 시작 (Windows)

사전 준비: Python 3.10 이상, PostgreSQL 16. 아래는 PowerShell 기준이며 저장소 루트에서 실행합니다. 이 프로젝트는 Anaconda Python 으로 개발·검증했습니다(코드가 `X | None` 타입 표기를 쓰므로 3.10 이상 필요).

### 1. PostgreSQL 준비 (둘 중 하나)

**방법 A: 네이티브 설치** (작성자 환경에서 검증한 경로)
```powershell
winget install PostgreSQL.PostgreSQL.16
# 설치 때 정한 postgres 비밀번호가 필요합니다. psql 이 PATH 에 없으면 전체 경로를 씁니다.
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -f scripts/create_dbs.sql
```
`scripts/create_dbs.sql` 이 `mes` 롤(비밀번호 `mes`)과 `mes`, `mes_test` DB 를 만듭니다.

**방법 B: Docker** (주의: 작성자 PC 에 Docker 가 없어 **이 경로는 직접 실행해 검증하지 못했습니다**)
```powershell
docker compose up -d
```
`docker-compose.yml` 이 `mes` 사용자/DB(비밀번호 `mes`)를 만들고, 최초 기동 시 `scripts/docker_init_test_db.sh` 가 `mes_test` DB 를 추가합니다.

### 2. Python 패키지
```powershell
pip install -r requirements.txt
```

### 3. 접속 문자열 (기본값과 다를 때만)
기본값은 `postgresql://mes:mes@localhost:5432/mes` 입니다(`mes/db.py`). 다르게 쓰려면 셸에서 `DATABASE_URL` 을 설정합니다. `.env` 파일은 자동으로 읽지 않습니다 (`.env.example` 은 값 예시일 뿐).
```powershell
# PowerShell
$env:DATABASE_URL = "postgresql://mes:mes@localhost:5432/mes"
```
```bash
# bash
export DATABASE_URL=postgresql://mes:mes@localhost:5432/mes
```

### 4. 실행 순서
```powershell
# (1) 스키마·시드 적용. --reset 은 public 스키마를 DROP 후 다시 만든다 (개발 DB 데이터 삭제)
python scripts/init_db.py --reset

# (2) 데이터 채우기: 빠르게 300틱(속도 600배)을 한 번에 채우고 종료
python -m simulator.simulate --speed 600 --seed 42 --once 300
#     또는 실시간에 가깝게 계속 적재 (Ctrl+C 로 중단, 실 1초당 시뮬 1분)
python -m simulator.simulate --speed 60 --seed 42

# (3) 대시보드 (시뮬레이터를 켜둔 채 다른 터미널에서)
streamlit run dashboard/app.py

# (4) 테스트
pytest
```
`python` 이 동작하지 않는 환경(예: Windows 스토어 스텁)에서는 설치된 Python 의 전체 경로로 실행합니다.

시뮬레이터 옵션: `--speed`(시뮬 시간/실시간 배율, 기본 60), `--seed`, `--once N`(N틱 실행 후 종료), `--tick`(실시간 틱 간격 초, 기본 1). 상태는 모두 DB 에 있어 재시작하면 DB 의 마지막 시각 이후부터 이어서 동작합니다.

`pytest` 는 `mes_test` DB 만 사용하며(세션 시작 시 그 DB 의 public 스키마를 비움), 개발 DB 는 건드리지 않습니다. 테스트는 `mes` 롤이 `mes_test` 에 접속할 수 있어야 하므로 1단계의 DB 생성이 필요합니다.

LOT 추적을 해보려면 대시보드 화면 하단 "LOT 번호" 칸에 실제 LOT 번호를 넣습니다. 번호 형식은 생산 LOT `WO-<작업지시>-<공정코드>-<순번>`(예: `WO-26-PACK-10`), 원자재 LOT `RM-<품목코드>-WO<작업지시>`(예: `RM-RM-IC-WO1`)입니다. 직접 조회할 수도 있습니다.
```sql
SELECT * FROM trace_backward('WO-26-PACK-10') ORDER BY depth, lot_no;
```
(LOT 번호는 시뮬레이터 실행마다 달라질 수 있으니 `SELECT lot_no FROM lot LIMIT 10;` 으로 확인하세요.)

## SQL 하이라이트

### 1. 재고 backflush 트리거 — [`sql/03_functions_triggers.sql`](sql/03_functions_triggers.sql)
`production_result` INSERT 직후, 품목 라우팅의 첫 공정 실적에서만 BOM 직계 자식 자재를 `qty_per x (양품+불량)` 만큼 차감하고 수불 원장에 기록합니다. 마지막 공정 실적은 완제품/반제품 재고를 양품만큼 늘립니다. 재고가 모자라면 `inventory` 의 `CHECK (qty >= 0)` 위반으로 INSERT 전체가 롤백됩니다. 같은 파일의 BEFORE INSERT 트리거는 작업지시 행을 `FOR UPDATE` 로 잠그고 초과생산을 막습니다.

```sql
IF v_pos IN ('FIRST', 'BOTH') THEN
    FOR c IN SELECT child_item_id, qty_per FROM bom WHERE parent_item_id = v_item_id LOOP
        UPDATE inventory
        SET qty = qty + (-c.qty_per * (NEW.good_qty + NEW.defect_qty))
        WHERE item_id = c.child_item_id;
        INSERT INTO inventory_txn (item_id, delta, ref_result_id)
        VALUES (c.child_item_id, -c.qty_per * (NEW.good_qty + NEW.defect_qty), NEW.result_id);
    END LOOP;
END IF;
```

### 2. 재귀 CTE LOT 추적 — [`sql/03_functions_triggers.sql`](sql/03_functions_triggers.sql)
`trace_backward(lot_no)` 는 완제품 LOT 에서 투입된 반제품·원자재 LOT(공급사 LOT 번호 포함)까지 거슬러 올라갑니다. 방문 경로 배열로 순환을 막고, 여러 경로로 닿는 LOT 는 최소 depth 로 한 번만 반환합니다. `trace_forward` 는 반대 방향입니다.

```sql
with recursive walk as (
    select c.parent_lot_id as lot_id, 1 as depth,
           array[s.lot_id, c.parent_lot_id] as path
    from lot s
    join lot_consumption c on c.child_lot_id = s.lot_id
    where s.lot_no = p_lot_no
    union all
    select c.parent_lot_id, w.depth + 1, w.path || c.parent_lot_id
    from walk w
    join lot_consumption c on c.child_lot_id = w.lot_id
    where c.parent_lot_id <> all (w.path)   -- 순환 방지
)
select distinct on (l.lot_id) l.lot_no, i.item_code, l.supplier_lot_no, w.depth
```

### 3. OEE 뷰 — [`sql/04_views.sql`](sql/04_views.sql)
`v_oee_daily` 는 설비 x 교대 x work_date 단위로 OEE = 가동률 x 성능률 x 품질률 을 계산합니다. 야간조의 자정 이후 구간은 교대가 시작된 전날 work_date 에 귀속시키고, 계획 비가동(점심·점검)은 계획시간에서 빼며, 교대 경계를 걸친 로그는 교대별로 잘라 계산합니다. 핵심 비율 계산부는 다음과 같습니다.

```sql
SELECT e.equipment_id, e.name AS equipment_name, a.shift_name, a.work_date,
       LEAST(1, COALESCE(a.run_sec / NULLIF(a.shift_sec - a.planned_down_sec, 0), 0)) AS availability,
       COALESCE(r.ideal_sec / NULLIF(a.run_sec, 0), 0)                      AS performance,
       COALESCE(r.good_qty / NULLIF(r.good_qty + r.defect_qty, 0), 0)       AS quality
FROM agg a
JOIN equipment e ON e.equipment_id = a.equipment_id
LEFT JOIN res r ON r.equipment_id = a.equipment_id AND r.shift_id = a.shift_id
               AND r.work_date = a.work_date
```

같은 파일에 불량률·FTY(`v_defect_rate`), 작업지시 진행률(`v_wo_progress`), 설비 현재 상태(`v_equipment_current`)도 있습니다.

## 성능 점검

KPI 뷰에 실적 100,000행을 적재해 측정했습니다. `v_oee_daily` 가 약 0.5초여서 일반 뷰를 유지했습니다. 방법과 한계는 [`docs/performance.md`](docs/performance.md) 를 참고하세요.

## 테스트

`pytest` 44개 (`tests/`): 스키마·제약, 트리거(backflush, 초과생산, 재고 부족 롤백, 상태 전이), LOT 추적(순환 포함), 뷰(고정 시나리오, 야간조 귀속, 교대 경계 분할, 0 나눔), 시뮬레이터(seed 재현성, 재시작 멱등성, 재고 고갈), 대시보드 조회 함수.

## 한계와 비목표

- **가상 데이터 기반**: 실제 PLC/OPC-UA 등 설비 연동은 없고 시뮬레이터가 대신합니다. 인증/권한, 멀티 사이트, 클라우드 배포, APS(스케줄링), ERP 연동은 범위 밖입니다.
- **입력 UI 없음**: 작업지시 등록·실적 입력 화면은 없습니다. 대시보드는 조회 전용입니다(LOT 추적 입력란 제외).
- **재고 규칙 단순화**: 소요 자재는 첫 공정에서 BOM 직계 자식만 차감하고, 결과물은 마지막 공정에서만 가산합니다. 단일 창고, 품목당 1행입니다.
- **LOT 계보는 휴리스틱**: 시뮬레이터가 "같은 작업지시의 직전 공정 최신 LOT" 를 부모로 연결하므로 실제 물리적 투입 관계를 정밀하게 반영하지 않습니다. 개별 시리얼 번호 추적은 제외했습니다.
- **FTY 는 공장 전체 단일 값**: 6개 공정의 `양품/투입` 곱이며 제품별 실제 경로 수율이 아닙니다.
- **OEE 성능률은 캡이 없습니다**: 시뮬레이터 데이터에서는 이상 사이클 대비 속도를 75–98%로 뽑지만, 실제 데이터에서 100%를 넘으면 그대로 나옵니다. 가동률만 최대 1로 캡합니다.
- **OEE 수치는 데모용**: `--once` 로 짧은 구간에 몰아 채우면 교대 길이(12시간) 대비 데이터가 적어 OEE 값이 낮게 나옵니다. 값 자체에 의미를 두지 마세요. (가동률 분모는 항상 교대 전체 길이인데 시뮬레이션 구간은 교대 일부만 덮을 수 있기 때문입니다.)
- **Docker 경로 미검증**: 작성자 환경에 Docker 가 없어 `docker-compose.yml` 은 직접 실행해 보지 못했습니다.
- 성능 측정은 단일 로컬 인스턴스의 수치입니다.
