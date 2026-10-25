# MES 포트폴리오: PostgreSQL + FastAPI + React 스마트팩토리

> **가상 데이터 고지**: 이 프로젝트의 공장, 품목, 설비, LOT, 수량, 불량 등 모든 데이터는 시드 SQL 과 시뮬레이터가 만든 **가상 데이터**입니다. 실제 기업·공장의 데이터가 아닙니다.

![MES 대시보드](docs/screenshots/dashboard.png)

## 목적

스마트팩토리 직무 지원용 포트폴리오입니다. 가상의 전자부품 공장(SMT/조립 라인 2개, 설비 12대)을 대상으로 MES 업무 흐름을 PostgreSQL 데이터 모델과 SQL 로 구현하고, 그 위에 **Python(FastAPI) API** 와 **React 웹 화면**을 얹었습니다. 브라우저에서 공장이 돌아가는 모습을 보고, 작업지시를 등록하고, 생산실적을 입력하고, LOT 를 추적하고, 설비 상태를 바꿀 수 있습니다. 설비 데이터는 시뮬레이터가 계속 적재하므로 화면이 살아 움직입니다.

원칙은 하나입니다. **모든 KPI 는 SQL 뷰/함수/트리거에서 계산하고, Python API 와 React 는 조회·표시·입력만 합니다.** 입력 화면도 트리거를 우회하지 않고 같은 INSERT 경로를 지나므로 재고 부족이나 초과생산은 DB 규칙이 거부하고 화면에는 한국어 사유가 표시됩니다.

## 무엇을 보여주는가

| 직무 관심 영역 | 이 프로젝트에서 |
|---|---|
| Web UI (React) | React 19 + TypeScript + Vite, React Router, TanStack Query(5초 폴링), Recharts. 6개 화면, vitest 컴포넌트 테스트 |
| Python | FastAPI 백엔드(psycopg 직접 SQL, ORM 없음), 요청당 트랜잭션, DB 오류를 HTTP 409/422 + 한국어 메시지로 변환, 공장 시뮬레이터, pytest |
| Digital Twin (2D 배치도) | 라인 x 공정 순서대로 배치한 SVG 공장 배치도. 설비가 RUN/IDLE/DOWN 색으로 실시간 표시되고 클릭하면 상세(현재 상태·사유, 최근 OEE, 최근 실적)가 열림 |
| DB + 제조 도메인 | 테이블 17개, 트리거(재고 backflush, 초과생산 차단, 상태 전이), `WITH RECURSIVE` LOT 정/역방향 추적, OEE·불량률·FTY·진행률 뷰 |

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

시뮬레이터가 설비 상태 로그와 생산실적을 PostgreSQL 에 INSERT 하면, 트리거가 재고와 작업지시 상태를 갱신하고 뷰/함수가 KPI 를 계산합니다. FastAPI 는 뷰/함수를 SELECT 해 JSON 으로 내보내고(그리고 입력 요청을 같은 테이블에 INSERT), React 는 5초마다 API 를 다시 조회해 화면을 갱신합니다. 데모 실행에서는 FastAPI 가 빌드된 React 정적 파일까지 서빙하므로 포트 하나(8000)만 씁니다.

```mermaid
flowchart LR
    SIM["simulator/simulate.py<br/>설비 상태, 생산실적, 불량, LOT 적재"] -->|INSERT| DB[("PostgreSQL 16<br/>테이블 / 트리거 / 뷰 / 함수")]
    DB -->|"SELECT (v_oee_daily, v_defect_rate, v_wo_progress, v_equipment_current, trace_*)"| API["FastAPI<br/>backend/app"]
    API -->|"INSERT (작업지시, 실적, 설비 상태)"| DB
    API <-->|"REST /api/*, 5초 폴링"| UI["React + TypeScript<br/>frontend/"]
```

## 화면

모든 스크린샷은 시뮬레이터가 돌고 있는 실제 실행 화면입니다(가상 데이터, 헤드리스 Edge 로 캡처). 시뮬레이터로 약 50시간(`--once 300`, 틱 10분)을 채운 뒤 `--speed 60` 연속 모드를 켜 둔 상태이며, 화면 값은 실행 시점에 따라 달라집니다.

### 1. 대시보드 (`/`)
![대시보드](docs/screenshots/dashboard.png)

