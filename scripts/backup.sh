#!/usr/bin/env bash
# Dump criptografado do banco (brain + chatwoot) para ./backups e, se configurado, para o MinIO/S3.
set -euo pipefail
cd "$(dirname "$0")/.."
source .env
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M)
for DB in "$POSTGRES_DB" chatwoot; do
  docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$DB" --no-owner | gzip > "backups/$DB-$STAMP.sql.gz"
  openssl enc -aes-256-cbc -pbkdf2 -salt -in "backups/$DB-$STAMP.sql.gz" -out "backups/$DB-$STAMP.sql.gz.enc" -pass pass:"$FIELD_ENCRYPTION_KEY"
  rm "backups/$DB-$STAMP.sql.gz"
done
find backups -name '*.enc' -mtime +14 -delete
echo "backup ok: backups/*-$STAMP.sql.gz.enc"
