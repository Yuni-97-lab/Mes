-- KPI 뷰: OEE·불량률·작업지시 진행률·설비 현재상태. 모든 지표는 SQL 뷰에서 계산한다.

-- ============================================================
-- v_oee_daily : 설비 x 교대 x 작업일 OEE
-- 행 단위: 생산실적 또는 설비 상태 로그 활동이 있는 (설비, 교대, work_date) 조합만 나온다.
-- work_date: 교대가 "시작된" 달력 날짜 (야간조의 자정 이후 구간은 전날 work_date 에 속함).
-- 교대 창: work_date + start_time ~ +교대길이(end_time <= start_time 이면 익일로 넘김, 12h).
-- 유효 창 = [교대 시작, LEAST(교대 끝, now())]  -- 진행 중인 교대는 지금까지만 계획시간으로 본다
-- 계획시간 = 유효 창 길이 - 계획 비가동(is_planned 사유가 붙은 비-RUN 로그의 유효 창 내 겹침 시간)
-- 가동시간 = RUN 로그의 유효 창 내 겹침 시간 (ended_at NULL 은 now() 까지)
-- 가동률 availability = 가동시간 / 계획시간  (비계획 DOWN·IDLE 은 가동률을 낮춤)
-- 성능률 performance  = Σ(ideal_cycle_sec x (양품+불량)) / 가동시간(초)
--       ideal_cycle_sec 은 (작업지시 품목, 설비 공정) 라우팅 기준, 라우팅 없으면 기여 0. 상한 캡 없음.
-- 품질률 quality      = 양품 / (양품+불량). 생산수량 0 이면 정의되지 않으므로 NULL.
-- oee = availability x performance x COALESCE(quality, 0). 그 외 분모 0 이면 해당 비율은 0 (NULLIF/COALESCE).
-- shift_start / shift_end: 교대 창(캡 적용 전). 대시보드가 "최근 교대" 범위를 고르는 데 쓴다.
-- 시간대: timestamptz -> 날짜/시각 변환은 세션 TimeZone 기준 (mes.db.connect() 가 Asia/Seoul 로 고정).
-- ============================================================
CREATE VIEW v_oee_daily AS
WITH res AS (   -- 실적을 (설비, 교대, work_date) 로 집계
    SELECT pr.equipment_id, pr.shift_id,
           (pr.started_at::date
              - CASE WHEN s.end_time <= s.start_time AND pr.started_at::time < s.end_time
                     THEN 1 ELSE 0 END) AS work_date,
           sum(pr.good_qty)   AS good_qty,
           sum(pr.defect_qty) AS defect_qty,
           sum((pr.good_qty + pr.defect_qty) * COALESCE(rt.ideal_cycle_sec, 0)) AS ideal_sec
    FROM production_result pr
    JOIN shift s ON s.shift_id = pr.shift_id
    JOIN equipment e ON e.equipment_id = pr.equipment_id
    JOIN work_order wo ON wo.wo_id = pr.wo_id
    LEFT JOIN routing rt ON rt.item_id = wo.item_id AND rt.process_id = e.process_id
    GROUP BY 1, 2, 3
),
log_keys AS (   -- 상태 로그가 걸치는 (설비, 교대, work_date)
    SELECT DISTINCT sl.equipment_id, s.shift_id, d::date AS work_date
    FROM equipment_status_log sl
    CROSS JOIN shift s
    CROSS JOIN LATERAL generate_series(sl.started_at::date - 1,
                                       COALESCE(sl.ended_at, now())::date,
                                       interval '1 day') d
    WHERE sl.started_at < (d::date + s.start_time)::timestamptz
                          + CASE WHEN s.end_time <= s.start_time
                                 THEN s.end_time - s.start_time + interval '24 hours'
                                 ELSE s.end_time - s.start_time END
      AND COALESCE(sl.ended_at, now()) > (d::date + s.start_time)::timestamptz
),
cand AS (
    SELECT equipment_id, shift_id, work_date FROM res
    UNION
    SELECT equipment_id, shift_id, work_date FROM log_keys
),
win AS (        -- 교대 창
    SELECT c.equipment_id, c.shift_id, c.work_date, s.name AS shift_name,
           (c.work_date + s.start_time)::timestamptz AS wstart,
           (c.work_date + s.start_time)::timestamptz
             + CASE WHEN s.end_time <= s.start_time
                    THEN s.end_time - s.start_time + interval '24 hours'
                    ELSE s.end_time - s.start_time END AS wend
    FROM cand c JOIN shift s ON s.shift_id = c.shift_id
),
eff AS (        -- 유효 창: 진행 중인 교대는 now() 에서 자른다 (창 시작 이전으로는 가지 않음)
    SELECT w.*, GREATEST(w.wstart, LEAST(w.wend, now())) AS wend_eff FROM win w
),
agg AS (
    SELECT w.equipment_id, w.shift_id, w.work_date, w.shift_name, w.wstart, w.wend,
           extract(epoch FROM w.wend_eff - w.wstart) AS shift_sec,
           COALESCE(sum(extract(epoch FROM
               GREATEST(interval '0', LEAST(COALESCE(sl.ended_at, now()), w.wend_eff)
                                       - GREATEST(sl.started_at, w.wstart))))
               FILTER (WHERE sl.status = 'RUN'), 0) AS run_sec,
           COALESCE(sum(extract(epoch FROM
               GREATEST(interval '0', LEAST(COALESCE(sl.ended_at, now()), w.wend_eff)
                                       - GREATEST(sl.started_at, w.wstart))))
               FILTER (WHERE sl.status <> 'RUN' AND dr.is_planned), 0) AS planned_down_sec
    FROM eff w
    LEFT JOIN equipment_status_log sl
           ON sl.equipment_id = w.equipment_id
          AND sl.started_at < w.wend_eff
          AND COALESCE(sl.ended_at, now()) > w.wstart
    LEFT JOIN downtime_reason dr ON dr.reason_id = sl.reason_id
    GROUP BY w.equipment_id, w.shift_id, w.work_date, w.shift_name, w.wstart, w.wend, w.wend_eff
),
ratios AS (
    SELECT e.equipment_id, e.name AS equipment_name, a.shift_name, a.work_date, a.wstart, a.wend,
           LEAST(1, COALESCE(a.run_sec / NULLIF(a.shift_sec - a.planned_down_sec, 0), 0)) AS availability,
           COALESCE(r.ideal_sec / NULLIF(a.run_sec, 0), 0)                      AS performance,
           r.good_qty / NULLIF(r.good_qty + r.defect_qty, 0)                    AS quality
    FROM agg a
    JOIN equipment e ON e.equipment_id = a.equipment_id
    LEFT JOIN res r ON r.equipment_id = a.equipment_id AND r.shift_id = a.shift_id
                   AND r.work_date = a.work_date
)
SELECT equipment_id, equipment_name, shift_name, work_date,
       availability::numeric, performance::numeric, quality::numeric,
       (availability * performance * COALESCE(quality, 0))::numeric AS oee,
       wstart AS shift_start, wend AS shift_end