KPI 카드(최근 24시간(2교대) 평균 OEE, 공정 전체 누적 불량률, 가동 설비 수), 설비별 OEE 와 공정별 불량률 차트, 진행 중 작업지시 진행률. 수치는 전부 SQL 뷰의 결과입니다.

### 2. 공장 현황 — Digital Twin 2D (`/floor`)
![공장 현황](docs/screenshots/floor.png)

라인 x 공정 순서의 배치도에서 설비가 가동(초록)/대기(노랑)/정지(빨강) 로 표시됩니다. 설비를 클릭하면 오른쪽에 상태·사유·시작 시각, 최근 교대별 가동/성능/양품률과 OEE, 최근 실적이 나옵니다. 위 캡처는 `L1-SMT-01` 을 설비 제어 화면에서 설비고장으로 정지시킨 뒤 선택한 모습입니다.

### 3. 작업지시 (`/work-orders`)
![작업지시](docs/screenshots/work-orders.png)

상태별 필터, 진행률 막대. 오른쪽 위 "신규 등록" 으로 품목(완제품/반제품)·라인·수량·납기일을 입력해 PLANNED 작업지시를 만듭니다. 행을 클릭하면 상세(공정별 누적 양품/불량, 생성된 LOT 목록)로 이동합니다.

### 4. 실적 입력 (`/results/new`)
![실적 입력](docs/screenshots/result-entry.png)

작업지시 → 해당 품목 라우팅의 공정 → 해당 라인·공정의 설비를 연쇄 선택하고, 양품 수량·소요 시간·불량 내역(불량코드, 재작업/폐기, 수량)을 입력합니다. 서버가 LOT 를 자동 생성하고 직전 공정 LOT(첫 공정이면 원자재 공급사 LOT)와 계보로 연결합니다. 재고 부족·초과생산 같은 DB 규칙 위반은 409 와 한국어 사유로 화면에 표시됩니다.

![실적 등록 완료](docs/screenshots/result-entry-saved.png)

등록하면 생성된 LOT 번호(`WO-<작업지시>-<공정코드>-M<순번>`)가 링크로 나오고, 누르면 LOT 추적 화면으로 이동합니다.

### 5. LOT 추적 (`/lots`)
![LOT 추적](docs/screenshots/lot-trace.png)

LOT 번호와 방향(정방향: 이 LOT 로 만든 LOT, 역방향: 이 LOT 의 원료 LOT)을 고르면 `trace_forward` / `trace_backward` 결과를 깊이별 트리로 보여 줍니다. 위 캡처는 화면에서 수동 입력한 포장 LOT `WO-58-PACK-M1` 의 역방향 추적입니다. 기능검사 → 조립 → 시뮬레이터가 만든 반제품(AOI → SMT → 자재투입) LOT 와 원자재 공급사 LOT 까지 거슬러 올라갑니다. 결과의 LOT 번호를 누르면 그 LOT 를 다시 추적합니다.

### 6. 설비 제어 (`/equipment`)
![설비 제어](docs/screenshots/equipment.png)

설비별로 상태(가동/대기/정지)와 비가동 사유를 골라 변경합니다. 정지(DOWN)는 사유가 필수입니다. 열려 있는 상태 로그를 닫고 새 로그를 여는 동작이며(설비당 진행 중 로그는 1개라는 DB 제약 준수), "이력" 버튼으로 상태 이력을 봅니다. 위 캡처에서 `L1-SMT-01` 이 설비고장으로 정지 중입니다.

## 프로젝트 구조

