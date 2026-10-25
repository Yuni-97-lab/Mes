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

시뮬레이터로 약 50시간(`--once 300`, 틱 10분)을 채운 뒤 연속 모드(`--speed 60`)를 켜둔 상태에서 캡처한 실제 화면입니다(가상 데이터). 상단 KPI 카드(최근 2교대 평균 OEE, 전체 불량률, 가동 설비 수), 설비 상태(라인 → 공정 순), 작업지시 진행률(진행 중 우선), 공정별 불량률, 설비별 OEE 가 보입니다. 화면 하단에 LOT 추적 입력란이 더 있습니다.

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
├── tests/                         # pytest 66개 (mes_test DB 사용)
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

**시간대**: 교대(주간 08–20, 야간 20–08)는 한국 시간 기준입니다. `postgres` Docker 이미지의 기본 시간대는 UTC 이므로 `docker-compose.yml` 에서 `TZ`/`PGTZ`/`timezone` 을 `Asia/Seoul` 로 고정했고, `scripts/create_dbs.sql`·Docker 초기화 스크립트도 두 DB 의 기본 시간대를 `Asia/Seoul` 로 설정합니다. 무엇보다 `mes/db.py` 의 `connect()` 가 세션마다 `TimeZone = Asia/Seoul` 을 지정하므로, 서버 설정과 관계없이 시뮬레이터의 교대 배정과 뷰의 교대 창 계산이 같은 시간대를 씁니다. 시뮬레이터도 시각을 KST(UTC+9)로 다룹니다.

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

# (2) 데이터 채우기: 지금까지의 약 50시간(10분 틱 300개)을 한 번에 채우고 종료
python -m simulator.simulate --speed 600 --seed 42 --once 300
#     또는 계속 적재 (Ctrl+C 로 중단): 현재 교대 시작(또는 DB 마지막 시각)부터 60배속으로 따라잡은 뒤 실시간 진행
python -m simulator.simulate --speed 60 --seed 42

# (3) 대시보드 (시뮬레이터를 켜둔 채 다른 터미널에서)
streamlit run dashboard/app.py

