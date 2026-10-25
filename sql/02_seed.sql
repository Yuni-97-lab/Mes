-- 마스터 시드 (모두 가상 데이터)

INSERT INTO item (item_code, name, item_type, unit) VALUES
    ('FG-A100',  '센서 모듈 A100',   'FG',  'EA'),
    ('FG-B200',  '전원 모듈 B200',   'FG',  'EA'),
    ('FG-C300',  '제어 보드 C300',   'FG',  'EA'),
    ('SFG-P01',  'SMT 실장 PCB-01',  'SFG', 'EA'),
    ('SFG-P02',  'SMT 실장 PCB-02',  'SFG', 'EA'),
    ('RM-PCB',   '베어 PCB 기판',    'RM',  'EA'),
    ('RM-IC',    '집적회로(IC)',     'RM',  'EA'),
    ('RM-CAP',   '칩 커패시터',      'RM',  'EA'),
    ('RM-RES',   '칩 저항',          'RM',  'EA'),
    ('RM-CASE',  '외장 케이스',      'RM',  'EA');

-- BOM: FG -> SFG -> RM 2단계 (FG 는 케이스 RM 도 직접 사용)
INSERT INTO bom (parent_item_id, child_item_id, qty_per)
SELECT p.item_id, c.item_id, v.qty
FROM (VALUES
    ('FG-A100', 'SFG-P01', 1), ('FG-A100', 'RM-CASE', 1),
    ('FG-B200', 'SFG-P02', 1), ('FG-B200', 'RM-CASE', 1),
    ('FG-C300', 'SFG-P01', 1), ('FG-C300', 'SFG-P02', 1), ('FG-C300', 'RM-CASE', 1),
    ('SFG-P01', 'RM-PCB', 1), ('SFG-P01', 'RM-IC', 2), ('SFG-P01', 'RM-CAP', 10), ('SFG-P01', 'RM-RES', 8),
    ('SFG-P02', 'RM-PCB', 1), ('SFG-P02', 'RM-IC', 1), ('SFG-P02', 'RM-CAP', 6),  ('SFG-P02', 'RM-RES', 4)
) AS v(parent_code, child_code, qty)
JOIN item p ON p.item_code = v.parent_code
JOIN item c ON c.item_code = v.child_code;

INSERT INTO process (code, name, seq) VALUES
    ('MATIN', '자재투입', 1),
    ('SMT',   'SMT',      2),
    ('AOI',   'AOI검사',  3),
    ('ASM',   '조립',     4),
    ('FCT',   '기능검사', 5),
    ('PACK',  '포장',     6);

-- 라우팅: SFG 는 자재투입→SMT→AOI, FG 는 조립→기능검사→포장 (ideal_cycle_sec 은 개당 초)
INSERT INTO routing (item_id, process_id, seq, ideal_cycle_sec)
SELECT i.item_id, p.process_id, v.seq, v.cycle
FROM (VALUES
    ('SFG-P01', 'MATIN', 1,  4.0), ('SFG-P01', 'SMT', 2, 18.0), ('SFG-P01', 'AOI', 3,  6.0),
    ('SFG-P02', 'MATIN', 1,  3.0), ('SFG-P02', 'SMT', 2, 12.0), ('SFG-P02', 'AOI', 3,  5.0),
    ('FG-A100', 'ASM',   1, 25.0), ('FG-A100', 'FCT', 2, 15.0), ('FG-A100', 'PACK', 3,  8.0),
    ('FG-B200', 'ASM',   1, 30.0), ('FG-B200', 'FCT', 2, 20.0), ('FG-B200', 'PACK', 3,  8.0),
    ('FG-C300', 'ASM',   1, 40.0), ('FG-C300', 'FCT', 2, 28.0), ('FG-C300', 'PACK', 3, 10.0)
) AS v(item_code, process_code, seq, cycle)
JOIN item i ON i.item_code = v.item_code
JOIN process p ON p.code = v.process_code;

INSERT INTO line (name) VALUES ('라인1'), ('라인2');

INSERT INTO equipment (line_id, process_id, name)
SELECT l.line_id, p.process_id, v.name
FROM (VALUES
    ('라인1', 'MATIN', 'L1-자재투입기'),
    ('라인1', 'SMT',   'L1-SMT-01'),
    ('라인1', 'AOI',   'L1-AOI-01'),
    ('라인1', 'ASM',   'L1-조립기-01'),
    ('라인1', 'FCT',   'L1-FCT-01'),
    ('라인1', 'PACK',  'L1-포장기-01'),
    ('라인2', 'MATIN', 'L2-자재투입기'),
    ('라인2', 'SMT',   'L2-SMT-01'),
    ('라인2', 'AOI',   'L2-AOI-01'),
    ('라인2', 'ASM',   'L2-조립기-01'),
    ('라인2', 'FCT',   'L2-FCT-01'),
    ('라인2', 'PACK',  'L2-포장기-01')
) AS v(line_name, process_code, name)
JOIN line l ON l.name = v.line_name
JOIN process p ON p.code = v.process_code;

INSERT INTO shift (name, start_time, end_time) VALUES
    ('주간', '08:00', '20:00'),
    ('야간', '20:00', '08:00');

INSERT INTO downtime_reason (name, is_planned) VALUES
    ('점심',     true),
    ('정기점검', true),
    ('설비고장', false),
    ('자재대기', false);

INSERT INTO defect_code (name) VALUES
    ('납땜불량'), ('부품누락'), ('오삽'), ('기능불량'), ('외관불량');

-- FG/SFG 재고 행은 0 으로 미리 생성 (이후 트리거가 UPSERT 없이 UPDATE 가능)
INSERT INTO inventory (item_id, qty)
SELECT item_id, 0 FROM item WHERE item_type IN ('FG', 'SFG');

-- 원자재 초기 재고 (충분히 큼), 수불 원장에도 기초 입고로 기록
INSERT INTO inventory (item_id, qty)
SELECT item_id, 1000000 FROM item WHERE item_type = 'RM';

INSERT INTO inventory_txn (item_id, delta)
SELECT item_id, 1000000 FROM item WHERE item_type = 'RM';
