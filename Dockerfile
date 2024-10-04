FROM python:3.11 AS builder

RUN pip --disable-pip-version-check --no-cache-dir install requests toml tenacity

COPY scheme.toml /scheme.toml

COPY build.py /build.py

RUN python3 /build.py

FROM python:3.11-alpine

RUN pip install toml

COPY --from=builder /profiles.json /profiles.json

COPY scheme.toml /scheme.toml

COPY classify.py /classify.py

ENTRYPOINT ["python3", "/classify.py"]
