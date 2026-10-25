# MES 포트폴리오 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PostgreSQL 기반 가상 전자부품 공장 MES(스키마·SQL 지표·시뮬레이터·Streamlit 대시보드)를 만든다.

**Architecture:** 모든 비즈니스 로직과 지표는 `sql/` 의 번호순 SQL 파일(테이블→시드→함수/트리거→뷰)에 둔다. Python은 SQL 적용(`scripts/init_db.py`), 데이터 생성(`simulator/`), 조회 표시(`dashboard/`)만 담당하며 psycopg 3로 직접 SQL을 실행한다(ORM 없음).

**Tech Stack:** PostgreSQL 16 (docker-compose), Python 3.11+ (Anaconda), psycopg[binary] 3, pytest, Streamlit, pandas.

**Spec:** `docs/superpowers/specs/2026-10-25-mes-portfolio-design.md`

## Global Constraints

- DB는 PostgreSQL 16, 테이블/컬럼명 영문 snake_case, SQL 주석·대시보드 라벨·README는 한국어
- 지표(OEE, 불량률, 진행률, LOT 추적)는 SQL(뷰/함수)에서 계산한다. Python에서 계산 금지
- OEE = 가용률 × 성능률 × 양품률; 가용률 = (계획시간−비가동)/계획시간; 성능률 = (이론 사이클타임×총생산수량)/가동시간; 양품률 = 양품/총생산
- 이론 사이클타임은 `routing`(품목×공정) 단위. 계획 비가동은 `downtime_reason.is_planned = true` 로 구분하여 제외
- 불량은 `rework` / `scrap` 구분. 진행률 = 최종 공정 양품수량 / 지시수량
- LOT는 공정마다 생성, `lot_consumption` 부모-자식 연결, `WITH RECURSIVE` 정/역방향 추적, 시리얼 번호 없음
- 재고 차감은 생산실적 INSERT 트리거 backflush(BOM 소요량×(양품+불량)), 완제품은 양품만큼 증가. 잔고(`inventory`)+원장(`inventory_txn`), 단일 창고, 음수 재고는 CHECK 제약으로 차단
- 규모: 품목 약 10(완제품 3, 반제품 2, 원자재 5), 라인 2, 설비 약 10, 작업지시 수십 건. 공정: 자재투입→SMT→AOI검사→조립→기능검사→포장. 교대: 주간/야간
- 시뮬레이터는 배속 옵션, 대시보드는 5초 폴링. 지표 뷰는 일반 뷰로 시작, 느리면 머티리얼라이즈드 뷰
- 모든 데이터는 가상. Windows 11 / Git Bash·PowerShell에서 동작해야 함

## Review Focus

- 가동시간 0인 설비·교대의 OEE → 0 또는 NULL 반환, 0 나눗셈 오류 금지 (Task 5)
- 재고 부족 상태에서 생산실적 INSERT → 트랜잭션 전체 거부, 부분 반영 없음 (Task 3)
- 지시수량을 초과하는 생산실적 → 거부 (Task 3)
- 존재하지 않는 LOT 추적, 소모 이력이 없는 LOT → 빈 결과, 오류 없음 (Task 4)
- 시뮬레이터 중단 후 재시작 → 진행 중 작업지시를 이어서 진행, 중복 데이터 없음 (Task 6)
- 데이터가 하나도 없는 DB에서 대시보드 → 빈 화면 안내, 예외 없음 (Task 7)

---

## File Structure

| 파일 | 책임 |
|---|---|
| `docker-compose.yml`, `.env.example` | PostgreSQL 16 컨테이너, 접속 정보 |
| `requirements.txt` | psycopg, pytest, streamlit, pandas |
| `scripts/init_db.py` | `sql/*.sql` 을 번호순 적용, `--reset` 지원 |
| `mes/db.py` | `connect()` 접속 헬퍼 (환경변수 `DATABASE_URL`) |
| `sql/01_schema.sql` | 테이블·제약·인덱스 |
| `sql/02_seed.sql` | 마스터 데이터 (품목, BOM, 라우팅, 설비, 교대, 사유코드, 초기 재고) |
| `sql/03_functions_triggers.sql` | 생산실적 트리거, 재고 backflush, LOT 추적 함수 |
| `sql/04_views.sql` | OEE, 불량률, 진행률 뷰 |
| `simulator/simulate.py` | 작업지시 생성·설비 상태·생산실적 적재 |
| `dashboard/app.py` | Streamlit 대시보드 |
| `tests/` | pytest (실제 PostgreSQL 대상, 테스트 전용 DB `mes_test`) |
| `README.md`, `docs/erd.md` | 실행법, ERD(Mermaid), 지표 정의, 스크린샷 |

