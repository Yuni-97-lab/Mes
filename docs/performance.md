# 성능 점검: KPI 뷰

## 방법
- `mes_test` DB 에 스키마+시드를 적용한 뒤 **트랜잭션 안에서** 대량 데이터를 `generate_series` 로 적재하고 측정 후 `ROLLBACK` (개발 DB 는 건드리지 않음).
- 비슈퍼유저라 `session_replication_role` 사용 불가 → `ALTER TABLE production_result DISABLE TRIGGER USER` (트랜잭션 내, 롤백됨)로 적재 시 트리거 우회.
- 데이터: `production_result` 100,000 행(12 설비 x 90일 x 2교대에 분산, 일부 조합만 채워짐), `equipment_status_log` 4,320 행, 적재 후 `ANALYZE`.

## 결과 (`EXPLAIN (ANALYZE) SELECT * FROM <view>`)
| 뷰 | 결과 행수 | Execution Time |
|---|---|---|
| `v_oee_daily` | 1,260 | 약 505 ms (단순 `count(*)` 2회: 0.515 s / 0.497 s) |
| `v_defect_rate` | 6 | 약 45 ms |
| `v_wo_progress` | 2 | 약 24 ms |

## 결정
`v_oee_daily` 가 1초 목표 이내(약 0.5초)이므로 **머티리얼라이즈드 뷰로 전환하지 않고 일반 뷰 유지**. 데이터가 10배 이상 늘어 1초를 넘으면 `mv_oee_daily` + `REFRESH MATERIALIZED VIEW` 로 전환하고 `v_oee_daily` 는 그 위의 일반 뷰로 두면 소비자 변경이 없다.
한계: 측정은 단일 로컬 PostgreSQL 16 인스턴스, 캐시된 상태의 수치이며 실행 시간은 환경에 따라 달라진다.
