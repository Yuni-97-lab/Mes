-- 생산실적 트리거: 초과생산 방지(BEFORE), 재고 backflush·상태 전이(AFTER)

-- 품목 라우팅에서 해당 공정의 위치를 판정하는 보조 함수
-- 반환: 'FIRST' (첫 공정), 'LAST' (마지막 공정), 'BOTH' (단일 공정), 'MID' (중간), NULL (라우팅에 없음)
CREATE FUNCTION routing_position(p_item_id integer, p_process_id integer) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT CASE
        WHEN r.seq = mm.min_seq AND r.seq = mm.max_seq THEN 'BOTH'
        WHEN r.seq = mm.min_seq THEN 'FIRST'
        WHEN r.seq = mm.max_seq THEN 'LAST'
        ELSE 'MID'
    END
    FROM routing r
    JOIN (SELECT min(seq) AS min_seq, max(seq) AS max_seq FROM routing WHERE item_id = p_item_id) mm ON true
    WHERE r.item_id = p_item_id AND r.process_id = p_process_id
$$;

-- BEFORE INSERT: 마지막 공정의 누적 양품 + 신규 양품이 계획수량을 넘으면 거부
CREATE FUNCTION production_result_bi() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_item_id integer;
    v_planned numeric;
    v_pos     text;
    v_done    numeric;
BEGIN
    -- 같은 작업지시의 동시 입력을 직렬화하여 누적 검사의 경쟁 상태를 막는다
    SELECT item_id, planned_qty INTO v_item_id, v_planned
    FROM work_order WHERE wo_id = NEW.wo_id FOR UPDATE;

    v_pos := routing_position(v_item_id, NEW.process_id);
    IF v_pos IN ('LAST', 'BOTH') THEN
        SELECT COALESCE(sum(good_qty), 0) INTO v_done
        FROM production_result WHERE wo_id = NEW.wo_id AND process_id = NEW.process_id;
        IF v_done + NEW.good_qty > v_planned THEN
            RAISE EXCEPTION 'work order over-production'
                USING DETAIL = format('wo_id=%s planned=%s cumulative_good=%s new_good=%s',
                                      NEW.wo_id, v_planned, v_done, NEW.good_qty);
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_production_result_bi
BEFORE INSERT ON production_result
FOR EACH ROW EXECUTE FUNCTION production_result_bi();

-- AFTER INSERT: 재고 backflush 와 작업지시 상태 전이
-- 규칙(단순화): 소요 자재는 품목의 첫 공정(자재투입) 실적에서만 BOM 직계 자식 기준으로
-- qty_per × (양품+불량) 만큼 차감하고, 생산 결과물(양품)은 마지막 공정 실적에서만 가산한다.
-- 그 외 공정은 재고 이동 없이 실적만 기록한다. 재고 부족은 inventory 의 CHECK(qty >= 0)
-- 위반(CheckViolation)으로 드러나 INSERT 전체가 롤백된다.
CREATE FUNCTION production_result_ai() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_item_id integer;
    v_planned numeric;
    v_pos     text;
    v_done    numeric;
    c         record;
BEGIN
    SELECT item_id, planned_qty INTO v_item_id, v_planned
    FROM work_order WHERE wo_id = NEW.wo_id;

    v_pos := routing_position(v_item_id, NEW.process_id);

    -- 첫 공정: 자식 품목 차감 (delta 음수)
    IF v_pos IN ('FIRST', 'BOTH') THEN
        FOR c IN SELECT child_item_id, qty_per FROM bom WHERE parent_item_id = v_item_id LOOP
            UPDATE inventory
            SET qty = qty + (-c.qty_per * (NEW.good_qty + NEW.defect_qty))
            WHERE item_id = c.child_item_id;
            INSERT INTO inventory_txn (item_id, delta, ref_result_id)
            VALUES (c.child_item_id, -c.qty_per * (NEW.good_qty + NEW.defect_qty), NEW.result_id);
        END LOOP;
    END IF;

    -- 마지막 공정: 완제품/반제품 재고 증가 (delta 양수) 및 완료 판정
    IF v_pos IN ('LAST', 'BOTH') THEN
        IF NEW.good_qty > 0 THEN
            UPDATE inventory SET qty = qty + NEW.good_qty WHERE item_id = v_item_id;
            INSERT INTO inventory_txn (item_id, delta, ref_result_id)
            VALUES (v_item_id, NEW.good_qty, NEW.result_id);
        END IF;

        SELECT COALESCE(sum(good_qty), 0) INTO v_done
        FROM production_result WHERE wo_id = NEW.wo_id AND process_id = NEW.process_id;
        IF v_done >= v_planned THEN
            UPDATE work_order SET status = 'DONE' WHERE wo_id = NEW.wo_id;
        END IF;
    END IF;

    -- 첫 실적이면 RUNNING (이미 DONE 인 작업지시는 되돌리지 않음)
    UPDATE work_order SET status = 'RUNNING' WHERE wo_id = NEW.wo_id AND status = 'PLANNED';

    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_production_result_ai
AFTER INSERT ON production_result
FOR EACH ROW EXECUTE FUNCTION production_result_ai();
