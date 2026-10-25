# MES 웹 UI (React + FastAPI) 설계

## 의도와 이유
LG CNS Smart Factory 공고(Web UI(React 등), Python, Digital Twin 기반 시스템, 데이터베이스 + 제조 도메인 지식)에 맞춰, 이미 만든 PostgreSQL 기반 MES(스키마·트리거·SQL 지표·시뮬레이터)에 **React 웹 화면과 Python API**를 얹는다. 목표는 면접관이 브라우저에서 "공장이 돌아가는 것을 보고, 작업지시를 내리고, 실적을 입력하고, LOT를 추적"하는 것을 직접 확인하게 하는 것. 사용자가 원한 것은 "MES를 화면으로 볼 수 있는 UI".

## 현재 상태 (재사용)
- PostgreSQL 16 스키마 17개 테이블, 트리거(재고 backflush, 초과생산 차단, 상태 전이), LOT 추적 함수, KPI 뷰(`v_oee_daily`, `v_defect_rate`, `v_wo_progress`, `v_equipment_current`), 시뮬레이터(`simulator/simulate.py`), Streamlit 대시보드(`dashboard/`), pytest 66개, `mes.db.connect()`.
- 지표는 SQL에서 계산한다는 원칙 유지. API/React는 조회·표시·입력만 한다.

## 목표
- **FastAPI 백엔드**(`backend/`): psycopg 직접 SQL(ORM 없음). 기존 DB를 그대로 사용하고 스키마 변경은 최소화
- **React + TypeScript 프런트**(`frontend/`, Vite): 한국어 UI. 화면
  1. 대시보드: KPI 카드(평균 OEE, 불량률, 가동 설비 수), OEE/불량률 차트, 작업지시 진행률
  2. 공장 현황(Digital Twin 2D): 라인×공정 배치도에 설비가 RUN/IDLE/DOWN 색으로 실시간 표시, 설비 클릭 시 상세(현재 상태, 최근 OEE, 최근 실적)
  3. 작업지시: 목록(상태 필터), 신규 등록, 상세(진행률, 공정별 실적, 생성된 LOT)
  4. 생산실적 입력: 작업지시·공정·설비 선택, 양품/불량(불량코드·구분) 입력. 기존 트리거 규칙(재고 부족, 초과생산)이 거부하면 사유를 화면에 표시
  5. 설비 제어: 상태 변경(RUN/IDLE/DOWN + 사유코드), 상태 이력
  6. LOT 추적: LOT 번호 입력, 정/역방향 결과를 트리 또는 표로 표시
- 5초 주기 폴링으로 자동 갱신(TanStack Query `refetchInterval`)
- 시뮬레이터는 지금처럼 별도 프로세스로 실행하여 화면이 살아 움직이게 한다
- 백엔드 단위 테스트(pytest + FastAPI TestClient, 테스트 DB `mes_test`), 프런트는 타입체크·빌드와 핵심 컴포넌트 테스트(vitest) 소수
- README(한국어) 갱신: 아키텍처 그림, 실행법, 화면 스크린샷 여러 장

## 비목표
- AI·생성형 AI 기능, Unity 3D, Java/C# (사용자 결정: AI 제외)
- 로그인/권한, 멀티 사이트, 실제 PLC/OPC-UA 연동, 클라우드 배포, WebSocket(폴링으로 충분)
- 모바일 최적화 (데스크톱 브라우저 기준)
- 기존 Streamlit 앱 유지 보수 (React 화면이 완성되면 제거)

## 안티골
- 화면은 화려한데 지표를 JS/Python에서 계산하는 것 (SQL 지표 원칙 위반)
- 입력 화면이 DB 트리거를 우회해서 재고/상태 규칙이 깨지는 것 (모든 입력은 기존 INSERT 경로와 트리거를 통과)
- 처음 실행하는 사람이 명령 몇 줄로 띄우지 못하는 것

## 제약
- Windows 11, 작업 폴더 `C:\Users\jeong\MES`, 원격은 GitHub `Yuni-97-lab/Mes` (main)
- Node.js 미설치 → LTS를 winget(`OpenJS.NodeJS.LTS`)으로 설치 (시스템 설치이므로 알림)
- Python: Anaconda (`C:\Users\jeong\anaconda3\python.exe`, `python` PATH 스텁 주의), DB 접속은 `mes.db.connect()`(시간대 Asia/Seoul 고정)
- 모든 데이터는 가상

## 접근 방식
- **1. React + FastAPI 신규 구축 (선택)**: 공고의 "React + Python + DB" 조합과 정확히 일치. Streamlit 로직(`dashboard/queries.py`)의 SQL을 백엔드로 이전
- 2. Streamlit 확장: 빠르나 React 역량을 증명하지 못함 — 공고 목적과 불일치로 제외

## 결정된 것 (사용자 확인)
React 웹 UI + 조작 화면까지, FastAPI, AI 제외, 접근 방식 1.