# (4) 테스트
pytest
```
`python` 이 동작하지 않는 환경(예: Windows 스토어 스텁)에서는 설치된 Python 의 전체 경로로 실행합니다.

시뮬레이터 옵션: `--speed`(기본 60), `--seed`, `--once N`, `--tick`(기본 1초). 시계 규칙은 다음과 같습니다.

- **시뮬 시각은 현재 시각(벽시계)을 넘지 않습니다.** 미래 시각의 데이터는 만들지 않으므로 대시보드 지표가 실제 시각과 어긋나지 않습니다.
- 틱 길이 = `--tick x --speed` 시뮬 초 (기본 60초, `--speed 600` 이면 10분).
- 시작점: 빈 DB 에서 `--once N` 은 "지금 - N틱" 부터 시작해 마지막 틱이 지금이 되고, 연속 모드는 현재 교대 시작 시각부터 채웁니다. DB 에 데이터가 있으면 마지막 시각부터 이어 갑니다.
- 연속 모드: 현재 시각보다 뒤처져 있는 동안은 실시간 `--tick` 초마다 한 틱씩(= `--speed` 배속) 따라잡고, 따라잡은 뒤에는 실제 시간이 한 틱 길이만큼 흐를 때마다 한 틱을 진행합니다. 즉 `--speed` 는 따라잡는 속도와 틱 길이만 정합니다.
- `--once N`: 최대 N틱을 기다림 없이 실행하고, 현재 시각에 닿으면 더 일찍 끝냅니다(예: 방금 채운 DB 에서 다시 실행하면 진행할 틱이 없음).
- 정지: 정상 종료·Ctrl+C 시 진행 중 설비 로그를 마지막 시뮬 시각에 닫고 IDLE 로 남깁니다. 멈춰 있는 동안 RUN 시간이 쌓이지 않습니다(가동률은 정지 시간만큼 내려감). 오래 멈춘 뒤(마지막 시각이 시작점 이전) 재시작하면 마지막 시각에 설비를 정지 처리하고 시작점부터 새로 채웁니다. 프로세스를 강제 종료한 경우에는 `python -m simulator.simulate --once 1 --speed 600` 을 한 번 실행하면 진행할 틱 없이 정지 처리만 하고 끝납니다.

`pytest` 는 `mes_test` DB 만 사용하며(세션 시작 시 그 DB 의 public 스키마를 비움), 개발 DB 는 건드리지 않습니다. 테스트는 `mes` 롤이 `mes_test` 에 접속할 수 있어야 하므로 1단계의 DB 생성이 필요합니다.

LOT 추적을 해보려면 대시보드 화면 하단 "LOT 번호" 칸에 실제 LOT 번호를 넣습니다. 번호 형식은 생산 LOT `WO-<작업지시>-<공정코드>-<순번>`(예: `WO-2-PACK-1`), 원자재(공급사) LOT `<품목코드>-<순번 4자리>`(예: `RM-IC-0001`)입니다. 직접 조회할 수도 있습니다.
```sql
-- 완제품 포장 LOT 의 투입 이력: 기능검사 → 조립 → AOI 를 통과한 반제품 LOT 2종 → SMT → 자재투입 → 원자재 공급사 LOT
SELECT * FROM trace_backward('WO-2-PACK-1') ORDER BY depth, lot_no;
-- 원자재 LOT 리콜 범위: 이 공급사 LOT 이 들어간 모든 하위 LOT
SELECT * FROM trace_forward('RM-IC-0001') ORDER BY depth, lot_no;
```
위 예시는 README 작성 시 데모 실행(`--seed 42 --once 300`)에서 확인한 값입니다. `trace_backward('WO-2-PACK-1')` 은 15행(depth 1–6)을 반환했고, depth 3 의 반제품 LOT 는 모두 AOI 공정 LOT(`WO-1-AOI-1`, `WO-3-AOI-1`)였습니다. `trace_forward('RM-IC-0001')` 은 생산 LOT 약 2,950개 중 1,088개를 반환했습니다(공급사 LOT 1개가 쓰인 기간의 하위 LOT 만). 시작 시각이 실행 시점에 따라 달라 LOT 번호와 행 수는 달라질 수 있으니 `SELECT lot_no FROM lot LIMIT 10;` 으로 확인하세요.

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
`v_oee_daily` 는 설비 x 교대 x work_date 단위로 OEE = 가동률 x 성능률 x 품질률 을 계산합니다. 야간조의 자정 이후 구간은 교대가 시작된 전날 work_date 에 귀속시키고, 계획 비가동(점심·점검)은 계획시간에서 빼며, 교대 경계를 걸친 로그는 교대별로 잘라 계산합니다. 진행 중인 교대는 교대 창 끝 대신 `now()` 까지만 계획시간으로 보므로(유효 창 `LEAST(교대 끝, now())`), 교대 초반에도 가동률이 낮게 왜곡되지 않습니다. 생산수량이 0 인 행의 품질률은 정의되지 않으므로 NULL 입니다. 핵심 비율 계산부는 다음과 같습니다.

```sql
SELECT e.equipment_id, e.name AS equipment_name, a.shift_name, a.work_date, a.wstart, a.wend,
       LEAST(1, COALESCE(a.run_sec / NULLIF(a.shift_sec - a.planned_down_sec, 0), 0)) AS availability,
       COALESCE(r.ideal_sec / NULLIF(a.run_sec, 0), 0)                      AS performance,
       r.good_qty / NULLIF(r.good_qty + r.defect_qty, 0)                    AS quality
FROM agg a
JOIN equipment e ON e.equipment_id = a.equipment_id
LEFT JOIN res r ON r.equipment_id = a.equipment_id AND r.shift_id = a.shift_id
               AND r.work_date = a.work_date
