variable "region" {
  description = "Região AWS"
  type        = string
  default     = "eu-west-1"
}

variable "name" {
  description = "Prefixo dos recursos"
  type        = string
  default     = "hcte-brain"
}

variable "environment" {
  type    = string
  default = "production"
}

variable "instance_type" {
  description = "m6i.2xlarge = 8 vCPU / 32 GB (alta temporada). t3.xlarge para shadow mode barato."
  type        = string
  default     = "m6i.2xlarge"
}

variable "disk_gb" {
  description = "Disco raiz gp3 criptografado (Postgres, ClickHouse, MinIO, backups locais)"
  type        = number
  default     = 300
}

variable "domain" {
  description = "Domínio público da máquina (Caddy emite TLS). Crie o registro A → IP fixo após o apply."
  type        = string
  default     = "brain.highclass.you"
}

variable "ssh_public_key" {
  description = "Conteúdo da sua chave pública SSH (ex.: cat ~/.ssh/id_ed25519.pub)"
  type        = string
}

variable "admin_cidr" {
  description = "Seu IP público em CIDR para SSH (ex.: 203.0.113.10/32). Ignorado quando tailscale_auth_key está definido."
  type        = string
  default     = "127.0.0.1/32"
}

variable "tailscale_auth_key" {
  description = "Opcional: auth key do Tailscale (tskey-auth-...). Com ela, SSH fica fechado ao público e você entra pela rede privada."
  type        = string
  default     = ""
  sensitive   = true
}

variable "repo_url" {
  description = "Git do repositório da máquina (privado: use deploy key/HTTPS token) ou vazio para enviar o zip por scp."
  type        = string
  default     = ""
}

variable "repo_ref" {
  type    = string
  default = "main"
}

variable "operator_email" {
  description = "E-mail que recebe os alarmes do CloudWatch (confirme a inscrição no e-mail da AWS)."
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = "Teto mensal esperado da conta AWS para alerta (VM + disco + IP + backups + S3)"
  type        = number
  default     = 450
}

variable "admin_cidr_v6" {
  description = "Opcional: seu IPv6 público em CIDR (ex.: 2001:db8::1/128) para SSH quando a operadora só dá IPv6."
  type        = string
  default     = ""
}
