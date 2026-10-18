#!/usr/bin/env bash
# Cria a VM da agência na AWS a partir do seu Mac, do zero até o IP fixo.
# Uso:  cd dubai-ai-agency/deploy/aws && bash bootstrap_mac.sh
# Não grava segredos em lugar nenhum além do padrão da AWS (~/.aws/credentials) e do terraform.tfvars (que está no .gitignore).
set -euo pipefail
cd "$(dirname "$0")"

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  PREENCHA AQUI (ou deixe como está e o script pergunta no terminal)           ║
# ║  Depois de rodar, APAGUE os valores deste bloco — este arquivo vai para o zip ║
# ║  e para o git; chave aqui dentro é vazamento.                                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
AWS_ACCESS_KEY_ID_REAL="COLE_AQUI_SUA_ACCESS_KEY_ID"          # IAM → usuário edu → Security credentials → Access keys
AWS_SECRET_ACCESS_KEY_REAL="COLE_AQUI_SUA_SECRET_ACCESS_KEY"  # só aparece na criação da chave
OPERATOR_EMAIL="edu@zeroum.bet"                                # alarmes e orçamento
INSTANCE_TYPE="m6i.2xlarge"                                    # ou t3.xlarge (~USD 150/mês) para o shadow mode
DOMAIN="brain.highclass.you"
TAILSCALE_AUTH_KEY=""                                          # tskey-auth-... (opcional; fecha o SSH público)

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ask()  { local v; read -r -p "$1 " v; echo "$v"; }

bold "1/6  Ferramentas (Homebrew, AWS CLI, Terraform)"
command -v brew >/dev/null || { echo "Instale o Homebrew primeiro: https://brew.sh"; exit 1; }
command -v aws >/dev/null || brew install awscli
if ! command -v terraform >/dev/null; then
  # a fórmula "terraform" do Homebrew foi desativada; o tap oficial da HashiCorp continua funcionando
  brew tap hashicorp/tap
  brew install hashicorp/tap/terraform
fi
aws --version && terraform version | head -1

bold "2/6  Credenciais da AWS (digite aqui; nada é enviado a terceiros)"
aws configure set region eu-west-1
aws configure set output json
if [[ "$AWS_ACCESS_KEY_ID_REAL" != COLE_AQUI* && "$AWS_SECRET_ACCESS_KEY_REAL" != COLE_AQUI* ]]; then
  aws configure set aws_access_key_id "$AWS_ACCESS_KEY_ID_REAL"
  aws configure set aws_secret_access_key "$AWS_SECRET_ACCESS_KEY_REAL"
  echo "credenciais do bloco PREENCHA AQUI gravadas em ~/.aws/credentials (perfil default)."
  echo "LEMBRETE: apague os valores do bloco no topo deste arquivo depois."
elif ! aws sts get-caller-identity >/dev/null 2>&1; then
  read -r -p "AWS Access Key ID: " AKID
  read -r -s -p "AWS Secret Access Key: " SAK; echo
  aws configure set aws_access_key_id "$AKID"
  aws configure set aws_secret_access_key "$SAK"
  unset AKID SAK
fi
aws sts get-caller-identity --output table

bold "3/6  Chave SSH e seu IP"
[ -f ~/.ssh/id_ed25519.pub ] || ssh-keygen -t ed25519 -C "edu@mac" -f ~/.ssh/id_ed25519 -N ""
PUBKEY=$(cat ~/.ssh/id_ed25519.pub)
MYIP=$(curl -4 -s ifconfig.me || curl -4 -s api.ipify.org || true)     # IPv4 obrigatório no security group
MYIP6=$(curl -6 -s ifconfig.me 2>/dev/null || true)
echo "chave: ${PUBKEY:0:40}...   IPv4: ${MYIP:-nenhum}   IPv6: ${MYIP6:-nenhum}"
[ -n "$MYIP" ] || { echo "Sem IPv4 público detectado; SSH será liberado só pelo IPv6 (ou use Tailscale)."; }

bold "4/6  Parâmetros da máquina"
EMAIL="$OPERATOR_EMAIL"; ITYPE="$INSTANCE_TYPE"; TSKEY="$TAILSCALE_AUTH_KEY"
echo "instância: $ITYPE · domínio: $DOMAIN · e-mail: $EMAIL · tailscale: ${TSKEY:+sim}${TSKEY:-não}"

cat > terraform.tfvars <<EOF
region         = "eu-west-1"
instance_type  = "${ITYPE}"
disk_gb        = 300
domain         = "${DOMAIN}"
ssh_public_key = "${PUBKEY}"
admin_cidr     = "${MYIP:-127.0.0.1}/32"
admin_cidr_v6  = "${MYIP6:+${MYIP6}/128}"
operator_email = "${EMAIL}"
tailscale_auth_key = "${TSKEY}"
EOF
echo "terraform.tfvars escrito (não comite este arquivo)."

bold "5/6  terraform init + plan"
terraform init -upgrade
terraform plan -out=plan.tfplan
echo
read -r -p "Revise acima (~30 recursos, tudo em eu-west-1). Aplicar? [yes/N] " GO; GO=$(echo "$GO" | tr "[:upper:]" "[:lower:]")
[[ "$GO" == "yes" || "$GO" == "y" || "$GO" == "sim" || "$GO" == "s" ]] || { echo "Nada criado. Rode de novo quando quiser."; exit 0; }

bold "6/6  terraform apply"
terraform apply plan.tfplan
rm -f plan.tfplan
echo
terraform output
echo
bold "Pronto. Próximo passo: crie o registro DNS  ${DOMAIN}  A  $(terraform output -raw public_ip)  e me avise."
echo "Confirme também a inscrição do SNS no e-mail ${EMAIL} (mensagem 'AWS Notification - Subscription Confirmation')."