```

대시보드의 "평균 OEE" 카드와 설비별 OEE 차트는 데이터가 있는 **최근 2개 교대 창(24시간)** 의 설비 x 교대 행 평균입니다(`dashboard/queries.py`, SQL 의 WHERE 로 범위 지정). 시뮬레이션 시작 무렵 일부만 덮인 첫 교대처럼 오래된 행이 평균을 왜곡하지 않게 하기 위해서입니다.

같은 파일에 불량률·FTY(`v_defect_rate`), 작업지시 진행률(`v_wo_progress`), 설비 현재 상태(`v_equipment_current`)도 있습니다.

## 성능 점검

KPI 뷰에 실적 100,000행을 적재해 측정했습니다. `v_oee_daily` 가 약 0.5초여서 일반 뷰를 유지했습니다. 방법과 한계는 [`docs/performance.md`](docs/performance.md) 를 참고하세요.

## 테스트

`pytest` 66개 (`tests/`): 스키마·제약(설비당 진행 중 로그 1개, 설비 ID 순서), 세션 시간대, 트리거(backflush, 초과생산, 재고 부족 롤백, 재고 행 없음 거부, 상태 전이), LOT 추적(순환 포함), 뷰(고정 시나리오, 야간조 귀속, 교대 경계 분할, 진행 중 교대의 now() 캡, 0 나눔·품질률 NULL), 시뮬레이터(seed 재현성, 라인별 작업지시, 일감 없을 때 자재대기, 완전한 교대의 성능률·OEE 범위, 검사 공정 불량 집중, LOT 계보가 라우팅을 따르는지, 교대 경계 실적 분할, 시계 규칙, 정지 처리, CLI 가 미래 시각을 쓰지 않는지), 대시보드 조회 함수(정렬, 최근 2교대 범위).

## 한계와 비목표

- **가상 데이터 기반**: 실제 PLC/OPC-UA 등 설비 연동은 없고 시뮬레이터가 대신합니다. 인증/권한, 멀티 사이트, 클라우드 배포, APS(스케줄링), ERP 연동은 범위 밖입니다.
- **입력 UI 없음**: 작업지시 등록·실적 입력 화면은 없습니다. 대시보드는 조회 전용입니다(LOT 추적 입력란 제외).
- **재고 규칙 단순화**: 소요 자재는 첫 공정에서 BOM 직계 자식만 차감하고, 결과물은 마지막 공정에서만 가산합니다. 단일 창고, 품목당 1행입니다.
- **LOT 계보는 시뮬레이터 규칙**: 시뮬레이터가 실제 투입량을 선입선출(FIFO)로 LOT 에 할당해 계보를 만듭니다. 완제품 조립은 반제품 라우팅의 마지막 공정(AOI)을 통과한 LOT 만, 후공정은 같은 작업지시의 바로 앞 공정 LOT 만, 첫 공정은 원자재 공급사 LOT(1만 개 단위, 여러 작업지시가 나눠 씀)를 투입합니다. 실제 현장의 바코드 스캔 같은 투입 실적이 아니라 규칙으로 만든 계보이며, 개별 시리얼 번호 추적은 제외했습니다. 원자재 LOT 는 계보용이며 재고 수량(`inventory`)과는 별도로 관리합니다.
- **FTY 는 공장 전체 단일 값**: 6개 공정의 `양품/투입` 곱이며 제품별 실제 경로 수율이 아닙니다.
- **OEE 성능률은 캡이 없습니다**: 시뮬레이터 데이터에서는 이상 사이클 대비 속도를 75–98%로 뽑지만, 실제 데이터에서 100%를 넘으면 그대로 나옵니다. 가동률만 최대 1로 캡합니다.
- **OEE 수치는 시뮬레이터 모델의 결과**: 데모 실행(`--once 300`)의 최근 2교대 평균 OEE 는 약 60%(가동률 약 72%, 성능률 약 86%, 품질률 약 97%)입니다. 가동률 손실은 대부분 자재대기(전공정 재공·반제품 재고·작업지시 교체 대기)이고 나머지는 고장·순간정지입니다. 시뮬레이터는 일감이 없는 설비를 RUN 이 아니라 IDLE(자재대기, 비계획)로 기록하고, 라인마다 SFG·FG 작업지시를 하나 이상 유지하며, 공정별 이상 사이클을 비슷하게 맞춰 두었습니다(`sql/02_seed.sql`). 시뮬레이션이 시작된 첫 교대는 시작 시각 이전 구간에 기록이 없어 가동률이 매우 낮게 나오므로 KPI 카드와 차트는 최근 2교대만 집계합니다(뷰 `v_oee_daily` 자체에는 모든 행이 있습니다).
- **시뮬레이터를 멈춘 동안**: 진행 중인 교대의 계획시간은 `now()` 까지 늘어나므로, 시뮬레이터를 멈춘 채 시간이 지나면 현재 교대의 가동률이 그만큼 내려갑니다(정지 처리된 IDLE 시간). 실제 공장에서 설비가 멈춘 것과 같은 해석입니다.
- **Docker 경로 미검증**: 작성자 환경에 Docker 가 없어 `docker-compose.yml` 은 직접 실행해 보지 못했습니다.
- 성능 측정은 단일 로컬 인스턴스의 수치입니다.
