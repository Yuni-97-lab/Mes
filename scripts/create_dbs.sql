-- 네이티브 설치 시 superuser(postgres)로 한 번 실행: psql -U postgres -f scripts/create_dbs.sql
CREATE ROLE mes LOGIN PASSWORD 'mes';
CREATE DATABASE mes OWNER mes;
CREATE DATABASE mes_test OWNER mes;
-- 교대 창 계산은 세션 시간대 기준이므로 DB 기본 시간대를 KST 로 고정 (connect() 도 같은 값을 지정)
ALTER DATABASE mes SET timezone TO 'Asia/Seoul';
ALTER DATABASE mes_test SET timezone TO 'Asia/Seoul';
