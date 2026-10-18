#!/usr/bin/env bash
# O serviço "minio" (armazenamento S3 para PDFs e eventos do Langfuse) precisa de uma imagem pública.
# A MinIO fechou suas imagens em 2025/26, então testamos alternativas compatíveis com S3 e gravamos
# docker-compose.override.yml com a que funcionar. Uso: bash scripts/pick_object_store.sh
set -uo pipefail
cd "$(dirname "$0")/.."

try() { echo "→ testando $1"; docker pull "$1" >/dev/null 2>&1; }

write_override() { # $1 = image, $2 = kind (rustfs|bitnami|minio|garage)
  local img="$1" kind="$2"
  case "$kind" in
    rustfs)
      cat > docker-compose.override.yml <<EOF
services:
  minio:
    image: ${img}
    environment:
      RUSTFS_ACCESS_KEY: \${MINIO_ROOT_USER:-brain}
      RUSTFS_SECRET_KEY: \${MINIO_ROOT_PASSWORD}
      RUSTFS_ADDRESS: ":9000"
      RUSTFS_VOLUMES: /data
      MINIO_ROOT_USER: \${MINIO_ROOT_USER:-brain}
      MINIO_ROOT_PASSWORD: \${MINIO_ROOT_PASSWORD}
    volumes:
      - miniodata:/data
EOF
      ;;
    bitnami)
      cat > docker-compose.override.yml <<EOF
services:
  minio:
    image: ${img}
    environment:
      MINIO_ROOT_USER: \${MINIO_ROOT_USER:-brain}
      MINIO_ROOT_PASSWORD: \${MINIO_ROOT_PASSWORD}
      MINIO_DEFAULT_BUCKETS: docs,media,langfuse
    volumes:
      - miniodata:/bitnami/minio/data
EOF
      ;;
    minio)
      cat > docker-compose.override.yml <<EOF
services:
  minio:
    image: ${img}
    command: server /data --console-address ":9001"
EOF
      ;;
  esac
  echo "docker-compose.override.yml escrito com ${img} (${kind})"
}

# ordem: imagens oficiais da MinIO ainda públicas (tags antigas) → RustFS (drop-in) → Bitnami
for img in \
  "minio/minio:RELEASE.2025-04-22T22-12-26Z" \
  "minio/minio:RELEASE.2024-12-18T13-15-44Z" \
  "quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z"; do
  if try "$img"; then write_override "$img" minio; exit 0; fi
done
for img in "rustfs/rustfs:latest" "rustfs/rustfs:1.0.0-alpha.78"; do
  if try "$img"; then write_override "$img" rustfs; exit 0; fi
done
for img in "bitnami/minio:latest" "bitnamilegacy/minio:latest"; do
  if try "$img"; then write_override "$img" bitnami; exit 0; fi
done

echo "Nenhuma imagem S3 pública disponível. Plano B: subir sem o serviço minio (PDFs ficam em disco local)."
cat > docker-compose.override.yml <<'EOF'
services:
  minio:
    image: busybox:latest
    command: ["sh", "-c", "echo 'object store desativado; usando disco local'; sleep infinity"]
  brain:
    environment:
      S3_ENDPOINT: ""
  langfuse-web:
    environment:
      LANGFUSE_S3_EVENT_UPLOAD_ENABLED: "false"
  langfuse-worker:
    environment:
      LANGFUSE_S3_EVENT_UPLOAD_ENABLED: "false"
EOF
exit 2
