-- 네이티브 설치 시 superuser(postgres)로 한 번 실행: psql -U postgres -f scripts/create_dbs.sql
CREATE ROLE mes LOGIN PASSWORD 'mes';
CREATE DATABASE mes OWNER mes;
CREATE DATABASE mes_test OWNER mes;
