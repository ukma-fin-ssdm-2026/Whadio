# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.11.16 AS uv

FROM python:3.13.16-slim-trixie AS build
# The torch build: cpu, or cuda for diarization on an NVIDIA GPU (compose.cuda.yaml).
ARG TORCH=cpu
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-build --no-install-project --extra asr --extra ${TORCH}
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# uv sync cannot build the project alone, so it is built here, and the dependencies above stay
# limited to wheels: no package's setup scripts run during installation.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv build --wheel --out-dir /tmp/dist \
    && uv pip install --python /app/.venv --no-deps --no-build /tmp/dist/whadio-*.whl

FROM python:3.13.16-slim-trixie
RUN useradd --create-home --uid 10001 whadio \
    && install --directory --owner=whadio --group=whadio /var/cache/huggingface
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/var/cache/huggingface
USER whadio
WORKDIR /home/whadio
ENTRYPOINT ["whadio"]
