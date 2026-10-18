# VM da agência na AWS — passo a passo (Terraform)

**Resultado:** uma EC2 `m6i.2xlarge` (8 vCPU / 32 GB) Ubuntu 24.04 em `eu-west-1`, IP fixo, disco gp3 300 GB criptografado, HTTPS aberto e SSH restrito, snapshots diários (14 dias), bucket S3 para dumps, alarmes de CPU/disco/status e orçamento mensal por e-mail — pronta para `make up` em ~5 minutos após o `apply`.

## 0. O que você precisa ter (eu não faço isso por você)
- Conta AWS com cartão e **MFA no root**; um usuário/role IAM com `AdministratorAccess` (ou, no mínimo, EC2, VPC, IAM, S3, Backup, CloudWatch, SNS, Budgets).
- `aws` CLI autenticado (`aws sts get-caller-identity` responde) e `terraform ≥ 1.6` instalados no seu Mac (`brew install awscli terraform`).
- Uma chave SSH (`ssh-keygen -t ed25519 -C edu@mac` se não tiver) e seu IP público (`curl -s ifconfig.me`).
- Acesso ao DNS de `highclass.you` para criar `brain.highclass.you`.
- Opcional, recomendado: conta Tailscale e uma auth key (fecha o SSH público).

## 1. Criar
```bash
cd dubai-ai-agency/deploy/aws
cp terraform.tfvars.example terraform.tfvars   # preencha ssh_public_key, admin_cidr, operator_email
terraform init
terraform plan                                  # revise: ~30 recursos, nada fora de eu-west-1
terraform apply                                 # digite yes; ~3 min
terraform output                                # IP fixo, comando ssh, próximos passos
```
Confirme a inscrição do SNS no e-mail que a AWS envia (senão os alarmes não chegam).

## 2. DNS
Crie o registro `A brain.highclass.you → <public_ip>` (TTL 300). `dig +short brain.highclass.you` tem que devolver o IP antes do `make up` — o Caddy só emite o certificado com o DNS resolvendo.

## 3. Código na máquina
Com `repo_url` no tfvars o cloud-init já clonou. Sem repositório:
```bash
scp dubai-ai-agency.zip ubuntu@<public_ip>:/opt/
ssh ubuntu@<public_ip> 'cd /opt && sudo unzip -o dubai-ai-agency.zip && sudo chown -R ubuntu:ubuntu dubai-ai-agency'
```
Confira o bootstrap: `ssh ubuntu@<public_ip> 'cloud-init status --wait; tail -5 /var/log/brain-bootstrap.log'`.

## 4. Segredos e subida
```bash
ssh ubuntu@<public_ip>
cd /opt/dubai-ai-agency && bash scripts/init_env.sh   # gera segredos; pergunta Anthropic, Jev, senha do dashboard, WhatsApp da CEO
#   DOMAIN=brain.highclass.you · ANTHROPIC_API_KEY · JEV_API_KEY (+JEV_MODEL pinado) · senhas longas (openssl rand -hex 32)
#   FIELD_ENCRYPTION_KEY (Fernet) · CEO_WHATSAPP · canais (WA/Meta/Telegram) quando tiver · DASHBOARD_PASSWORD
make up && make migrate && make check && make jev-smoke
make seed          # opcional: dados de demonstração para ver o dashboard vivo
```
Abra `https://brain.highclass.you/` (usuário `ceo`, senha do `.env`). Chatwoot em `/inbox`, Langfuse em `/langfuse` — siga o `docs/RUNBOOK.md` Dia 1–4.

## 5. Operação
- **Backups**: snapshot do disco todo dia 04:00 (Dubai) por 14 dias + `scripts/backup.sh` → `s3://<bucket>/dumps/` (90 dias). Restaurar: `aws backup start-restore-job` ou novo volume do snapshot.
- **Alarmes**: status check, CPU > 85%, disco > 85%, orçamento 80%/100% → seu e-mail. O SysOps interno cobre o resto (filas, webhooks, Jev, tokens).
- **Atualizar a máquina**: `git pull && make up` (ou novo zip) — os volumes Docker preservam dados. `make migrate` é idempotente.
- **Crescer**: mude `instance_type` no tfvars e `terraform apply` (reinicia a instância, ~2 min; o disco e o IP ficam). Para ir à UAE (`me-central-1`) depois, é um novo `apply` com `region` e restauração do dump — o `.env` e os volumes seguem com você.
- **Destruir**: `terraform destroy` NÃO apaga o disco raiz (`delete_on_termination=false`) nem o bucket (`force_destroy=false`) — de propósito.

## Custo (eu-west-1, estimativa out/2026)
| Item | USD/mês |
| --- | --- |
| m6i.2xlarge sob demanda (730 h × 0,384) | ~280 |
| gp3 300 GB + IOPS/throughput base | ~27 |
| IP fixo | ~3,6 |
| Snapshots (14 dias, ~150 GB úteis) | ~10–15 |
| S3 dumps + saída de dados | ~3–8 |
| **Total** | **~325–335** · com Savings Plan 1 ano: ~215 |

Shadow mode mais barato: `instance_type = "t3.xlarge"` (~USD 120 + disco) e sobe para m6i.2xlarge antes de novembro.

## Segurança já incluída
Disco criptografado · IMDSv2 obrigatório · SSH só do seu IP (ou só via Tailscale) · ufw + fail2ban · atualizações automáticas com reboot 04:30 · Caddy com HSTS · papel IAM mínimo (SSM, CloudWatch, bucket de backups) · bucket privado, versionado e criptografado · `terraform.tfvars` e estado fora do git.
