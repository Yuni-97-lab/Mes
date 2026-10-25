#!/bin/sh
# 최초 기동 시 테스트 DB 생성, 두 DB 의 기본 시간대를 Asia/Seoul 로 고정
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE mes_test OWNER $POSTGRES_USER"
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ALTER DATABASE $POSTGRES_DB SET timezone TO 'Asia/Seoul'"
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ALTER DATABASE mes_test SET timezone TO 'Asia/Seoul'"