---

### Task 1: 환경·DB 부트스트랩

**Files:**
- Create: `docker-compose.yml`, `.env.example`, `requirements.txt`, `mes/__init__.py`, `mes/db.py`, `scripts/init_db.py`, `tests/conftest.py`, `tests/test_bootstrap.py`, `.gitignore`

**Interfaces:**
- Produces: `mes.db.connect(dbname: str | None = None) -> psycopg.Connection` (환경변수 `DATABASE_URL`, 기본 `postgresql://mes:mes@localhost:5432/mes`; `dbname` 지정 시 DB 이름만 교체)
- Produces: `scripts.init_db.apply_sql(conn, sql_dir: Path = Path("sql")) -> list[str]` (적용한 파일명 반환, 파일명 오름차순), CLI `python scripts/init_db.py [--reset] [--db NAME]`
- Produces: pytest fixture `db` (테스트 DB `mes_test`를 새로 만들어 스키마 적용 후 connection 제공, 각 테스트 후 롤백) 및 `seeded_db` (시드까지 적용)

- [ ] **Step 1: `git init`, `.gitignore`(`.env`, `__pycache__`, `.venv`) 작성 후 첫 커밋**
- [ ] **Step 2: Docker 사용 가능 여부를 `docker --version`으로 확인.** 가능하면 `docker-compose.yml`(postgres:16, 사용자/DB `mes`, 볼륨, 5432 포트)을 작성. 불가하면 PostgreSQL 16 네이티브 설치(winget `PostgreSQL.PostgreSQL.16`) 후 `mes` 사용자·DB·`mes_test` DB 생성 SQL을 `scripts/create_dbs.sql`로 제공. 어느 쪽이든 README에 둘 다 기술
- [ ] **Step 3: 실패하는 테스트 작성** `tests/test_bootstrap.py::test_connect_returns_pg16` — `connect().execute("show server_version_num").fetchone()[0]` 가 16xxxx 대 (`>= "160000"`); `test_apply_sql_runs_files_in_order` — 임시 디렉터리에 `02_b.sql`, `01_a.sql` 을 만들고 반환 리스트가 `["01_a.sql","02_b.sql"]`
- [ ] **Step 4:** `pytest tests/test_bootstrap.py -v` → FAIL (모듈 없음)
- [ ] **Step 5:** `requirements.txt` 설치(`pip install -r requirements.txt`), `mes/db.py`·`scripts/init_db.py`·`tests/conftest.py` 구현. `--reset` 은 `public` 스키마를 DROP/CREATE
- [ ] **Step 6:** `pytest tests/test_bootstrap.py -v` → PASS
- [ ] **Step 7: 커밋** `chore: DB bootstrap and test fixtures`

### Task 2: 스키마와 시드

**Files:**
- Create: `sql/01_schema.sql`, `sql/02_seed.sql`, `tests/test_schema.py`

**Interfaces:**
- Produces (테이블, 이후 모든 태스크가 사용): `item(item_id, item_code unique, name, item_type check in ('FG','SFG','RM'), unit)`, `bom(parent_item_id, child_item_id, qty_per numeric>0)`, `process(process_id, code, name, seq)`, `routing(item_id, process_id, seq, ideal_cycle_sec numeric>0)`, `line(line_id, name)`, `equipment(equipment_id, line_id, process_id, name)`, `shift(shift_id, name, start_time, end_time)`, `downtime_reason(reason_id, name, is_planned boolean)`, `defect_code(defect_id, name)`, `work_order(wo_id, item_id, line_id, planned_qty>0, status check in ('PLANNED','RUNNING','DONE'), due_date, created_at)`, `lot(lot_id, lot_no unique, item_id, wo_id null, process_id null, supplier_lot_no null, qty, created_at)`, `lot_consumption(parent_lot_id, child_lot_id, qty)` (parent=투입된 LOT, child=생성된 LOT; 자기참조 금지 CHECK), `production_result(result_id, wo_id, process_id, equipment_id, shift_id, lot_id, started_at, ended_at, good_qty>=0, defect_qty>=0, rework_qty>=0)`, `defect_record(result_id, defect_id, kind check in ('rework','scrap'), qty>0)`, `equipment_status_log(log_id, equipment_id, status check in ('RUN','IDLE','DOWN'), reason_id null, started_at, ended_at null)`, `inventory(item_id pk, qty numeric check >= 0)`, `inventory_txn(txn_id, item_id, delta, ref_result_id null, created_at)`
- 시드: 위 규모·공정·교대(주간 08–20, 야간 20–08)·사유코드(계획: 점심·정기점검 / 비계획: 설비고장·자재대기)·불량코드·원자재 초기 재고(충분히 큼)

