"""Geração de PDF de cotação/voucher com WeasyPrint e upload para o MinIO (S3)."""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from jinja2 import Template

from brain.settings import agency_config, get_settings, market

QUOTE_HTML = Template("""
<!doctype html><html lang="{{ lang }}"><head><meta charset="utf-8">
<style>
 @page { size: A4; margin: 18mm; }
 body { font-family: 'Noto Sans', sans-serif; color:#1b1b1b; font-size: 11pt; }
 h1 { font-size: 20pt; margin: 0 0 4px; } .muted { color:#666; font-size: 9pt; }
 table { width:100%; border-collapse: collapse; margin-top: 14px; }
 th, td { text-align:left; padding: 7px 6px; border-bottom: 1px solid #e3e3e3; } th { background:#f4f4f4; font-size: 9.5pt; }
 .total { font-size: 14pt; font-weight: 700; text-align:right; margin-top: 10px; }
 .box { border:1px solid #ddd; padding:10px 12px; border-radius:6px; margin-top:14px; font-size: 9.5pt; }
 .lic { margin-top:18px; font-size: 8.5pt; color:#555; border-top:1px solid #ddd; padding-top:8px; }
</style></head><body>
<h1>{{ agency.name }}</h1>
<div class="muted">{{ agency.legal_name }} · Licença DET {{ agency.det_license_number }} · {{ agency.website }}</div>
<h2 style="margin-top:22px">{{ title }}</h2>
<div class="muted">Para {{ client }} · emitida em {{ issued }} · válida até {{ valid_until }}</div>
<table><thead><tr><th>Item</th><th>Data</th><th>Qtd</th><th>Unitário (USD)</th><th>Total (USD)</th></tr></thead><tbody>
{% for l in lines %}<tr><td>{{ l.name }}</td><td>{{ l.date or '—' }}</td><td>{{ l.qty }}</td><td>{{ '%.2f'|format(l.unit_sell_usd) }}</td><td>{{ '%.2f'|format(l.unit_sell_usd * l.qty) }}</td></tr>{% endfor %}
</tbody></table>
{% if discount_pct %}<div style="text-align:right;margin-top:6px">Desconto: {{ discount_pct }}%</div>{% endif %}
<div class="total">Total: USD {{ '%.2f'|format(total_usd) }} &nbsp;·&nbsp; {{ currency }} {{ '%.2f'|format(total_local) }}</div>
<div class="muted" style="text-align:right">Preço final. Inclui todas as taxas e impostos aplicáveis dos fornecedores. Câmbio indicativo.</div>
<div class="box"><b>Cancelamento e pagamento</b><br>{{ policies.cancellation }}<br><br>{{ policies.payment }}</div>
<div class="box"><b>Seus dados</b><br>{{ policies.data }}</div>
<div class="lic">Serviços operados por fornecedores licenciados pela Dubai Department of Economy and Tourism. Esta cotação não inclui passagem aérea. {{ agency.legal_name }} · Licença DET {{ agency.det_license_number }}.</div>
</body></html>
""")


async def upload_bytes(key: str, data: bytes, content_type: str = "application/pdf") -> str:
    """Envia para o MinIO e devolve URL pública (via Caddy /docs/...)."""
    import boto3  # opcional; incluído via botocore no ambiente docker se necessário

    s = get_settings()
    if not s.s3_endpoint:  # sem object store: grava em /app/state/docs (volume brainstate) e serve em /docs/<key>
        from pathlib import Path
        path = Path("/app/state/docs") / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"https://{s.domain}/docs/{key}"
    try:
        client = boto3.client("s3", endpoint_url=s.s3_endpoint, aws_access_key_id=s.minio_user, aws_secret_access_key=s.minio_password)
        try:
            client.head_bucket(Bucket=s.s3_bucket_docs)
        except Exception:  # noqa: BLE001
            client.create_bucket(Bucket=s.s3_bucket_docs)
        client.put_object(Bucket=s.s3_bucket_docs, Key=key, Body=data, ContentType=content_type)
    except Exception:  # noqa: BLE001 — object store fora do ar: nunca travar a cotação; cai para disco local
        from pathlib import Path
        path = Path("/app/state/docs") / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return f"https://{s.domain}/docs/{key}"


async def render_quote(q: dict[str, Any]) -> str:
    from weasyprint import HTML  # import tardio: pesado

    cfg = agency_config()
    mk = market(q["market_code"])
    html = QUOTE_HTML.render(
        lang=mk["language"].split("-")[0], agency=cfg["agency"], policies=cfg["policies"],
        title=q["title"], client=q.get("display_name") or "cliente", issued=datetime.now().strftime("%d/%m/%Y"),
        valid_until=q["valid_until"], lines=q["items"], discount_pct=q["discount_pct"], total_usd=float(q["total_usd"]),
        currency=q["local_currency"], total_local=float(q["total_local"] or 0),
    )
    buf = io.BytesIO()
    HTML(string=html).write_pdf(buf)
    return await upload_bytes(f"quotes/{q['id']}.pdf", buf.getvalue())