```
.
├── sql/
│   ├── 01_schema.sql              # 테이블 17개, 제약, 인덱스
│   ├── 02_seed.sql                # 마스터 시드 (품목 10, 공정 6, 설비 12, 교대 2 ...)
│   ├── 03_functions_triggers.sql  # 실적 트리거(재고 backflush, 초과생산 방지), LOT 추적 함수
│   └── 04_views.sql               # v_oee_daily, v_defect_rate, v_wo_progress, v_equipment_current
├── backend/app/                   # FastAPI
│   ├── main.py                    # 앱 생성, /api/health, frontend/dist 정적 서빙 + SPA 라우트 fallback
│   ├── routers/read.py            # 조회 API (KPI, OEE, 불량률, 설비, 작업지시, LOT 추적, 목록 옵션)
│   ├── routers/write.py           # 입력 API (작업지시 등록, 실적 입력, 설비 상태 변경)
│   ├── services/results.py        # 실적 입력: LOT 생성·계보 연결·불량 내역 (시뮬레이터와 같은 계보 규칙)
│   ├── schemas.py, errors.py      # 요청/응답 모델, DB 오류 -> HTTP 409 변환
│   └── deps.py                    # 요청당 DB 연결(성공 시 commit)
├── frontend/                      # React + TypeScript (Vite)
│   └── src/{pages,components,api}/  # 화면 6개, 배치도(FloorMap), LOT 트리, API 훅
├── simulator/simulate.py          # 공장 시뮬레이터 (CLI)
├── mes/db.py                      # DATABASE_URL 연결 헬퍼
├── scripts/                       # run_demo.ps1, init_db.py, create_dbs.sql, docker_init_test_db.sh
├── tests/                         # pytest (mes_test DB 사용). tests/api 는 FastAPI TestClient
├── docs/                          # erd.md, performance.md, screenshots/
├── docker-compose.yml             # PostgreSQL 16 (Docker 경로)
├── requirements.txt
└── .env.example
```

## 빠른 시작 (Windows)

사전 준비: Python 3.10 이상, PostgreSQL 16, Node.js LTS(프런트 빌드용). 아래는 PowerShell 기준이며 저장소 루트에서 실행합니다. 이 프로젝트는 Anaconda Python 3.13 과 Node.js 24 로 개발·검증했습니다(코드가 `X | None` 타입 표기를 쓰므로 Python 3.10 이상 필요).

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

### 2. Python 패키지, Node.js
```powershell
pip install -r requirements.txt
winget install OpenJS.NodeJS.LTS   # Node 가 없을 때만. 설치 후 새 터미널을 엽니다.
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

### 4. 데모 실행
```powershell
# (1) 스키마·시드 적용. --reset 은 public 스키마를 DROP 후 다시 만든다 (개발 DB 데이터 삭제)
python scripts/init_db.py --reset

# (2) 데이터 채우기: 지금까지의 약 50시간(10분 틱 300개)을 한 번에 채우고 종료
python -m simulator.simulate --speed 600 --seed 42 --once 300

# (3) 시뮬레이터를 계속 돌려 화면이 움직이게 하기: 별도 터미널에서 실행 (Ctrl+C 로 중단)
python -m simulator.simulate --speed 60 --seed 42

