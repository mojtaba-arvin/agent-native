# The multi-platform index digest is pinned in container/base-image.lock.
ARG PYTHON_BASE=python:3.11.18-slim-bookworm@sha256:94a8fee35252d06ab75856f15f12c7bae67b10e8a6da93c7fded82b2610926cd

FROM --platform=$TARGETPLATFORM ${PYTHON_BASE} AS builder
ARG SOURCE_DATE_EPOCH=0
ARG SOURCE_REVISION=unknown
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} \
    PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build

COPY container/build-requirements.lock /tmp/build-requirements.lock
RUN python -m pip install --require-hashes --no-deps -r /tmp/build-requirements.lock

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN mkdir -p /wheelhouse && \
    python -m pip wheel --no-build-isolation --no-deps --no-cache-dir \
      --wheel-dir=/wheelhouse . && \
    python -m pip wheel --no-deps --no-cache-dir --wheel-dir=/wheelhouse \
      "psycopg==3.2.12" "psycopg-binary==3.2.12" "typing-extensions==4.15.0"

FROM --platform=$TARGETPLATFORM ${PYTHON_BASE} AS runtime
ARG SOURCE_DATE_EPOCH=0
ARG SOURCE_REVISION=unknown
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} \
    PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp
LABEL org.opencontainers.image.title="Agent Native" \
      org.opencontainers.image.description="Agent-first backend framework CLI and runtime package" \
      org.opencontainers.image.source="https://github.com/mojtaba-arvin/agent-native" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="0.1.0.dev0" \
      org.opencontainers.image.revision="${SOURCE_REVISION}"
WORKDIR /opt/agent-native
COPY --from=builder /wheelhouse /tmp/wheelhouse
RUN python -m pip install --no-index --no-deps --find-links=/tmp/wheelhouse \
      "psycopg==3.2.12" "psycopg-binary==3.2.12" "typing-extensions==4.15.0" agent-native==0.1.0.dev0 && \
    rm -rf /tmp/wheelhouse
USER 65532:65532
ENTRYPOINT ["agent-native"]
CMD ["--help"]
