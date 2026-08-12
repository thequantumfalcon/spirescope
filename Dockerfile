# Digest for the python:3.12-slim multi-arch tag, resolved 2026-08-12 against
# registry-1.docker.io/v2/library/python/manifests/3.12-slim. Re-resolve and
# bump this when a rebuild against a newer 3.12-slim is wanted.
FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

WORKDIR /app

# Copy project files and install
COPY pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY sts2/ sts2/
RUN pip install --no-cache-dir .

# Non-root user for security. /app must be writable by it for the source
# tree, but user state (language setting, hypotheses, community aggregate) no
# longer lives under /app/sts2/data — the data/state split moved it to the
# XDG path, ~/.local/share/SpireScope, which for this container's appuser
# resolves to /home/appuser/.local/share/SpireScope. That path is created and
# chowned too, or the same class of bug this comment used to describe (silent
# write failures, the language switcher 400ing on a locale its own dropdown
# had just offered) would recur under the new path instead.
RUN useradd --create-home appuser \
    && mkdir -p /home/appuser/.local/share/SpireScope \
    && chown -R appuser:appuser /app /home/appuser/.local/share/SpireScope
USER appuser

EXPOSE 8000

ENV STS2_HOST=0.0.0.0
ENV STS2_PORT=8000

# Persists the language setting, hypotheses, run aggregate, etc. across
# container recreation — see the state-dir comment above.
VOLUME /home/appuser/.local/share/SpireScope

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "-m", "sts2"]
