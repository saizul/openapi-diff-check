FROM python:3.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . \
    && useradd --system --uid 10001 --home-dir /work app \
    && mkdir -p /work \
    && rm -rf /app/build
USER app
WORKDIR /work
ENTRYPOINT ["openapi-diff-check"]
CMD ["--help"]