- [ ] **Step 1: 실패하는 테스트** `test_schema.py` — `test_expected_tables_exist`(위 테이블 전부 `information_schema` 확인), `test_negative_inventory_rejected`(`inventory.qty=-1` INSERT 시 `psycopg.errors.CheckViolation`), `test_seed_counts`(item 10건 중 FG 3·SFG 2·RM 5, equipment 10, line 2, process 6, routing 행이 FG·SFG 품목마다 존재)
- [ ] **Step 2:** 실행해 FAIL 확인
- [ ] **Step 3:** `01_schema.sql`(FK·CHECK 포함, 조회용 인덱스: `production_result(equipment_id, started_at)`, `production_result(wo_id)`, `lot_consumption(parent_lot_id)`, `lot_consumption(child_lot_id)`, `equipment_status_log(equipment_id, started_at)`), `02_seed.sql` 작성. BOM은 FG→SFG→RM 2단계
- [ ] **Step 4:** PASS 확인 후 커밋 `feat: schema and master seed data`

### Task 3: 생산실적 트리거 (재고 backflush·초과 방지)

**Files:**
- Create: `sql/03_functions_triggers.sql`, `tests/test_triggers.py`

**Interfaces:**
- Consumes: Task 2 테이블 및 시드 (`seeded_db`)
- Produces: 트리거 `trg_production_result_ai` (AFTER INSERT on `production_result`) 와 BEFORE INSERT 검증 트리거 `trg_production_result_bi`. 동작: 해당 `wo.item_id` 의 BOM 직계 자식 소요량 × (good+defect) 만큼 `inventory` 차감하고 `inventory_txn` 기록(delta 음수); 해당 공정이 해당 품목 라우팅의 마지막 공정이면 완제품(또는 반제품) 재고를 good 만큼 증가(delta 양수); 작업지시 첫 실적 시 status `RUNNING`, 최종 공정 양품 누적이 planned_qty 이상이면 `DONE`
- BEFORE 트리거: 최종 공정 누적 양품 + 신규 good 이 `planned_qty` 초과 시 예외 `RAISE EXCEPTION 'work order over-production'`

- [ ] **Step 1: 실패하는 테스트** — `test_backflush_deducts_rm_and_adds_fg`(실적 1건 INSERT 후 RM 재고 감소량 = qty_per×(good+defect), `inventory_txn` 행 존재), `test_insufficient_stock_rejects_whole_insert`(원자재 재고를 0으로 만든 뒤 INSERT → `CheckViolation`, `production_result` 행 수 변화 없음), `test_overproduction_rejected`(planned_qty=10 작업지시에 good=11 → 예외), `test_status_transitions_to_running_then_done`
- [ ] **Step 2:** FAIL 확인
- [ ] **Step 3:** plpgsql 함수·트리거 구현. 재고 갱신은 `UPDATE inventory SET qty = qty + delta` 로 CHECK 제약이 거부를 담당
- [ ] **Step 4:** PASS 확인 후 커밋 `feat: backflush and over-production triggers`

### Task 4: LOT 추적 함수

**Files:**
- Modify: `sql/03_functions_triggers.sql`
- Create: `tests/test_lot_trace.py`

**Interfaces:**
- Produces: `trace_forward(p_lot_no text) returns table(lot_no text, item_code text, depth int)` (해당 LOT를 투입해 만들어진 모든 하위 LOT), `trace_backward(p_lot_no text) returns table(lot_no text, item_code text, supplier_lot_no text, depth int)` (해당 LOT의 원료 LOT들). 둘 다 `WITH RECURSIVE`, 순환 방지(방문 경로 배열 사용), 시작 LOT 자신은 제외, depth 1부터

