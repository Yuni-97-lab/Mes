#!/bin/sh
# 최초 기동 시 테스트 DB 생성
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE mes_test OWNER $POSTGRES_USER"
