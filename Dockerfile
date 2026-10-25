FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[hosted]"

# Non-root user for security
RUN adduser --disabled-password --no-create-home appuser
USER appuser

# Default to remote MCP mode
ENV ALTFINANCE_TRANSPORT=streamable-http
ENV ALTFINANCE_HOST=0.0.0.0
ENV ALTFINANCE_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "altfinance_mcp"]