- [ ] **Step 1: 실패하는 테스트** — 테스트가 직접 RM LOT `RM-A` → SFG LOT `SFG-1` → FG LOT `FG-1` 소모 체인을 INSERT 한 뒤: `trace_forward('RM-A')` 가 `[('SFG-1',1),('FG-1',2)]`, `trace_backward('FG-1')` 가 depth 1에 `SFG-1`, depth 2에 `RM-A`(supplier_lot_no 포함). `test_unknown_lot_returns_empty`(없는 LOT 번호 → 0행), `test_cycle_does_not_hang`(A→B, B→A 소모 행을 강제 INSERT해도 종료)
- [ ] **Step 2:** FAIL 확인 → **Step 3:** 구현 → **Step 4:** PASS 확인 후 커밋 `feat: lot genealogy recursive trace`

### Task 5: KPI 뷰 (OEE·불량률·진행률)

**Files:**
- Create: `sql/04_views.sql`, `tests/test_views.py`

**Interfaces:**
- Produces: `v_oee_daily(equipment_id, equipment_name, shift_name, work_date date, availability numeric, performance numeric, quality numeric, oee numeric)` (각 값 0~1, 가동시간 0이면 해당 비율은 0), `v_defect_rate(process_code, input_qty, defect_qty, scrap_qty, rework_qty, defect_rate, fty numeric)` (공정별, fty는 전체 공정 양품률의 곱), `v_wo_progress(wo_id, item_code, planned_qty, good_qty, progress_pct numeric, status, due_date)`, `v_equipment_current(equipment_id, name, status, since)` (최신 상태 로그 기준)
- Consumes: Task 2 테이블, 계획시간은 교대 길이(12h)에서 `is_planned` 사유 DOWN 구간을 제외한 값

- [ ] **Step 1: 실패하는 테스트** — 고정 시나리오 INSERT 후 값 검증: 12h 교대, 계획 비가동 1h, 비계획 DOWN 1h, 이론 사이클타임 60초, 총생산 400, 양품 380 → availability = (11−1)/11, performance = 60×400/(가동시간 초), quality = 0.95, `oee` = 세 값의 곱을 소수점 4자리까지 `pytest.approx` 확인. `test_oee_zero_runtime_is_zero_not_error`(상태 로그·실적이 없는 설비는 행이 나오되 oee=0 또는 뷰에서 제외, 예외 없음), `test_wo_progress_uses_last_process_good_qty`, `test_defect_rate_splits_rework_scrap`
- [ ] **Step 2:** FAIL 확인 → **Step 3:** 구현(`NULLIF` 로 0 나눗셈 방지) → **Step 4:** PASS 확인
- [ ] **Step 5:** 시드 + 임시 대량 데이터(실적 약 10만 행)로 `EXPLAIN ANALYZE` 를 실행해 `v_oee_daily` 가 1초 이내인지 확인. 초과 시 머티리얼라이즈드 뷰 `mv_oee_daily` + `refresh materialized view` 로 전환하고 뷰 이름은 유지. 결과 요약을 `docs/performance.md` 에 기록 후 커밋 `feat: KPI views`

### Task 6: 시뮬레이터

**Files:**
- Create: `simulator/__init__.py`, `simulator/simulate.py`, `tests/test_simulator.py`

**Interfaces:**
- Consumes: `mes.db.connect`, Task 3 트리거(재고·초과 거부 예외를 시뮬레이터가 잡아 해당 작업지시를 `DONE`/대기 처리)
- Produces: `simulate.step(conn, now: datetime, rng: random.Random) -> int` (한 틱 동안 적재한 production_result 행 수), `simulate.ensure_work_orders(conn, min_running: int = 3) -> int` (RUNNING 작업지시가 부족하면 새로 생성, 생성 수 반환), CLI `python -m simulator.simulate --speed 60 --seed 42 [--once N]`. `--speed`는 시뮬 시간/실시간 배율
- 동작: 설비별 상태(RUN/IDLE/DOWN) 로그를 확률적으로 전이(DOWN 시 비계획 사유 부여), RUN 중 사이클마다 실적 INSERT(불량률 약 2–5%, 불량은 `defect_record` 에 rework/scrap 비율 부여), 공정 순서대로 LOT 생성 및 `lot_consumption` 연결

