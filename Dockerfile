FROM python:3.12-slim

WORKDIR /app

# Copy project files and install
COPY pyproject.toml README.md ./
COPY sts2/ sts2/
RUN pip install --no-cache-dir .

# Non-root user for security. /app must be writable by it: DATA_DIR resolves to
# /app/sts2/data here (not frozen, no STS2_DATA_DIR), and that is where the
# language setting, hypotheses and community aggregate are persisted. Left
# root-owned, every write silently failed and the language switcher answered
# 400 for a locale its own dropdown had just offered.
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENV STS2_HOST=0.0.0.0
ENV STS2_PORT=8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "-m", "sts2"]
