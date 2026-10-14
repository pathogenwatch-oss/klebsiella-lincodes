FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim AS base

COPY src uv.lock pyproject.toml LICENSE README.md scheme.toml host_config.json /plincer/

WORKDIR /plincer

RUN uv build --wheel && mkdir /build && mv LICENSE README.md scheme.toml host_config.json pyproject.toml uv.lock dist/*.whl /build/

FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim AS prod

ARG LOG=DEBUG
ENV LOG=${LOG}
ARG BUILD_DATE
LABEL build_data=$BUILD_DATE

COPY --from=base /build /plincer

WORKDIR /plincer

RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements.txt

RUN uv pip install --system --requirement requirements.txt \
    && uv pip install --system --no-deps ./*.whl

RUN --mount=type=secret,id=secrets \
    --mount=type=cache,target=/cache \
    plincer \
    build \
    --secrets-file /run/secrets/secrets  \
    --secrets-cache-file /cache/secrets_cache.json \
    -l ${LOG}

ENTRYPOINT ["plincer", "classify", "-"]
