# MES 포트폴리오

PostgreSQL 16 기반 MES(제조실행시스템) 포트폴리오 프로젝트.

## 환경 준비

### 방법 A: Docker
```bash
docker compose up -d
```
`docker-compose.yml` 이 사용자/DB `mes`(비밀번호 `mes`)를 만든다. 테스트 DB는 한 번 생성한다.
```bash
docker compose exec db psql -U mes -d mes -c "CREATE DATABASE mes_test"
```

### 방법 B: 네이티브 설치 (Windows)
```powershell
winget install PostgreSQL.PostgreSQL.16
psql -U postgres -f scripts/create_dbs.sql   # mes 롤, mes / mes_test DB 생성
```

### 공통
```bash
pip install -r requirements.txt
cp .env.example .env        # 필요 시 DATABASE_URL 수정
python scripts/init_db.py --reset
pytest -v
```
