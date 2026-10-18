FROM python:3.12-slim

ENV CLAUDE_CONFIG_DIR=/app/state/claude \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Node é necessário para o runtime do Claude Agent SDK (Claude Code CLI) e para WeasyPrint/fonts dos PDFs
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg git build-essential \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 libjpeg62-turbo fonts-noto fonts-noto-cjk fonts-noto-color-emoji \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y build-essential gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e . 2>/dev/null || pip install \
      "claude-agent-sdk>=0.1.0" "anthropic>=0.60" "fastapi>=0.115" "uvicorn[standard]>=0.30" \
      "asyncpg>=0.29" "redis>=5.0" "apscheduler>=3.10" "pydantic>=2.7" "pydantic-settings>=2.3" \
      "httpx>=0.27" "pyyaml>=6.0" "jinja2>=3.1" "weasyprint>=62" "langfuse>=2.50" \
      "cryptography>=42" "python-multipart>=0.0.9" "aiosmtplib>=3.0" "aioimaplib>=1.1" "structlog>=24.1"

COPY brain ./brain
COPY config ./config
COPY prompts ./prompts
COPY db ./db
COPY evals ./evals
COPY scripts ./scripts
COPY knowledge ./knowledge

RUN useradd -m brain && mkdir -p /app/state/claude && chown -R brain:brain /app
USER brain

EXPOSE 8000
CMD ["uvicorn", "brain.main:app", "--host", "0.0.0.0", "--port", "8000"]
