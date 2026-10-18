#!/usr/bin/env bash
# Cria o .env a partir do .env.example gerando todos os segredos aleatórios e perguntando só o que é seu.
# Uso (na VM): cd /opt/dubai-ai-agency && bash scripts/init_env.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { cp .env ".env.bak.$(date +%s)"; echo "(.env existente salvo como backup)"; }
cp .env.example .env

setv() { # setv CHAVE VALOR — substitui a linha CHAVE=... preservando o comentário ao lado
  local k="$1" v="$2"
  python3 - "$k" "$v" <<'PY'
import re, sys
k, v = sys.argv[1], sys.argv[2]
p = ".env"; s = open(p, encoding="utf-8").read()
pat = re.compile(rf"^{re.escape(k)}=([^#\n]*)(\s*#.*)?$", re.M)
if pat.search(s):
    s = pat.sub(lambda m: f"{k}={v}", s, count=1)
else:
    s += f"\n{k}={v}\n"
open(p, "w", encoding="utf-8").write(s)
PY
}
rnd() { openssl rand -hex "$1"; }

echo "== segredos aleatórios"
setv DOMAIN "${DOMAIN:-brain.highclass.you}"
setv POSTGRES_PASSWORD "$(rnd 24)"
setv MINIO_ROOT_PASSWORD "$(rnd 24)"
setv CLICKHOUSE_PASSWORD "$(rnd 24)"
setv CHATWOOT_SECRET_KEY_BASE "$(rnd 64)"
setv LANGFUSE_NEXTAUTH_SECRET "$(rnd 32)"
setv LANGFUSE_SALT "$(rnd 32)"
setv LANGFUSE_ENCRYPTION_KEY "$(rnd 32)"
setv TELEGRAM_WEBHOOK_SECRET "$(rnd 16)"
setv WEBCHAT_SIGNING_SECRET "$(rnd 32)"
setv WA_VERIFY_TOKEN "$(rnd 16)"
setv META_VERIFY_TOKEN "$(rnd 16)"
if python3 -c "import cryptography" 2>/dev/null; then
  setv FIELD_ENCRYPTION_KEY "$(python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
else
  setv FIELD_ENCRYPTION_KEY "$(openssl rand -base64 32 | tr '+/' '-_')"   # Fernet: 32 bytes em base64 url-safe
fi
setv SECRETS_ROTATED_AT "{\"ANTHROPIC_API_KEY\":\"$(date +%F)\",\"JEV_API_KEY\":\"$(date +%F)\",\"DASHBOARD_PASSWORD\":\"$(date +%F)\"}"

echo "== o que é seu (Enter para deixar em branco e preencher depois com: nano .env)"
read -r -p "ANTHROPIC_API_KEY (sk-ant-...): " V; [ -n "$V" ] && setv ANTHROPIC_API_KEY "$V"
read -r -p "JEV_API_KEY (jv_live_... ou vazio = modo degradado): " V; [ -n "$V" ] && setv JEV_API_KEY "$V"
read -r -s -p "DASHBOARD_PASSWORD (login 'ceo' no dashboard; Enter = gerar uma): " V; echo
if [ -z "$V" ]; then V="$(rnd 12)"; echo "   senha gerada: $V   ← guarde no gerenciador de senhas"; fi
setv DASHBOARD_PASSWORD "$V"
read -r -p "CEO_WHATSAPP (+9715XXXXXXXX, Enter para depois): " V; [ -n "$V" ] && setv CEO_WHATSAPP "$V"
read -r -p "CEO_EMAIL (Enter para edu@zeroum.bet): " V; setv CEO_EMAIL "${V:-edu@zeroum.bet}"

chmod 600 .env
echo
echo "== .env pronto (permissão 600). Variáveis ainda vazias (canais, pagamentos, fornecedores) entram depois com: nano .env"
grep -E "^(DOMAIN|ANTHROPIC_API_KEY|JEV_API_KEY|CEO_WHATSAPP|CEO_EMAIL)=" .env | sed -E 's/#.*//; s/(KEY=)([^ ]{4})[^ ]+/\1\2******/'
echo "Próximo: make up && make migrate && make check"
