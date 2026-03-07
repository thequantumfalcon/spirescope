FROM python:3.12-slim

WORKDIR /app

# Copy project files and install
COPY pyproject.toml .
COPY sts2/ sts2/
RUN pip install --no-cache-dir .

# Non-root user for security
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

ENV STS2_HOST=0.0.0.0
ENV STS2_PORT=8000

CMD ["python", "-m", "sts2"]