# (4) 웹 UI: 프런트 빌드(frontend/dist 가 없을 때만) + uvicorn 을 한 번에 실행
powershell -ExecutionPolicy Bypass -File scripts/run_demo.ps1
```
브라우저에서 <http://localhost:8000> 을 엽니다. (2) 는 데이터만 채우고 끝나므로 화면에 값은 나오지만 움직이지는 않고, 종료 시 설비를 모두 IDLE 로 닫기 때문에 가동 설비 수가 0 으로 보입니다. (3) 을 켜면 설비가 다시 가동됩니다. (3) 은 (2) 로 채운 뒤 이어서 실시간으로 적재합니다(DB 에 데이터가 있으면 마지막 시각부터 이어 감).

`scripts/run_demo.ps1` 옵션: `-Rebuild`(프런트를 다시 빌드), `-Port 8000`, `-BindHost 127.0.0.1`, `-Python C:\경로\python.exe`. 스크립트는 `python` 이 Windows 스토어 스텁이 아니라 실제 인터프리터인지 확인하고, 아니면 Anaconda/Miniconda/설치형 Python 의 알려진 경로를 찾으며, 그래도 없으면 `-Python` 으로 지정하라고 안내합니다. `npm` 이 PATH 에 없으면 `C:\Program Files\nodejs` 를 찾습니다. 프런트는 `npm ci` 와 `npm run build` 로 빌드하며 결과는 `frontend/dist`(커밋하지 않음)에 생깁니다.

**수동 실행 (스크립트 없이, bash 등)**
```bash
(cd frontend && npm ci && npm run build)
python -m uvicorn backend.app.main:app --port 8000
```
`frontend/dist` 가 있으면 FastAPI 가 `/` 와 `/floor`, `/work-orders/12` 같은 SPA 경로에 `index.html` 을, `/assets/*` 에 빌드 산출물을 돌려주고 `/api/*` 는 계속 API 가 처리합니다(없는 `/api` 경로는 JSON 404). `frontend/dist` 가 없으면 API 만 뜹니다.

### 개발 모드 (프런트 핫 리로드)
```bash
# 터미널 1: API (코드 변경 시 자동 재시작)
python -m uvicorn backend.app.main:app --reload --port 8000
# 터미널 2: Vite 개발 서버. /api 요청은 localhost:8000 으로 프록시됨
cd frontend
npm install
npm run dev        # http://localhost:5173
```

### 시뮬레이터 옵션과 시계 규칙
시뮬레이터 옵션: `--speed`(기본 60), `--seed`, `--once N`, `--tick`(기본 1초). 시계 규칙은 다음과 같습니다.

- **시뮬 시각은 현재 시각(벽시계)을 넘지 않습니다.** 미래 시각의 데이터는 만들지 않으므로 대시보드 지표가 실제 시각과 어긋나지 않습니다.
- 틱 길이 = `--tick x --speed` 시뮬 초 (기본 60초, `--speed 600` 이면 10분).
- 시작점: 빈 DB 에서 `--once N` 은 "지금 - N틱" 부터 시작해 마지막 틱이 지금이 되고, 연속 모드는 현재 교대 시작 시각부터 채웁니다. DB 에 데이터가 있으면 마지막 시각부터 이어 갑니다.
- 연속 모드: 현재 시각보다 뒤처져 있는 동안은 실시간 `--tick` 초마다 한 틱씩(= `--speed` 배속) 따라잡고, 따라잡은 뒤에는 실제 시간이 한 틱 길이만큼 흐를 때마다 한 틱을 진행합니다. 즉 `--speed` 는 따라잡는 속도와 틱 길이만 정합니다.
- `--once N`: 최대 N틱을 기다림 없이 실행하고, 현재 시각에 닿으면 더 일찍 끝냅니다(예: 방금 채운 DB 에서 다시 실행하면 진행할 틱이 없음).
- 정지: 정상 종료·Ctrl+C 시 진행 중 설비 로그를 마지막 시뮬 시각에 닫고 IDLE 로 남깁니다. 멈춰 있는 동안 RUN 시간이 쌓이지 않습니다(가동률은 정지 시간만큼 내려감). 오래 멈춘 뒤(마지막 시각이 시작점 이전) 재시작하면 마지막 시각에 설비를 정지 처리하고 시작점부터 새로 채웁니다. 프로세스를 강제 종료한 경우에는 `python -m simulator.simulate --once 1 --speed 600` 을 한 번 실행하면 진행할 틱 없이 정지 처리만 하고 끝납니다.

## 테스트

```powershell
pytest -q                       # 백엔드/SQL/시뮬레이터 (mes_test DB, 약 3분)
cd frontend; npm test           # vitest 컴포넌트 테스트 (npx vitest run 과 동일)
cd frontend; npm run build      # 타입체크(tsc -b) + 프로덕션 빌드
```

- `pytest` 108개: 스키마·제약(설비당 진행 중 로그 1개, 설비 ID 순서), 세션 시간대, 트리거(backflush, 초과생산, 재고 부족 롤백, 재고 행 없음 거부, 상태 전이), LOT 추적(순환 포함), 뷰(고정 시나리오, 야간조 귀속, 교대 경계 분할, 진행 중 교대의 now() 캡, 0 나눔·품질률 NULL), 시뮬레이터(seed 재현성, 라인별 작업지시, 일감 없을 때 자재대기, 완전한 교대의 성능률·OEE 범위, 검사 공정 불량 집중, LOT 계보가 라우팅을 따르는지, 교대 경계 실적 분할, 시계 규칙, 정지 처리, CLI 가 미래 시각을 쓰지 않는지), API(`tests/api`: 조회 엔드포인트와 직렬화, 실제 행이 있을 때 KPI/OEE/불량률 값, 작업지시 등록, 실적 입력의 LOT·계보·수불 생성과 순번, 재고 부족·초과생산 409, 잘못된 조합 422/404, 설비 상태 변경, 정적 서빙과 SPA fallback).
- `vitest` 49개: 배치도, 상태 배지, 작업지시 등록 폼, 실적 입력 폼 검증, LOT 추적 화면, 대시보드.
- `pytest` 는 `mes_test` DB 만 사용하며(세션 시작 시 그 DB 의 public 스키마를 비움), 개발 DB 는 건드리지 않습니다. 테스트는 `mes` 롤이 `mes_test` 에 접속할 수 있어야 하므로 1단계의 DB 생성이 필요합니다.

## 시연 순서

시뮬레이터(3)를 켠 채 <http://localhost:8000> 에서 다음 순서로 보여 줍니다.

1. **대시보드**: KPI 카드와 설비별 OEE, 공정별 불량률이 5초마다 갱신되는 것을 확인합니다.
2. **공장 현황**: 배치도에서 설비 상태 색이 바뀌는 것을 보고, 설비 하나를 눌러 최근 OEE 와 실적을 봅니다.
3. **작업지시 등록**: "신규 등록" 으로 완제품(예: 센서 모듈 A100)·라인·수량·납기일을 입력합니다. PLANNED 로 생성됩니다.
4. **실적 입력**: 방금 만든 작업지시를 선택해 첫 공정부터 양품·불량을 입력합니다. 생성된 LOT 번호(`WO-<작업지시>-<공정>-M1`)가 표시되고, 작업지시 상태가 PLANNED → RUNNING 으로 바뀝니다. 앞 공정 LOT 가 필요한 완제품은 같은 방식으로 공정을 차례로 입력합니다. 계획 수량을 넘기거나 재고가 모자라게 입력하면 거부 사유가 표시됩니다.
5. **LOT 추적**: 실적 입력 완료 화면의 LOT 링크로 이동해 역방향 추적으로 원자재 공급사 LOT 까지 거슬러 올라가고, 원자재 LOT 를 눌러 정방향으로 리콜 범위를 보여 줍니다.
6. **설비 제어**: 설비 하나를 정지(DOWN, 사유 선택)로 바꾸고 공장 현황에서 빨간색으로 바뀐 것을 확인한 뒤, 가동으로 복구합니다.

주의: 6번의 수동 상태 변경은 시뮬레이터가 돌고 있으면 시뮬레이터의 자체 전이 규칙(고장·자재대기 등)이 그 설비의 열린 로그를 닫고 덮어쓸 수 있습니다(설비에 "수동 고정" 개념은 두지 않았습니다). 확실히 시연하려면 시뮬레이터를 멈추거나 `--speed` 를 낮춰 실행하세요. 정상 종료(Ctrl+C)하면 모든 설비가 IDLE 로 닫히므로 시연 전에 상태 변경으로 가동 상태를 만들어 둡니다.

## 직접 SQL 로 LOT 추적

번호 형식은 생산 LOT `WO-<작업지시>-<공정코드>-<순번>`(예: `WO-2-PACK-1`), 화면에서 수동 입력한 실적의 LOT `WO-<작업지시>-<공정코드>-M<순번>`(예: `WO-58-PACK-M1`), 원자재(공급사) LOT `<품목코드>-<순번 4자리>`(예: `RM-IC-0001`)입니다.
```sql
-- 완제품 포장 LOT 의 투입 이력: 기능검사 → 조립 → AOI 를 통과한 반제품 LOT 2종 → SMT → 자재투입 → 원자재 공급사 LOT
SELECT * FROM trace_backward('WO-2-PACK-1') ORDER BY depth, lot_no;
-- 원자재 LOT 리콜 범위: 이 공급사 LOT 이 들어간 모든 하위 LOT
SELECT * FROM trace_forward('RM-IC-0001') ORDER BY depth, lot_no;
```
위 예시는 데모 실행(`--seed 42 --once 300`)에서 확인한 값입니다. `trace_backward('WO-2-PACK-1')` 은 15행(depth 1–6)을 반환했고, depth 3 의 반제품 LOT 는 모두 AOI 공정 LOT(`WO-1-AOI-1`, `WO-3-AOI-1`)였습니다. `trace_forward('RM-IC-0001')` 은 생산 LOT 약 2,950개 중 1,088개를 반환했습니다(공급사 LOT 1개가 쓰인 기간의 하위 LOT 만). 시작 시각이 실행 시점에 따라 달라 LOT 번호와 행 수는 달라질 수 있으니 `SELECT lot_no FROM lot LIMIT 10;` 으로 확인하세요.

## SQL 하이라이트

### 1. 재고 backflush 트리거 — [`sql/03_functions_triggers.sql`](sql/03_functions_triggers.sql)
`production_result` INSERT 직후, 품목 라우팅의 첫 공정 실적에서만 BOM 직계 자식 자재를 `qty_per x (양품+불량)` 만큼 차감하고 수불 원장에 기록합니다. 마지막 공정 실적은 완제품/반제품 재고를 양품만큼 늘립니다. 재고가 모자라면 `inventory` 의 `CHECK (qty >= 0)` 위반으로 INSERT 전체가 롤백됩니다. 같은 파일의 BEFORE INSERT 트리거는 작업지시 행을 `FOR UPDATE` 로 잠그고 초과생산을 막습니다. 웹의 실적 입력도 이 트리거를 그대로 지나며, API 는 위반을 HTTP 409 로 바꿔 줄 뿐입니다.

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

대시보드의 "평균 OEE" 카드와 설비별 OEE 차트는 데이터가 있는 **최근 2개 교대 창(24시간)** 의 설비 x 교대 행 평균입니다(`backend/app/routers/read.py` 의 `RECENT_OEE`, SQL 의 WHERE 로 범위 지정). 시뮬레이션 시작 무렵 일부만 덮인 첫 교대처럼 오래된 행이 평균을 왜곡하지 않게 하기 위해서입니다.

같은 파일에 불량률·FTY(`v_defect_rate`), 작업지시 진행률(`v_wo_progress`), 설비 현재 상태(`v_equipment_current`)도 있습니다.

## 설계 결정

- **지표는 SQL, API 는 얇게**: API 는 뷰/함수를 SELECT 해 직렬화만 하고 JS/Python 에서 KPI 를 다시 계산하지 않습니다. ORM 없이 psycopg 로 SQL 을 그대로 보이게 썼습니다.
- **입력도 DB 규칙을 통과**: 실적 입력은 savepoint 안에서 LOT·계보·실적·불량 내역을 한꺼번에 INSERT 하고, 트리거나 CHECK 가 거부하면 전부 롤백합니다(`backend/app/services/results.py`). 요청 단위로 성공 시 commit, 예외 시 rollback 합니다(`backend/app/deps.py`).
- **수동 LOT 와 시뮬레이터 LOT 구분**: 수동 입력 LOT 는 `-M<순번>` 접미사를 써서 시뮬레이터의 순번과 충돌하지 않고, 계보 규칙(직전 공정 LOT, 첫 공정은 원자재 공급사 LOT, 완제품 조립은 반제품 AOI LOT)은 시뮬레이터 함수를 재사용해 같게 유지했습니다.
- **폴링**: 화면은 5초 주기 폴링(TanStack Query `refetchInterval`)입니다. 이 규모에서는 WebSocket 없이도 충분하고 서버가 단순합니다.
- **배치도는 격자**: 좌표 테이블 없이 라인 x 공정 순서로 격자 배치한 SVG 입니다(외부 3D/배치 라이브러리 없음). 한 셀에 설비가 여럿이면 나란히 표시하도록 했지만 현재 시드는 셀당 1대입니다.
- **서빙**: 데모는 FastAPI 가 `frontend/dist` 를 함께 서빙해 한 줄로 실행하고, 개발은 uvicorn + Vite 프록시로 분리합니다.

## 성능 점검

KPI 뷰에 실적 100,000행을 적재해 측정했습니다. `v_oee_daily` 가 약 0.5초여서 일반 뷰를 유지했습니다. 방법과 한계는 [`docs/performance.md`](docs/performance.md) 를 참고하세요.

## 한계와 비목표

- **가상 데이터 기반**: 실제 PLC/OPC-UA 등 설비 연동은 없고 시뮬레이터가 대신합니다. 멀티 사이트, 클라우드 배포, APS(스케줄링), ERP 연동, AI/생성형 AI 기능은 범위 밖입니다.
- **로그인·권한 없음**: API 에 인증이 없어 화면에서 누구나 작업지시 등록, 실적 입력, 설비 상태 변경을 할 수 있습니다. 로컬 데모 용도이며 외부에 노출하면 안 됩니다. 기본 바인딩도 `127.0.0.1` 입니다.
- **폴링이며 실시간 푸시 아님**: 5초 지연이 있고 WebSocket/SSE 는 쓰지 않았습니다. 모바일 화면 최적화도 하지 않았습니다(데스크톱 브라우저 기준).
- **수동 입력은 단순화**: 실적 시각은 서버의 현재 시각(KST)이고 시작 시각은 입력한 소요 시간(분, 0 초과 60 이하)으로 계산합니다. 교대는 종료 시각 기준으로 귀속하며 교대 경계에서 실적을 나누지 않습니다(시뮬레이터는 나눕니다). 작업지시의 상태 변경 화면은 없고 PLANNED → RUNNING → DONE 은 트리거가 처리합니다.
- **수동 설비 제어와 시뮬레이터 충돌**: 시뮬레이터가 돌고 있으면 수동 상태 변경이 시뮬레이터에 의해 덮일 수 있습니다(시연 순서 참고).
- **재고 규칙 단순화**: 소요 자재는 첫 공정에서 BOM 직계 자식만 차감하고, 결과물은 마지막 공정에서만 가산합니다. 단일 창고, 품목당 1행입니다.
- **LOT 계보는 시뮬레이터 규칙**: 시뮬레이터가 실제 투입량을 선입선출(FIFO)로 LOT 에 할당해 계보를 만듭니다. 완제품 조립은 반제품 라우팅의 마지막 공정(AOI)을 통과한 LOT 만, 후공정은 같은 작업지시의 바로 앞 공정 LOT 만, 첫 공정은 원자재 공급사 LOT(1만 개 단위, 여러 작업지시가 나눠 씀)를 투입합니다. 실제 현장의 바코드 스캔 같은 투입 실적이 아니라 규칙으로 만든 계보이며, 개별 시리얼 번호 추적은 제외했습니다. 원자재 LOT 는 계보용이며 재고 수량(`inventory`)과는 별도로 관리합니다.
- **FTY 는 공장 전체 단일 값**: 6개 공정의 `양품/투입` 곱이며 제품별 실제 경로 수율이 아닙니다.
- **OEE 성능률은 캡이 없습니다**: 시뮬레이터 데이터에서는 이상 사이클 대비 속도를 75–98%로 뽑지만, 실제 데이터에서 100%를 넘으면 그대로 나옵니다. 가동률만 최대 1로 캡합니다.
- **OEE 수치는 시뮬레이터 모델의 결과**: 데모 실행(`--once 300`)의 최근 2교대 평균 OEE 는 약 60%(가동률 약 72%, 성능률 약 86%, 품질률 약 97%)입니다. 가동률 손실은 대부분 자재대기(전공정 재공·반제품 재고·작업지시 교체 대기)이고 나머지는 고장·순간정지입니다. 시뮬레이터는 일감이 없는 설비를 RUN 이 아니라 IDLE(자재대기, 비계획)로 기록하고, 라인마다 SFG·FG 작업지시를 하나 이상 유지하며, 공정별 이상 사이클을 비슷하게 맞춰 두었습니다(`sql/02_seed.sql`). 시뮬레이션이 시작된 첫 교대는 시작 시각 이전 구간에 기록이 없어 가동률이 매우 낮게 나오므로 KPI 카드와 차트는 최근 2교대만 집계합니다(뷰 `v_oee_daily` 자체에는 모든 행이 있습니다).
- **시뮬레이터를 멈춘 동안**: 진행 중인 교대의 계획시간은 `now()` 까지 늘어나므로, 시뮬레이터를 멈춘 채 시간이 지나면 현재 교대의 가동률이 그만큼 내려갑니다(정지 처리된 IDLE 시간). 실제 공장에서 설비가 멈춘 것과 같은 해석입니다.
- **Docker 경로 미검증**: 작성자 환경에 Docker 가 없어 `docker-compose.yml` 은 직접 실행해 보지 못했습니다. `scripts/run_demo.ps1` 도 Windows PowerShell 5.1 기준이며 macOS/Linux 에서는 위의 수동 실행 명령을 쓰십시오(그 경로는 직접 검증하지 못했습니다).
- 성능 측정은 단일 로컬 인스턴스의 수치입니다.
