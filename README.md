# MES 포트폴리오

PostgreSQL 16 기반 MES(제조실행시스템) 포트폴리오 프로젝트.

## 환경 준비

### 방법 A: Docker
```bash
docker compose up -d
```
`docker-compose.yml` 이 사용자/DB `mes`(비밀번호 `mes`)와 `mes_test` DB를 최초 기동 시 만든다
(`scripts/docker_init_test_db.sh`).

### 방법 B: 네이티브 설치 (Windows)
```powershell
winget install PostgreSQL.PostgreSQL.16
psql -U postgres -f scripts/create_dbs.sql   # mes 롤, mes / mes_test DB 생성
```

### 공통
```bash
pip install -r requirements.txt
# 기본값과 다르면 셸에서 DATABASE_URL 을 설정 (.env.example 참고, .env 는 자동 로드되지 않음)
# 예: export DATABASE_URL=postgresql://mes:mes@localhost:5432/mes
python scripts/init_db.py --reset
pytest -v
```