## 내 판단 (확인 필요)
- 프런트: Vite + React 18 + TypeScript, 라우팅 React Router, 서버 상태 TanStack Query, 차트 Recharts, 스타일 일반 CSS 또는 Tailwind 중 가벼운 쪽 (빌더 선택)
- API는 REST/JSON, 경로 접두사 `/api`. 운영 빌드는 FastAPI가 `frontend/dist` 를 정적 서빙하여 `uvicorn` 한 줄로 실행, 개발 시 Vite dev server + 프록시
- Digital Twin은 SVG 기반 2D 배치도(라인 2개, 공정 6단계 순서대로 좌→우), 외부 3D 라이브러리 없음
- 입력 API는 단일 트랜잭션으로 기존 테이블에 INSERT, 트리거/체크 위반(CheckViolation, over-production)은 HTTP 409 + 한국어 사유로 응답
- `dashboard/` (Streamlit)는 React 완료 후 제거하고 README 갱신, 쿼리 SQL은 `backend/` 로 이동
- 작업지시 신규 등록 입력: 품목(FG/SFG), 라인, 수량, 납기일. 상태는 PLANNED로 생성
- 설비 제어 입력은 `equipment_status_log` 에 열린 로그를 닫고 새로 여는 동작(시뮬레이터와 같은 한 설비 한 열린 로그 제약 준수)

## 입력 규칙 (내 판단, 검토 단계에서 보강)
- **LOT**: 실적 입력 시 API가 LOT를 자동 생성한다(`WO-<작업지시>-<공정코드>-M<순번>`, 시뮬레이터 순번과 충돌하지 않도록 `M` 접두사). 앞 공정 LOT(같은 작업지시의 직전 공정 최신 LOT, 첫 공정이면 RM LOT)를 `lot_consumption` 으로 연결해 수동 입력분도 LOT 추적에 나타나게 한다. 계보 규칙은 시뮬레이터와 동일(반제품은 해당 품목의 마지막 공정 LOT만 소모)하며 공통 로직은 한 곳(`backend/` 의 서비스 함수)에 둔다
- **유효 조합**: 입력 폼은 연쇄 선택(작업지시 → 해당 품목 라우팅의 공정 → 해당 라인·공정의 설비)이며 목록용 조회 API를 둔다. 서버도 잘못된 조합을 422로 거부한다. DONE 작업지시에는 실적 입력 불가
- **상태 전이**: PLANNED → RUNNING → DONE 은 기존 트리거가 첫 실적/최종 공정 완료 시 처리한다(API는 건드리지 않음)
- **오류 처리**: 기존 트리거·제약 위반은 SQLSTATE(CheckViolation=23514, RaiseException=P0001) 와 메시지로 분류해 HTTP 409 + 한국어 사유로 응답. SQL 함수/트리거 수정은 허용하되 필요한 최소 범위(예: 오류 메시지 정리)
- **수동 입력과 시뮬레이터 동시 실행**: 수동 설비 상태 변경은 지속된다 — 시뮬레이터는 수동으로 바뀐 설비의 열린 로그를 자기 전이 규칙으로 닫을 수는 있으므로, 이를 막기 위해 설비에 `manual_hold` 개념은 두지 않고, 시연 안내를 README에 적는다(수동 제어를 시연할 때는 시뮬레이터를 멈추거나 느린 속도로 실행). 단순함 우선
- **시각·교대**: 입력 시각은 서버의 현재 시각(Asia/Seoul), 시작 시각은 `ended_at − 사이클 시간`이 아니라 사용자가 입력한 소요 분(기본 1분)으로 계산. 교대는 `ended_at` 시각으로 도출하며, 교대 경계에 걸치면 종료 시각 기준 교대로 귀속(분할하지 않음, 시뮬레이터와 다름을 문서화)
- **불량 입력**: 불량 행(불량코드, 구분 rework/scrap, 수량)의 목록으로 입력. `production_result.defect_qty` = 전체 불량 합(scrap+rework), `rework_qty` = rework 행 합. API가 합계를 계산해 저장하고 `defect_record` 와 일치시킨다
- **차트 범위**: 대시보드는 Streamlit과 동일(KPI·설비별 OEE는 최근 2개 교대 창, 공정별 불량률은 전체 누적). 쿼리 SQL을 그대로 이전
- **Digital Twin 배치**: 좌표 데이터 없음. 라인 × 공정 순서(seq)로 격자 배치하고, 한 셀에 설비가 여러 대면 셀 안에 나란히 표시. 현재 시드는 셀당 1대
- **완료 정의**: 모든 화면 동작 + 백엔드 테스트 통과 + 빌드 성공 + 스크린샷 5장 이상(대시보드, 공장 현황, 작업지시, 실적 입력, LOT 추적) README 포함. Streamlit(`dashboard/`)과 그 테스트는 React 화면이 모두 동작하는 마지막 태스크에서 삭제하고 쿼리 테스트는 백엔드 테스트로 이전
- **서비스 실행**: 개발은 uvicorn + `npm run dev`. 데모/운영은 `scripts/run_demo.ps1`(프런트 빌드 → uvicorn)로 한 번에 실행. `frontend/dist` 는 커밋하지 않는다

## 빌더에게 맡기는 것
API 경로·스키마 세부, 화면 레이아웃/스타일, 컴포넌트 구조, 폴더 구조 세부, 폴링 주기 미세조정, 테스트 범위.
