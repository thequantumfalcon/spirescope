FROM python:3.12-slim AS base

WORKDIR /app

# Install dependencies only (cached layer)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY sts2/ sts2/

# Non-root user for security
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

ENV STS2_HOST=0.0.0.0
ENV STS2_PORT=8000

CMD ["python", "-m", "sts2"]
