output "public_ip" {
  description = "IP fixo — crie o registro A do domínio apontando para ele"
  value       = aws_eip.brain.public_ip
}

output "dns_record" {
  value = "${var.domain}.  A  ${aws_eip.brain.public_ip}"
}

locals {
  uses_tailscale = nonsensitive(var.tailscale_auth_key != "")
}

output "ssh" {
  value = local.uses_tailscale ? "ssh ubuntu@${var.name}  (via Tailscale) — ou: aws ssm start-session --target ${aws_instance.brain.id}" : "ssh ubuntu@${aws_eip.brain.public_ip}"
}

output "instance_id" {
  value = aws_instance.brain.id
}

output "backup_bucket" {
  value = aws_s3_bucket.backups.bucket
}

output "next_steps" {
  value = <<-EOT
    1. DNS: ${var.domain} → ${aws_eip.brain.public_ip} (registro A; TTL 300). Espere propagar (dig +short ${var.domain}).
    2. Entre na máquina e confira o cloud-init: ssh ubuntu@${aws_eip.brain.public_ip} 'cloud-init status --wait && tail -20 /var/log/brain-bootstrap.log'
    3. Se não usou repo_url: scp dubai-ai-agency.zip ubuntu@${aws_eip.brain.public_ip}:/opt/ && ssh ... 'cd /opt && sudo unzip -o dubai-ai-agency.zip && sudo chown -R ubuntu:ubuntu dubai-ai-agency'
    4. cd /opt/dubai-ai-agency && bash scripts/init_env.sh   (gera os segredos; pergunta Anthropic, Jev, senha do dashboard, WhatsApp)
    5. make up && make migrate && make check && make jev-smoke  → https://${var.domain}/
    6. Backups: snapshots diários já ativos; 'make backup' envia dumps para s3://${aws_s3_bucket.backups.bucket}
  EOT
}
