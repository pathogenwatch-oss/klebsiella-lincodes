FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim AS base

COPY src uv.lock pyproject.toml LICENSE README.md scheme.toml host_config.json /plincer/

WORKDIR /plincer

RUN uv build --wheel && mkdir /build && mv LICENSE README.md scheme.toml host_config.json dist/*.whl /build/

FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim AS prod

ARG VERSION
ARG LOG=DEBUG
ENV VERSION=${VERSION}
ENV LOG=${LOG}

COPY --from=base /build /plincer

WORKDIR /plincer

RUN uv pip install --system plincer-"${VERSION}"-py3-none-any.whl

RUN --mount=type=secret,id=secrets \
    --mount=type=cache,target=/cache \
    plincer \
    build \
    --secrets-file /run/secrets/secrets  \
    --secrets-cache-file /cache/secrets_cache.json \
    -l ${LOG}

ENTRYPOINT ["plincer", "classify"]
