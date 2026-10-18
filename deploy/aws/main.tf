# A VM da agência 100% IA na AWS — uma instância EC2 (Ubuntu 24.04), IP fixo, disco criptografado,
# security group fechado (80/443 públicos; SSH só do seu IP), backups diários do disco (AWS Backup) e
# cloud-init que instala Docker e deixa a máquina pronta para `make up`.
#
# Uso (no seu terminal, com AWS CLI já autenticado):
#   cd deploy/aws
#   cp terraform.tfvars.example terraform.tfvars   # edite: ssh_public_key, admin_cidr, (opcional) tailscale_auth_key
#   terraform init && terraform plan && terraform apply
#   terraform output                                 # IP fixo → crie o registro A brain.highclass.you → IP
#   ssh ubuntu@$(terraform output -raw public_ip)
#
# Custo estimado (eu-west-1, out/2026): m6i.2xlarge sob demanda ~USD 0,384/h ≈ USD 280/mês + 300 GB gp3 ≈ USD 27
# + IP fixo ≈ USD 3,6 + backups ≈ USD 15 → ~USD 330/mês. Com Savings Plan de 1 ano cai ~35%.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
  # Para estado remoto (recomendado quando houver mais de uma pessoa operando), descomente:
  # backend "s3" { bucket = "hcte-terraform-state", key = "brain/terraform.tfstate", region = "eu-west-1", encrypt = true }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "dubai-ai-agency", Owner = "HCTE", ManagedBy = "terraform", Environment = var.environment }
  }
}

# ───────────────────────── rede (VPC padrão da conta; simples e suficiente para uma VM) ─────────────────────────
data "aws_vpc" "default" { default = true }

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ───────────────────────── segurança ─────────────────────────
resource "aws_security_group" "brain" {
  name        = "${var.name}-sg"
  description = "brain: HTTPS publico, SSH restrito"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTPS (dashboard, webhooks, inbox, langfuse)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
  ingress {
    description = "HTTP (so para o Caddy emitir/renovar TLS e redirecionar)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
  dynamic "ingress" {
    for_each = local.uses_tailscale ? [] : [1] # com Tailscale, SSH so pela rede privada
    content {
      description      = "SSH so do IP do operador"
      from_port        = 22
      to_port          = 22
      protocol         = "tcp"
      cidr_blocks      = [var.admin_cidr]
      ipv6_cidr_blocks = var.admin_cidr_v6 == "" ? [] : [var.admin_cidr_v6]
    }
  }
  egress {
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
}

resource "aws_key_pair" "operator" {
  key_name   = "${var.name}-operator"
  public_key = var.ssh_public_key
}

# Papel da instância: só o necessário (CloudWatch agent, SSM para acesso sem SSH, leitura de backups no S3 opcional)
resource "aws_iam_role" "instance" {
  name = "${var.name}-instance-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cloudwatch" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_instance_profile" "instance" {
  name = "${var.name}-instance-profile"
  role = aws_iam_role.instance.name
}

# Bucket para os dumps criptografados do scripts/backup.sh (além do snapshot do disco)
resource "aws_s3_bucket" "backups" {
  bucket_prefix = "${var.name}-backups-"
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    id     = "expire-old-dumps"
    status = "Enabled"
    filter {}
    expiration { days = 90 }
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
}

resource "aws_iam_role_policy" "backups_rw" {
  name = "${var.name}-backups-rw"
  role = aws_iam_role.instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"], Resource = [aws_s3_bucket.backups.arn, "${aws_s3_bucket.backups.arn}/*"] }
    ]
  })
}

# ───────────────────────── a máquina ─────────────────────────
resource "aws_eip" "brain" {
  domain = "vpc"
  tags   = { Name = "${var.name}-eip" }
}

resource "aws_instance" "brain" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.brain.id]
  key_name                    = aws_key_pair.operator.key_name
  iam_instance_profile        = aws_iam_instance_profile.instance.name
  associate_public_ip_address = true
  monitoring                  = true
  ebs_optimized               = true

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.disk_gb
    iops                  = 3000
    throughput            = 250
    encrypted             = true
    delete_on_termination = false # o disco sobrevive a um terminate acidental
    tags                  = { Name = "${var.name}-root", Backup = "daily" }
  }

  metadata_options {
    http_tokens                 = "required" # IMDSv2
    http_put_response_hop_limit = 2          # containers Docker alcançam o IMDS
  }

  user_data = templatefile("${path.module}/cloud-init.yaml", {
    domain             = var.domain
    repo_url           = var.repo_url
    repo_ref           = var.repo_ref
    tailscale_auth_key = var.tailscale_auth_key
    backup_bucket      = aws_s3_bucket.backups.bucket
    aws_region         = var.region
    operator_email     = var.operator_email
  })
  user_data_replace_on_change = false # mudar o cloud-init não recria a máquina

  lifecycle {
    ignore_changes = [ami] # nova AMI não força recriação
  }

  tags = { Name = var.name }
}

resource "aws_eip_association" "brain" {
  instance_id   = aws_instance.brain.id
  allocation_id = aws_eip.brain.id
}

# ───────────────────────── backups do disco (snapshot diário, 14 dias) ─────────────────────────
resource "aws_backup_vault" "brain" {
  name = "${var.name}-vault"
}

resource "aws_backup_plan" "daily" {
  name = "${var.name}-daily"
  rule {
    rule_name         = "daily-0400-dubai"
    target_vault_name = aws_backup_vault.brain.name
    schedule          = "cron(0 0 * * ? *)" # 00:00 UTC = 04:00 Dubai
    lifecycle { delete_after = 14 }
  }
}

resource "aws_iam_role" "backup" {
  name = "${var.name}-backup-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "backup.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_backup_selection" "brain" {
  name         = "${var.name}-root-volume"
  plan_id      = aws_backup_plan.daily.id
  iam_role_arn = aws_iam_role.backup.arn
  resources    = [aws_instance.brain.arn]
}

# ───────────────────────── alarmes (CPU, disco cheio, instância fora) → e-mail do operador ─────────────────────────
resource "aws_sns_topic" "alerts" {
  name = "${var.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.operator_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.operator_email
}

resource "aws_cloudwatch_metric_alarm" "status" {
  alarm_name          = "${var.name}-status-check"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { InstanceId = aws_instance.brain.id }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "cpu" {
  alarm_name          = "${var.name}-cpu-high"
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { InstanceId = aws_instance.brain.id }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "disk" {
  alarm_name          = "${var.name}-disk-low"
  namespace           = "CWAgent"
  metric_name         = "disk_used_percent"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { InstanceId = aws_instance.brain.id, path = "/", device = "nvme0n1p1", fstype = "ext4" }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

# ───────────────────────── orçamento mensal da conta (alerta por e-mail em 80% e 100%) ─────────────────────────
resource "aws_budgets_budget" "monthly" {
  count        = var.operator_email == "" ? 0 : 1
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.operator_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.operator_email]
  }
}