FROM ratios;

-- ============================================================
-- v_defect_rate : 공정별 불량률
-- input_qty = 양품+불량, defect_rate = 불량/투입 (투입 0 이면 0)
-- scrap_qty/rework_qty 는 defect_record.kind 별 합계.
-- fty(First Time Yield) = 투입이 있는 모든 공정의 (양품/(양품+불량)) 곱.
--   전체 공정 단일 값이 각 행에 반복된다. 투입 없는 공정은 곱에서 제외(=1), 어떤 공정이든 양품 0 이면 0.
-- ============================================================
CREATE VIEW v_defect_rate AS
WITH res AS (
    SELECT process_id,
           sum(good_qty) AS good_qty, sum(defect_qty) AS defect_qty
    FROM production_result GROUP BY process_id
),
dr AS (
    SELECT pr.process_id,
           COALESCE(sum(d.qty) FILTER (WHERE d.kind = 'scrap'), 0)  AS scrap_qty,
           COALESCE(sum(d.qty) FILTER (WHERE d.kind = 'rework'), 0) AS rework_qty
    FROM defect_record d JOIN production_result pr ON pr.result_id = d.result_id
    GROUP BY pr.process_id
),
per AS (
    SELECT p.code AS process_code, p.seq,
           COALESCE(r.good_qty, 0) + COALESCE(r.defect_qty, 0) AS input_qty,
           COALESCE(r.good_qty, 0)   AS good_qty,
           COALESCE(r.defect_qty, 0) AS defect_qty,
           COALESCE(dr.scrap_qty, 0)  AS scrap_qty,
           COALESCE(dr.rework_qty, 0) AS rework_qty
    FROM process p
    LEFT JOIN res r ON r.process_id = p.process_id
    LEFT JOIN dr ON dr.process_id = p.process_id
),
fty AS (
    SELECT CASE WHEN bool_or(good_qty = 0) THEN 0
                ELSE COALESCE(exp(sum(ln(NULLIF(good_qty, 0) / input_qty))), 1) END AS fty
    FROM per WHERE input_qty > 0
)
SELECT per.process_code, per.input_qty, per.defect_qty, per.scrap_qty, per.rework_qty,
       COALESCE(per.defect_qty / NULLIF(per.input_qty, 0), 0)::numeric AS defect_rate,
       COALESCE((SELECT fty FROM fty), 1)::numeric AS fty
FROM per
ORDER BY per.seq;

-- ============================================================
-- v_wo_progress : 작업지시 진행률
-- good_qty = 해당 품목 라우팅의 "마지막 공정"에서의 누적 양품, progress_pct = 100 x good / planned (소수 1자리)
-- ============================================================
CREATE VIEW v_wo_progress AS
SELECT wo.wo_id, i.item_code, wo.planned_qty,
       COALESCE(g.good_qty, 0) AS good_qty,
       round(100 * COALESCE(g.good_qty, 0) / NULLIF(wo.planned_qty, 0), 1) AS progress_pct,
       wo.status, wo.due_date
FROM work_order wo
JOIN item i ON i.item_id = wo.item_id
LEFT JOIN LATERAL (
    SELECT sum(pr.good_qty) AS good_qty
    FROM production_result pr
    WHERE pr.wo_id = wo.wo_id
      AND pr.process_id = (SELECT rt.process_id FROM routing rt
                           WHERE rt.item_id = wo.item_id ORDER BY rt.seq DESC LIMIT 1)
) g ON true;

-- ============================================================
-- v_equipment_current : 설비별 최신 상태 (started_at 최신 로그). 로그 없으면 IDLE / since NULL
-- ============================================================
CREATE VIEW v_equipment_current AS
SELECT e.equipment_id, e.name,
       COALESCE(l.status, 'IDLE') AS status,
       l.started_at AS since
FROM equipment e
LEFT JOIN LATERAL (
    SELECT status, started_at FROM equipment_status_log sl
    WHERE sl.equipment_id = e.equipment_id
    ORDER BY sl.started_at DESC, sl.log_id DESC LIMIT 1
) l ON true;
