FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim AS base

COPY src uv.lock pyproject.toml LICENSE README.md scheme.toml /plincer/

WORKDIR /plincer

RUN uv build --wheel && mkdir /build && mv LICENSE README.md scheme.toml dist/*.whl /build/

FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim AS prod

ARG VERSION
ENV VERSION=${VERSION}

COPY --from=base /build /plincer

WORKDIR /plincer

RUN uv pip install --system plincer-"${VERSION}"-py3-none-any.whl

RUN plincer build

ENTRYPOINT ["plincer", "classify"]