- [ ] **Step 1: 실패하는 테스트** — `test_step_inserts_results_and_respects_seed`(같은 seed 두 번 실행한 결과 행 수 동일), `test_restart_does_not_duplicate_work_orders`(`ensure_work_orders` 를 두 번 호출해도 RUNNING 수가 `min_running` 을 넘지 않음), `test_defect_records_sum_matches_result`(각 실적의 `defect_qty` = `defect_record` 수량 합), `test_stock_exhaustion_does_not_crash`(원자재 재고 0 → `step` 이 예외 없이 0 반환)
- [ ] **Step 2:** FAIL 확인 → **Step 3:** 구현 → **Step 4:** PASS 확인
- [ ] **Step 5:** 개발 DB에서 `python scripts/init_db.py --reset` 후 `python -m simulator.simulate --speed 600 --once 200` 실행, `v_oee_daily`·`v_wo_progress` 에 행이 생기는지 확인. 커밋 `feat: factory simulator`

### Task 7: 대시보드

**Files:**
- Create: `dashboard/app.py`, `dashboard/queries.py`, `tests/test_dashboard_queries.py`

**Interfaces:**
- Consumes: Task 5 뷰, Task 4 함수
- Produces: `dashboard.queries` 의 `oee_by_equipment(conn) -> pd.DataFrame`, `wo_progress(conn) -> pd.DataFrame`, `defect_by_process(conn) -> pd.DataFrame`, `equipment_status(conn) -> pd.DataFrame`, `lot_trace(conn, lot_no: str, direction: str) -> pd.DataFrame`(direction은 `'forward'|'backward'`, 그 외 `ValueError`). 각 함수는 뷰/함수에 대한 SELECT 한 개만 수행
- `app.py` 구성: 상단 KPI 카드(평균 OEE, 불량률, 가동 설비 수), 설비 상태 표, 작업지시 진행률 바, 공정별 불량률 차트, LOT 추적 입력창(정/역방향). 5초 자동 새로고침(`st.fragment(run_every=5)` 또는 `streamlit-autorefresh`). 데이터 없으면 "데이터가 없습니다. 시뮬레이터를 실행하세요" 안내

- [ ] **Step 1: 실패하는 테스트** — `test_queries_return_dataframes_on_empty_db`(시드만 있는 DB에서 각 함수가 빈 DataFrame 반환, 예외 없음), `test_lot_trace_rejects_bad_direction`, `test_lot_trace_forward_columns`(컬럼 `lot_no,item_code,depth`)
- [ ] **Step 2:** FAIL 확인 → **Step 3:** 구현 → **Step 4:** PASS 확인
- [ ] **Step 5:** `streamlit run dashboard/app.py` 를 시뮬레이터 가동 상태에서 실행해 모든 구성 요소가 표시되는지, 빈 DB에서 안내문이 뜨는지 눈으로 확인. 커밋 `feat: streamlit dashboard`

### Task 8: 문서·스크린샷·마무리

**Files:**
- Create: `README.md`, `docs/erd.md`, `docs/screenshots/` 
- Modify: `docs/performance.md`

- [ ] **Step 1:** `docs/erd.md` 에 Mermaid ERD(전 테이블, 관계)와 지표 정의(Global Constraints의 OEE·불량률·진행률·재고·LOT 규칙)를 한국어로 작성
- [ ] **Step 2:** `README.md` — 프로젝트 목적(LG CNS 스마트팩토리 지원용 가상 공장), 아키텍처 한 장 요약, 실행법(Docker 경로 / 네이티브 경로, `init_db → simulate → streamlit` 명령 순서), 주요 SQL 하이라이트(트리거·재귀 CTE·OEE 뷰 링크), 스크린샷, 가상 데이터 고지
- [ ] **Step 3:** 깨끗한 상태에서 README의 명령만으로 처음부터 재현(`--reset` 포함)해 동작 확인. 대시보드 스크린샷을 `docs/screenshots/` 에 저장하고 README에 삽입
- [ ] **Step 4:** 전체 `pytest -v` 통과 확인. 커밋 `docs: README, ERD, screenshots`

---

## Self-Review 결과

- 스펙 커버리지: 스키마·시드(T2), 트리거·재고(T3), LOT(T4), OEE·불량·진행률(T5), 시뮬레이터(T6), 대시보드(T7), README/ERD/스크린샷/재현성(T1·T8) 모두 대응
- 이름 일관성: `trace_forward/backward`, `v_oee_daily`, `v_wo_progress`, `v_defect_rate`, `v_equipment_current`, `mes.db.connect` 가 태스크 간 동일
- 분량: 스펙 대비 과하지 않도록 SQL/함수 본문은 작성하지 않고 시그니처·테스트·값만 명시
