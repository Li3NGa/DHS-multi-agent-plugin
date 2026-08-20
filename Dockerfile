FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    CONFIG=/app/example_config.yaml \
    DS_AGENT_TOKEN=""

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY example_config.yaml /app/example_config.yaml
COPY docker-entrypoint.sh /usr/local/bin/deepseek-multi-agent-entrypoint
RUN chmod +x /usr/local/bin/deepseek-multi-agent-entrypoint

# 纵深防御：容器内以非 root 用户运行，避免服务被攻破后直接获得容器 root。
RUN addgroup --system dsma && adduser --system --ingroup dsma --home /app dsma \
    && chown -R dsma:dsma /app

USER dsma

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; p=os.environ.get('PORT','8000'); t=os.environ.get('DS_AGENT_TOKEN',''); req=urllib.request.Request('http://127.0.0.1:'+p+'/health', headers={'Authorization':'Bearer '+t}); urllib.request.urlopen(req, timeout=3)"]

ENTRYPOINT ["/usr/local/bin/deepseek-multi-agent-entrypoint"]
